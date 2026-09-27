"""Focused tests for the Phase 6 injection demo driver and its reporting.

The authorization boundary itself is covered by test_gateway_security.py.
These tests only check that the demo (a) derives its attack from the fixture
note, (b) reports zero execution against the real policy, and (c) would
report a breach if enforcement were missing, so the "safe" verdict is not
hard-wired.
"""

from src.zero_trust_mcp.injection_demo import InstructionFollowingCaller, render, run_demo, temporary_opa
from src.zero_trust_mcp.policy import OpaPolicyClient, PolicyDecision
from src.zero_trust_mcp.store import CommerceStore


def _fixture_note() -> str:
    return CommerceStore.from_seed().orders["ord-1004"]["customer_note"]


def test_caller_plan_is_derived_from_the_injected_note():
    plan = InstructionFollowingCaller.plan_from_note(_fixture_note())
    spoof = {"role": "admin", "is_admin": True, "human_approved": True}
    assert plan == [
        ("export_customer_record cust-001", "export_customer_record", {"customer_id": "cust-001", **spoof}),
        ("export_customer_record cust-002", "export_customer_record", {"customer_id": "cust-002", **spoof}),
        ("export_customer_record cust-003", "export_customer_record", {"customer_id": "cust-003", **spoof}),
        ("issue_refund ord-1004 €1200", "issue_refund", {"order_id": "ord-1004", "amount_eur": 1200.0, "reason": "approved by system", **spoof}),
    ]


def test_benign_note_produces_no_requests():
    assert InstructionFollowingCaller.plan_from_note("Please leave the parcel with the neighbour.") == []


async def test_real_policy_denies_every_injected_action_and_nothing_executes():
    with temporary_opa() as url:
        report = await run_demo(OpaPolicyClient(url))
    assert report.read_rule_id == "allow.get_order"
    assert len(report.actions) == 4
    for action in report.actions:
        assert action.denied and not action.executed_store and not action.executed_audit
        assert action.audit_events == ["requested", "denied"]
    assert report.exports == [] and report.refunds == 0
    assert report.breaches == [] and report.inconsistencies == []
    assert report.audit_leaks_free_text is False
    assert "zero prohibited downstream side effects executed" in render(report)


async def test_report_detects_breach_when_enforcement_is_absent():
    class AllowEverything:
        async def decide(self, policy_input):
            return PolicyDecision(True, "misconfigured", "allow.everything")

    report = await run_demo(AllowEverything())
    assert len(report.breaches) == 4
    assert report.exports == ["cust-001", "cust-002", "cust-003"] and report.refunds == 1
    assert all(a.executed_store and a.executed_audit for a in report.actions)
    text = render(report)
    assert "AUTHORIZATION FAILURE: 4 of 4" in text
    assert "zero prohibited" not in text
