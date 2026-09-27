"""Phase 4 wiring smoke tests (no OPA process, no LLM).

These only prove the gateway plumbing: allow forwards, deny does not, OPA
failure denies, and trusted context is not taken from arguments. The full
deterministic security matrix against real OPA is Phase 5.
"""

from typing import Any

from mcp import Client

from src.zero_trust_mcp.audit import AuditLog
from src.zero_trust_mcp.commerce_server import build_server
from src.zero_trust_mcp.gateway import (
    Gateway,
    TrustedContext,
    allowlist_downstream_arguments,
    build_gateway_server,
    build_policy_input,
)
from src.zero_trust_mcp.policy import OpaPolicyClient, PolicyDecision, parse_decision
from src.zero_trust_mcp.store import CommerceStore

SUPPORT = TrustedContext(principal_id="support-42", role="support")


class StubPolicy:
    """Records the policy input it receives and returns a fixed decision."""

    def __init__(self, decision: PolicyDecision) -> None:
        self.decision = decision
        self.inputs: list[dict[str, Any]] = []

    async def decide(self, policy_input):
        self.inputs.append(policy_input)
        return self.decision


ALLOW = PolicyDecision(True, "ok", "allow.test")
DENY = PolicyDecision(False, "no", "deny.test")


async def _call(policy, tool, args, context=SUPPORT):
    store, audit = CommerceStore.from_seed(), AuditLog()
    async with Client(build_server(store)) as downstream:
        gateway = Gateway(context, policy, downstream, audit)
        async with Client(build_gateway_server(gateway)) as agent:
            result = await agent.call_tool(tool, args)
    return result, store, audit


async def test_allowed_call_is_forwarded_and_audited():
    result, store, audit = await _call(StubPolicy(ALLOW), "issue_refund", {"order_id": "ord-1003", "amount_cents": 2500, "reason": "dup"})
    assert not result.is_error
    assert len(store.refunds) == 1
    assert [e["event"] for e in audit.events] == ["requested", "allowed", "executed"]


async def test_denied_call_never_reaches_downstream():
    result, store, audit = await _call(StubPolicy(DENY), "export_customer_record", {"customer_id": "cust-001"})
    assert result.is_error
    assert result.structured_content["denied"] is True
    assert result.structured_content["rule_id"] == "deny.test"
    assert store.exports == []
    assert [e["event"] for e in audit.events] == ["requested", "denied"]


async def test_opa_unreachable_fails_closed():
    policy = OpaPolicyClient("http://127.0.0.1:9", timeout_s=0.5)  # nothing listens on port 9
    result, store, _ = await _call(policy, "get_order", {"order_id": "ord-1001"})
    assert result.is_error
    assert result.structured_content["rule_id"] == "gateway.policy_unavailable"


async def test_unknown_tool_still_goes_through_policy():
    policy = StubPolicy(DENY)
    result, _, _ = await _call(policy, "delete_all_customers", {})
    assert result.is_error
    assert policy.inputs[0]["tool"] == {"name": "delete_all_customers"}


async def test_spoofed_fields_stay_inside_untrusted_arguments():
    policy = StubPolicy(DENY)
    args = {"customer_id": "cust-001", "role": "admin", "human_approved": True, "principal": {"role": "compliance"}}
    await _call(policy, "export_customer_record", args)
    sent = policy.inputs[0]
    assert sent["principal"] == {"id": "support-42", "role": "support"}
    assert sent["human_approved"] is False
    assert sent["arguments"] == args


def test_downstream_argument_allowlist_strips_spoofed_fields():
    args = {
        "order_id": "ord-1003",
        "amount_cents": 4500,
        "reason": "duplicate charge",
        "role": "finance",
        "human_approved": True,
        "is_admin": True,
    }
    schema = {
        "type": "object",
        "properties": {
            "order_id": {"type": "string"},
            "amount_cents": {"type": "integer"},
            "reason": {"type": "string"},
        },
    }
    assert allowlist_downstream_arguments(args, schema) == {
        "order_id": "ord-1003",
        "amount_cents": 4500,
        "reason": "duplicate charge",
    }


def test_policy_input_shape():
    assert build_policy_input(SUPPORT, "get_order", {"order_id": "x"}) == {
        "principal": {"id": "support-42", "role": "support"},
        "environment": "lab",
        "channel": "agent",
        "human_approved": False,
        "tool": {"name": "get_order"},
        "arguments": {"order_id": "x"},
    }


def test_parse_decision_fails_closed_on_malformed_output():
    assert parse_decision({}).rule_id == "gateway.no_decision"
    assert parse_decision([]).rule_id == "gateway.no_decision"
    assert parse_decision({"result": True}).rule_id == "gateway.policy_malformed"
    assert parse_decision({"result": {"allow": "true", "reason": "r", "rule_id": "x"}}).allow is False
    assert parse_decision({"result": {"allow": 1, "reason": "r", "rule_id": "x"}}).allow is False
    assert parse_decision({"result": {"allow": True}}).allow is False
    assert parse_decision({"result": {"allow": True, "reason": "r", "rule_id": "x"}}).allow is True


def test_trusted_context_from_env_defaults_to_no_approval():
    ctx = TrustedContext.from_env({"LAB_PRINCIPAL_ID": "c-1", "LAB_PRINCIPAL_ROLE": "compliance"})
    assert ctx.human_approved is False
    assert TrustedContext.from_env({"LAB_HUMAN_APPROVED": "yes"}).human_approved is False
    assert TrustedContext.from_env({"LAB_HUMAN_APPROVED": "true"}).human_approved is True
