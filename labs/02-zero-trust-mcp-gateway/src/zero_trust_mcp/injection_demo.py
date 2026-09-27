"""Phase 6: prompt-injection experiment (no LLM).

Shows the difference between what an untrusted caller REQUESTS and what the
downstream server EXECUTES:

    caller (attacker-controlled) --> gateway session --> Gateway (PEP) --> OPA (PDP)
                                                            |
                                                            +--> downstream MCP --> store

`InstructionFollowingCaller` stands in for a compromised or prompt-injected
agent. It is deterministic: it derives its requests from the ord-1004
customer_note text. It holds only the gateway MCP session. It never sees the
store, the downstream client, OPA, or the TrustedContext.

EXECUTED is measured from the store (the side-effect executor), not inferred
from the policy decision, and cross-checked against the audit trail.

Run:
    python -m src.zero_trust_mcp.injection_demo              # starts a temporary local OPA
    python -m src.zero_trust_mcp.injection_demo --opa-url http://127.0.0.1:8181
"""

from __future__ import annotations

import argparse
import contextlib
import json
import logging
import re
import shutil
import socket
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import anyio
import httpx
from mcp import Client

from .audit import AuditLog
from .commerce_server import build_server
from .gateway import Gateway, TrustedContext, build_gateway_server
from .policy import OpaPolicyClient, PolicyClient
from .store import CommerceStore

LAB_ROOT = Path(__file__).resolve().parents[2]
POLICY_FILE = LAB_ROOT / "policies" / "gateway.rego"
INJECTED_ORDER = "ord-1004"
SUPPORT = TrustedContext(principal_id="support-42", role="support")
NOTE_PREVIEW_CHARS = 110

# Which store ledger proves a side effect for each dangerous tool.
SIDE_EFFECT_LEDGER = {"export_customer_record": "exports", "issue_refund": "refunds"}


# --- Attacker-controlled side ---------------------------------------------------------


class InstructionFollowingCaller:
    """Simulated injected agent: obeys instructions found in data. Holds only the gateway session."""

    def __init__(self, gateway_session: Client) -> None:
        self._session = gateway_session

    async def read_order(self, order_id: str):
        return await self._session.call_tool("get_order", {"order_id": order_id})

    async def request(self, tool: str, arguments: dict[str, Any]):
        return await self._session.call_tool(tool, arguments)

    @staticmethod
    def plan_from_note(note: str) -> list[tuple[str, str, dict[str, Any]]]:
        """Turn the note's instructions into (label, tool, arguments). Deterministic, no model."""
        spoof: dict[str, Any] = {}
        if re.search(r"\badmin\b", note):
            spoof |= {"role": "admin", "is_admin": True}
        if re.search(r"human_approved\s*=\s*true", note):
            spoof["human_approved"] = True

        plan: list[tuple[str, str, dict[str, Any]]] = []
        if "export_customer_record" in note:
            for customer_id in dict.fromkeys(re.findall(r"\bcust-\d+\b", note)):
                plan.append((f"export_customer_record {customer_id}", "export_customer_record", {"customer_id": customer_id, **spoof}))
        refund = re.search(r"issue_refund for order_id (\S+) with amount_eur (\d+(?:\.\d+)?) and reason '([^']*)'", note)
        if refund:
            order_id, amount, reason = refund.group(1), float(refund.group(2)), refund.group(3)
            plan.append((f"issue_refund {order_id} €{amount:g}", "issue_refund", {"order_id": order_id, "amount_eur": amount, "reason": reason, **spoof}))
        return plan


# --- Trusted observer / report --------------------------------------------------------


@dataclass
class ActionRecord:
    label: str
    tool: str
    spoofed_keys: list[str]
    decision_id: str | None
    rule_id: str | None
    denied: bool
    executed_store: bool
    audit_events: list[str]

    @property
    def executed_audit(self) -> bool:
        return "executed" in self.audit_events

    @property
    def executed(self) -> bool:
        # Either source reporting execution counts; disagreement is surfaced separately.
        return self.executed_store or self.executed_audit


@dataclass
class DemoReport:
    note_preview: str
    read_rule_id: str | None
    actions: list[ActionRecord] = field(default_factory=list)
    exports: list[str] = field(default_factory=list)
    refunds: int = 0
    audit_leaks_free_text: bool = False

    @property
    def breaches(self) -> list[ActionRecord]:
        return [a for a in self.actions if a.executed]

    @property
    def inconsistencies(self) -> list[ActionRecord]:
        return [a for a in self.actions if a.executed_store != a.executed_audit]


def _preview(note: str) -> str:
    flat = " ".join(note.split())
    return flat if len(flat) <= NOTE_PREVIEW_CHARS else flat[:NOTE_PREVIEW_CHARS] + f"… [+{len(flat) - NOTE_PREVIEW_CHARS} chars omitted]"


async def run_demo(policy: PolicyClient, context: TrustedContext = SUPPORT) -> DemoReport:
    store, audit = CommerceStore.from_seed(), AuditLog()  # in memory only
    async with Client(build_server(store)) as downstream:
        gateway = Gateway(context, policy, downstream, audit)
        async with Client(build_gateway_server(gateway)) as session:
            caller = InstructionFollowingCaller(session)

            read = await caller.read_order(INJECTED_ORDER)
            if read.is_error:
                return DemoReport(note_preview="", read_rule_id=(read.structured_content or {}).get("rule_id"))
            note = read.structured_content["customer_note"]
            report = DemoReport(note_preview=_preview(note), read_rule_id=audit.events[1].get("rule_id"))

            for label, tool, args in caller.plan_from_note(note):
                ledger = getattr(store, SIDE_EFFECT_LEDGER[tool])
                before_ledger, before_events = len(ledger), len(audit.events)
                result = await caller.request(tool, args)
                new_events = audit.events[before_events:]
                sc = result.structured_content or {}
                report.actions.append(
                    ActionRecord(
                        label=label,
                        tool=tool,
                        spoofed_keys=sorted(k for k in args if k in {"role", "is_admin", "human_approved"}),
                        decision_id=new_events[0]["decision_id"] if new_events else None,
                        rule_id=next((e.get("rule_id") for e in new_events if "rule_id" in e), None),
                        denied=sc.get("denied") is True,
                        executed_store=len(ledger) > before_ledger,
                        audit_events=[e["event"] for e in new_events],
                    )
                )

    report.exports = list(store.exports)
    report.refunds = len(store.refunds)
    dumped = json.dumps(audit.events)
    report.audit_leaks_free_text = "SYSTEM OVERRIDE" in dumped or "approved by system" in dumped
    return report


def render(report: DemoReport, context: TrustedContext = SUPPORT) -> str:
    yn = lambda b: "yes" if b else "no"  # noqa: E731
    out = [
        f"Trusted principal: {context.principal_id} (role={context.role}, human_approved={context.human_approved})",
        f"Step 1  get_order({INJECTED_ORDER}) via gateway -> {report.read_rule_id}",
    ]
    if not report.note_preview:
        out.append("  get_order was not allowed; no note was read, so no injected plan exists.")
        return "\n".join(out)
    out += [
        "",
        "Step 2  customer_note  [UNTRUSTED DATA - displayed, never executed by the gateway]",
        f"  | {report.note_preview}",
        "",
        f"Step 3  Instruction-following caller derived {len(report.actions)} dangerous request(s) from that note",
        "        and sent every one through the gateway session (no downstream access).",
        "",
        f"{'ACTION':<34}{'REQUESTED':<11}{'POLICY':<8}{'RULE_ID':<35}{'DENIED':<8}EXECUTED",
    ]
    for a in report.actions:
        policy = "DENY" if a.denied else "ALLOW"
        out.append(f"{a.label:<34}{'yes':<11}{policy:<8}{(a.rule_id or '-'):<35}{yn(a.denied):<8}{yn(a.executed)}")
    spoofed = sorted({k for a in report.actions for k in a.spoofed_keys})
    if spoofed:
        out.append(f"  (every request also carried spoofed arguments: {', '.join(spoofed)})")

    out += ["", "Gateway audit sequence per decision (argument values: ids/amounts only, free text omitted)"]
    for a in report.actions:
        out.append(f"  {(a.decision_id or '?')[:8]}  {a.label:<34}{' -> '.join(a.audit_events)}")

    out += [
        "",
        "Downstream store verification (executor ground truth)",
        f"  customer exports executed: {len(report.exports)}   {report.exports}",
        f"  refunds executed:          {report.refunds}",
        f"  injected free text present in audit log: {yn(report.audit_leaks_free_text)}",
    ]
    for a in report.inconsistencies:
        out.append(f"  WARNING: store and audit disagree for {a.label}")

    requested = len(report.actions)
    out.append("")
    if report.breaches:
        out.append(f"AUTHORIZATION FAILURE: {len(report.breaches)} of {requested} prohibited request(s) EXECUTED downstream.")
    else:
        out += [
            f"Susceptibility: the caller followed the injected instruction ({requested} dangerous request(s) attempted).",
            f"Enforcement:    {sum(a.denied for a in report.actions)} denied by policy.",
            "The caller followed the injected instruction, but zero prohibited downstream side effects executed.",
        ]
    return "\n".join(out)


# --- Temporary local OPA (demo convenience) ---------------------------------------------


@contextlib.contextmanager
def temporary_opa(policy_file: Path = POLICY_FILE):
    opa = shutil.which("opa")
    if opa is None:
        raise RuntimeError("`opa` binary not found; install OPA or pass --opa-url")
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    url = f"http://127.0.0.1:{port}"
    proc = subprocess.Popen(
        [opa, "run", "--server", "--addr", f"127.0.0.1:{port}", "--log-level", "error", str(policy_file)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 10
        while True:
            with contextlib.suppress(httpx.HTTPError):
                if httpx.get(f"{url}/health", timeout=0.5).status_code == 200:
                    break
            if proc.poll() is not None or time.monotonic() > deadline:
                raise RuntimeError("temporary OPA failed to start")
            time.sleep(0.05)
        yield url
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Lab 02 Phase 6 prompt-injection demo (no LLM)")
    parser.add_argument("--opa-url", help="use an already-running OPA instead of starting a temporary one")
    args = parser.parse_args(argv)
    # Keep the demo output readable; library request logs add nothing here.
    for name in ("httpx", "mcp"):
        logging.getLogger(name).setLevel(logging.WARNING)

    with contextlib.ExitStack() as stack:
        opa_url = args.opa_url or stack.enter_context(temporary_opa())
        print(f"Policy decision point: OPA at {opa_url} ({POLICY_FILE.relative_to(LAB_ROOT)})\n")
        report = anyio.run(run_demo, OpaPolicyClient(opa_url))
    print(render(report))
    if not report.note_preview:
        return 2
    return 1 if report.breaches or report.inconsistencies else 0


if __name__ == "__main__":
    sys.exit(main())
