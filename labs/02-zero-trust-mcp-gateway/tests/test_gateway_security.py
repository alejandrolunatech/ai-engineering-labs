"""Phase 5: deterministic security tests for the Zero-Trust MCP Gateway.

Question under test:
    "Can an untrusted caller cause an unauthorized downstream action to execute?"

Everything here is deterministic: no LLM, no external network. The
authorization matrix runs against the REAL policy in a temporary local OPA
process. Only OPA failure modes (unreachable, timeout, malformed output) use a
fake OPA on localhost, because real OPA cannot be made to misbehave on demand.

Separation under test:
    caller request (tool + arguments)  untrusted
    TrustedContext                     trusted, set by the test as gateway config
    OPA / gateway.rego                 Policy Decision Point
    Gateway                            Policy Enforcement Point
    commerce MCP server + store        side-effect executor

"Did not execute" is proven three independent ways for every denial:
    1. SpyDownstream saw no tools/call from the gateway;
    2. the store snapshot (customers, orders, refunds, exports) is unchanged;
    3. the audit trail for the decision is exactly requested -> denied.
"""

from __future__ import annotations

import copy
import json
import shutil
import socket
import subprocess
import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import httpx
import pytest
from mcp import Client

from src.zero_trust_mcp.audit import AuditLog
from src.zero_trust_mcp.commerce_server import build_server
from src.zero_trust_mcp.gateway import Gateway, TrustedContext, build_gateway_server
from src.zero_trust_mcp.policy import OpaPolicyClient
from src.zero_trust_mcp.store import CommerceStore

POLICY_FILE = Path(__file__).resolve().parents[1] / "policies" / "gateway.rego"

AUDITOR = TrustedContext(principal_id="auditor-1", role="auditor")
SUPPORT = TrustedContext(principal_id="support-42", role="support")
FINANCE = TrustedContext(principal_id="finance-7", role="finance")
COMPLIANCE = TrustedContext(principal_id="compliance-3", role="compliance")
COMPLIANCE_APPROVED = TrustedContext(principal_id="compliance-3", role="compliance", human_approved=True)
UNKNOWN_ROLE = TrustedContext(principal_id="root-0", role="superuser")
NO_PRINCIPAL = TrustedContext(principal_id=None, role=None)

REFUND_SCHEMA_KEYS = {"order_id", "amount_cents", "reason"}


def refund_args(amount_eur: float, reason: str = "duplicate charge", **extra: Any) -> dict[str, Any]:
    return {"order_id": "ord-1003", "amount_cents": round(amount_eur * 100), "reason": reason, **extra}


def export_args(**extra: Any) -> dict[str, Any]:
    return {"customer_id": "cust-001", **extra}


# --- Real OPA process -----------------------------------------------------------


def _free_localhost_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def opa_url():
    opa = shutil.which("opa")
    if opa is None:
        pytest.fail("`opa` binary not found: the security suite must not be skipped silently")

    port = _free_localhost_port()
    url = f"http://127.0.0.1:{port}"
    proc = subprocess.Popen(
        [opa, "run", "--server", "--addr", f"127.0.0.1:{port}", "--log-level", "error", str(POLICY_FILE)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    try:
        deadline = time.monotonic() + 10
        while True:
            if proc.poll() is not None:
                pytest.fail(f"OPA exited early: {proc.stderr.read().decode(errors='replace')}")
            try:
                if httpx.get(f"{url}/health", timeout=0.5).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            if time.monotonic() > deadline:
                pytest.fail("OPA did not become healthy within 10s")
            time.sleep(0.05)

        # Healthy is not enough: prove the gateway policy is loaded and answering.
        probe = httpx.post(f"{url}/v1/data/gateway/decision", json={"input": {}}, timeout=2).json()
        assert probe["result"]["rule_id"] == "deny.missing_principal", probe
        yield url
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()


# --- Fake OPA for failure modes only ---------------------------------------------


@dataclass
class FakeOpaResponse:
    status: int = 200
    body: bytes = b"{}"
    delay_s: float = 0.0


@pytest.fixture
def fake_opa():
    """Localhost HTTP server whose reply each test sets via `server.reply`."""

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            reply: FakeOpaResponse = self.server.reply
            self.rfile.read(int(self.headers.get("Content-Length", 0)))
            if reply.delay_s:
                time.sleep(reply.delay_s)
            self.send_response(reply.status)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(reply.body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    server.reply = FakeOpaResponse()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server, f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


# --- Harness ------------------------------------------------------------------------


class SpyDownstream:
    """Pass-through wrapper recording every tools/call the gateway sends downstream."""

    def __init__(self, client: Client) -> None:
        self._client = client
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def list_tools(self):
        return await self._client.list_tools()

    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None):
        self.calls.append((name, copy.deepcopy(arguments)))
        return await self._client.call_tool(name, arguments)


@dataclass
class Outcome:
    result: Any
    store: CommerceStore
    before: dict[str, Any]
    spy: SpyDownstream
    audit: AuditLog
    policy_inputs: list[dict[str, Any]] = field(default_factory=list)

    @property
    def denied(self) -> bool:
        sc = self.result.structured_content or {}
        return bool(self.result.is_error) and sc.get("denied") is True

    @property
    def rule_id(self) -> str | None:
        return (self.result.structured_content or {}).get("rule_id")

    def events(self) -> list[str]:
        return [e["event"] for e in self.audit.events]


def snapshot(store: CommerceStore) -> dict[str, Any]:
    return copy.deepcopy(
        {"customers": store.customers, "orders": store.orders, "refunds": store.refunds, "exports": store.exports}
    )


async def call_through_gateway(context: TrustedContext, policy, tool: str, arguments: dict[str, Any], **call_kw) -> Outcome:
    store, audit = CommerceStore.from_seed(), AuditLog()
    before = snapshot(store)
    async with Client(build_server(store)) as downstream_client:
        spy = SpyDownstream(downstream_client)
        gateway = Gateway(context, policy, spy, audit)
        async with Client(build_gateway_server(gateway)) as agent:
            result = await agent.call_tool(tool, arguments, **call_kw)
    return Outcome(result, store, before, spy, audit)


def assert_denied_without_execution(out: Outcome, rule_id: str) -> None:
    # 0. The caller receives a structured denial from the PEP.
    assert out.denied, out.result
    assert out.rule_id == rule_id
    # 1. The gateway never sent anything to the executor.
    assert out.spy.calls == []
    # 2. The executor's state is untouched.
    assert snapshot(out.store) == out.before
    assert out.store.refunds == [] and out.store.exports == []
    # 3. The audit trail records the attempt and the denial, and nothing else.
    assert out.events() == ["requested", "denied"]
    assert out.audit.events[-1]["downstream_executed"] is False
    assert out.audit.events[-1]["rule_id"] == rule_id


def assert_allowed_and_executed_once(out: Outcome, tool: str, rule_id: str) -> None:
    assert not out.result.is_error, out.result
    assert len(out.spy.calls) == 1 and out.spy.calls[0][0] == tool
    assert out.events() == ["requested", "allowed", "executed"]
    allowed_event = out.audit.events[1]
    assert allowed_event["rule_id"] == rule_id
    assert out.audit.events[-1]["downstream_executed"] is True
    assert out.audit.events[-1]["downstream_error"] is False
    assert len({e["decision_id"] for e in out.audit.events}) == 1


@pytest.fixture
def opa(opa_url) -> OpaPolicyClient:
    return OpaPolicyClient(opa_url)


# --- 1-9: role x tool authorization matrix (real OPA) ------------------------------


async def test_01_auditor_get_order_allowed(opa):
    out = await call_through_gateway(AUDITOR, opa, "get_order", {"order_id": "ord-1001"})
    assert_allowed_and_executed_once(out, "get_order", "allow.get_order")
    assert out.result.structured_content["order_id"] == "ord-1001"
    assert snapshot(out.store) == out.before  # a read has no side effect


async def test_02_auditor_refund_denied(opa):
    out = await call_through_gateway(AUDITOR, opa, "issue_refund", refund_args(25))
    assert_denied_without_execution(out, "deny.tool_not_permitted_for_role")


async def test_03_support_refund_25_with_reason_allowed_once(opa):
    out = await call_through_gateway(SUPPORT, opa, "issue_refund", refund_args(25))
    assert_allowed_and_executed_once(out, "issue_refund", "allow.refund.within_limit")
    assert out.store.refunds == [
        {"refund_id": "rf-0001", "order_id": "ord-1003", "amount_cents": 2500, "reason": "duplicate charge"}
    ]
    assert out.store.exports == []


async def test_04_support_refund_250_denied(opa):
    out = await call_through_gateway(SUPPORT, opa, "issue_refund", refund_args(250, order_id="ord-1002"))
    assert_denied_without_execution(out, "deny.refund.over_limit")


async def test_05_finance_refund_250_allowed_once(opa):
    out = await call_through_gateway(FINANCE, opa, "issue_refund", {"order_id": "ord-1002", "amount_cents": 25000, "reason": "damaged"})
    assert_allowed_and_executed_once(out, "issue_refund", "allow.refund.within_limit")
    assert len(out.store.refunds) == 1
    assert out.store.refunds[0]["order_id"] == "ord-1002"
    assert out.store.refunds[0]["amount_cents"] == 25000


async def test_06_finance_refund_750_denied(opa):
    # ord-1004 totals 1200 EUR, so the downstream business rule would accept 750:
    # only the policy stands between this request and the side effect.
    out = await call_through_gateway(FINANCE, opa, "issue_refund", {"order_id": "ord-1004", "amount_cents": 75000, "reason": "x"})
    assert_denied_without_execution(out, "deny.refund.over_limit")


async def test_07_support_export_denied(opa):
    out = await call_through_gateway(SUPPORT, opa, "export_customer_record", export_args())
    assert_denied_without_execution(out, "deny.tool_not_permitted_for_role")


async def test_08_compliance_export_without_trusted_approval_denied(opa):
    out = await call_through_gateway(COMPLIANCE, opa, "export_customer_record", export_args())
    assert_denied_without_execution(out, "deny.export.approval_required")


async def test_09_compliance_export_with_trusted_approval_allowed_once(opa):
    out = await call_through_gateway(COMPLIANCE_APPROVED, opa, "export_customer_record", export_args())
    assert_allowed_and_executed_once(out, "export_customer_record", "allow.export.human_approved")
    assert out.store.exports == ["cust-001"]
    assert out.store.refunds == []
    assert out.result.structured_content["email"] == "ada.testwell@example.test"


# --- 10-12: unknown / missing identity and capability --------------------------------


async def test_10_unknown_role_denied(opa):
    for tool, args in [("get_order", {"order_id": "ord-1001"}), ("issue_refund", refund_args(1)), ("export_customer_record", export_args())]:
        out = await call_through_gateway(UNKNOWN_ROLE, opa, tool, args)
        assert_denied_without_execution(out, "deny.unknown_role")


async def test_11_unknown_tool_denied_and_never_reaches_downstream(opa):
    out = await call_through_gateway(COMPLIANCE_APPROVED, opa, "delete_all_customers", {"confirm": True})
    assert_denied_without_execution(out, "deny.unknown_tool")


async def test_12_missing_principal_denied(opa):
    out = await call_through_gateway(NO_PRINCIPAL, opa, "issue_refund", refund_args(1))
    assert_denied_without_execution(out, "deny.missing_principal")


# --- 13-14: PDP failure modes must fail closed ----------------------------------------
#
# Each uses a request that real OPA WOULD allow (support refund 25 EUR), so a
# fail-open bug would show up as an executed refund.


async def test_13_opa_unavailable_fails_closed():
    # Bind then close a port so nothing is listening on it.
    dead = OpaPolicyClient(f"http://127.0.0.1:{_free_localhost_port()}", timeout_s=0.5)
    out = await call_through_gateway(SUPPORT, dead, "issue_refund", refund_args(25))
    assert_denied_without_execution(out, "gateway.policy_unavailable")


async def test_13b_opa_timeout_fails_closed(fake_opa):
    server, url = fake_opa
    allow = {"result": {"allow": True, "reason": "late", "rule_id": "allow.late"}}
    server.reply = FakeOpaResponse(body=json.dumps(allow).encode(), delay_s=1.0)
    out = await call_through_gateway(SUPPORT, OpaPolicyClient(url, timeout_s=0.2), "issue_refund", refund_args(25))
    assert_denied_without_execution(out, "gateway.policy_timeout")


MALFORMED_OPA_RESPONSES = {
    "http_500": (FakeOpaResponse(status=500, body=b'{"result": {"allow": true}}'), "gateway.policy_error"),
    "not_json": (FakeOpaResponse(body=b"allow"), "gateway.policy_malformed"),
    "no_decision": (FakeOpaResponse(body=b"{}"), "gateway.no_decision"),
    "result_not_object": (FakeOpaResponse(body=b'{"result": true}'), "gateway.policy_malformed"),
    "allow_string_true": (
        FakeOpaResponse(body=b'{"result": {"allow": "true", "reason": "r", "rule_id": "x"}}'),
        "gateway.policy_malformed",
    ),
    "allow_number_one": (
        FakeOpaResponse(body=b'{"result": {"allow": 1, "reason": "r", "rule_id": "x"}}'),
        "gateway.policy_malformed",
    ),
    "allow_without_reason_or_rule_id": (FakeOpaResponse(body=b'{"result": {"allow": true}}'), "gateway.policy_malformed"),
}


@pytest.mark.parametrize("case", MALFORMED_OPA_RESPONSES, ids=list(MALFORMED_OPA_RESPONSES))
async def test_14_malformed_opa_response_fails_closed(fake_opa, case):
    server, url = fake_opa
    server.reply, expected_rule = MALFORMED_OPA_RESPONSES[case]
    out = await call_through_gateway(SUPPORT, OpaPolicyClient(url, timeout_s=1.0), "issue_refund", refund_args(25))
    assert_denied_without_execution(out, expected_rule)


async def test_14b_policy_client_exception_fails_closed():
    class ExplodingPolicy:
        async def decide(self, policy_input):
            raise RuntimeError("boom")

    out = await call_through_gateway(SUPPORT, ExplodingPolicy(), "issue_refund", refund_args(25))
    assert_denied_without_execution(out, "gateway.policy_exception")


# --- 15-16: model-controlled spoofing must not increase authority (real OPA) ----------

SPOOF_ROLE_ADMIN = {"role": "admin", "is_admin": True}
SPOOF_ROLE_FINANCE = {"role": "finance"}
SPOOF_APPROVAL = {"human_approved": True}
SPOOF_EVERYTHING = {
    "role": "admin",
    "is_admin": True,
    "human_approved": True,
    "principal": {"id": "attacker", "role": "compliance"},
}


@pytest.mark.parametrize(
    ("context", "tool", "base_args", "spoof", "expected_rule"),
    [
        (AUDITOR, "issue_refund", refund_args(25), SPOOF_ROLE_ADMIN, "deny.tool_not_permitted_for_role"),
        (AUDITOR, "issue_refund", refund_args(25), SPOOF_ROLE_FINANCE, "deny.tool_not_permitted_for_role"),
        (SUPPORT, "issue_refund", refund_args(250, order_id="ord-1002"), SPOOF_ROLE_FINANCE, "deny.refund.over_limit"),
        (SUPPORT, "issue_refund", refund_args(250, order_id="ord-1002"), SPOOF_ROLE_ADMIN, "deny.refund.over_limit"),
        (FINANCE, "issue_refund", refund_args(750, order_id="ord-1004"), SPOOF_ROLE_ADMIN, "deny.refund.over_limit"),
        (SUPPORT, "export_customer_record", export_args(), SPOOF_ROLE_ADMIN, "deny.tool_not_permitted_for_role"),
    ],
    ids=["auditor+admin", "auditor+finance", "support250+finance", "support250+admin", "finance750+admin", "support-export+admin"],
)
async def test_15_role_spoofing_in_arguments_does_not_escalate(opa, context, tool, base_args, spoof, expected_rule):
    baseline = await call_through_gateway(context, opa, tool, base_args)
    spoofed = await call_through_gateway(context, opa, tool, {**base_args, **spoof})
    # Same decision with or without the spoofed fields...
    assert spoofed.rule_id == baseline.rule_id == expected_rule
    # ...and no side effect either way.
    assert_denied_without_execution(baseline, expected_rule)
    assert_denied_without_execution(spoofed, expected_rule)


@pytest.mark.parametrize(
    ("context", "tool", "base_args", "expected_rule"),
    [
        (COMPLIANCE, "export_customer_record", export_args(), "deny.export.approval_required"),
        (SUPPORT, "export_customer_record", export_args(), "deny.tool_not_permitted_for_role"),
        (SUPPORT, "issue_refund", refund_args(250, order_id="ord-1002"), "deny.refund.over_limit"),
        (AUDITOR, "issue_refund", refund_args(25), "deny.tool_not_permitted_for_role"),
    ],
    ids=["compliance-export", "support-export", "support-refund250", "auditor-refund"],
)
@pytest.mark.parametrize("spoof", [SPOOF_APPROVAL, SPOOF_EVERYTHING], ids=["human_approved", "everything"])
async def test_16_approval_spoofing_in_arguments_does_not_escalate(opa, context, tool, base_args, expected_rule, spoof):
    assert context.human_approved is False  # trusted approval really is absent
    out = await call_through_gateway(context, opa, tool, {**base_args, **spoof})
    assert_denied_without_execution(out, expected_rule)


async def test_16b_spoofing_via_request_meta_is_ignored(opa):
    """`_meta` is caller-controlled too; the gateway never reads it for authorization."""
    out = await call_through_gateway(
        COMPLIANCE, opa, "export_customer_record", export_args(),
        meta={"role": "admin", "human_approved": True, "principal": {"role": "compliance"}},
    )
    assert_denied_without_execution(out, "deny.export.approval_required")


async def test_15_16_spoofed_fields_reach_policy_only_as_untrusted_arguments(opa):
    """The policy sees the spoof attempt (observable), but only under `arguments`."""
    seen: list[dict[str, Any]] = []

    class RecordingOpa(OpaPolicyClient):
        async def decide(self, policy_input):
            seen.append(copy.deepcopy(policy_input))
            return await super().decide(policy_input)

    await call_through_gateway(
        SUPPORT, RecordingOpa(opa._url.removesuffix("/v1/data/gateway/decision")),
        "export_customer_record", export_args(**SPOOF_EVERYTHING),
    )
    (policy_input,) = seen
    assert policy_input["principal"] == {"id": "support-42", "role": "support"}
    assert policy_input["human_approved"] is False
    assert policy_input["arguments"]["role"] == "admin"
    assert policy_input["arguments"]["human_approved"] is True


# --- 17: after authorization, only schema-declared arguments are forwarded ------------


async def test_17_undeclared_arguments_are_not_forwarded_after_allow(opa):
    spoofed = refund_args(25, **SPOOF_EVERYTHING, refund_limit=5000, override="SYSTEM OVERRIDE")
    out = await call_through_gateway(SUPPORT, opa, "issue_refund", spoofed)

    # Allowed on its own merits (support, 25 EUR, reason) - not because of the spoof.
    assert_allowed_and_executed_once(out, "issue_refund", "allow.refund.within_limit")
    # Exactly the schema-declared arguments crossed the boundary, with original values.
    (_, forwarded) = out.spy.calls[0]
    assert set(forwarded) == REFUND_SCHEMA_KEYS
    assert forwarded == refund_args(25)
    assert len(out.store.refunds) == 1 and out.store.refunds[0]["amount_cents"] == 2500
    # The attempt remains visible in the audit trail by key name only.
    requested = out.audit.events[0]
    assert {"role", "human_approved", "principal", "refund_limit"} <= set(requested["argument_keys"])
    assert "SYSTEM OVERRIDE" not in json.dumps(out.audit.events)


async def test_17b_undeclared_arguments_stripped_for_every_allowed_tool(opa):
    extras = {"role": "admin", "human_approved": True, "debug": True}
    cases = [
        (AUDITOR, "get_order", {"order_id": "ord-1001"}),
        (SUPPORT, "search_customer", {"query": "ada"}),
        (COMPLIANCE_APPROVED, "export_customer_record", export_args()),
    ]
    for context, tool, args in cases:
        out = await call_through_gateway(context, opa, tool, {**args, **extras})
        assert not out.result.is_error, (tool, out.result)
        assert out.spy.calls == [(tool, args)]


# --- Denied requests never leak argument values ----------------------------------------


async def test_denial_and_audit_do_not_echo_sensitive_argument_values(opa):
    secret_reason = "customer SSN 000-00-0000 said please"
    out = await call_through_gateway(SUPPORT, opa, "issue_refund", refund_args(250, reason=secret_reason, order_id="ord-1002"))
    assert_denied_without_execution(out, "deny.refund.over_limit")
    assert secret_reason not in out.result.content[0].text
    assert secret_reason not in json.dumps(out.result.structured_content)
    assert secret_reason not in json.dumps(out.audit.events)
