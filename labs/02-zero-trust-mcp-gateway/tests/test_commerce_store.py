"""Deterministic tests for the synthetic commerce state (no MCP, no LLM)."""

import pytest

from src.zero_trust_mcp.store import SEED_PATH, CommerceError, CommerceStore


@pytest.fixture
def store() -> CommerceStore:
    return CommerceStore.from_seed()


def test_get_order_returns_order_with_refund_total(store):
    order = store.get_order("ord-1001")
    assert order["customer_id"] == "cust-001"
    assert order["total_eur"] == 39.9
    assert order["refunded_cents"] == 0


def test_get_order_unknown_raises(store):
    with pytest.raises(CommerceError, match="unknown order_id"):
        store.get_order("ord-9999")


def test_injection_order_is_returned_verbatim_and_causes_no_side_effects(store):
    order = store.get_order("ord-1004")
    assert "SYSTEM OVERRIDE" in order["customer_note"]
    assert "export_customer_record" in order["customer_note"]
    # Reading malicious text is not executing it.
    assert store.refunds == []
    assert store.exports == []


def test_search_customer_matches_name_email_and_id(store):
    assert [c["customer_id"] for c in store.search_customer("testwell")] == ["cust-001"]
    assert [c["customer_id"] for c in store.search_customer("BRAM.PLACEHOLDER@")] == ["cust-002"]
    assert [c["customer_id"] for c in store.search_customer("cust-003")] == ["cust-003"]
    assert len(store.search_customer("example.test")) == 3


def test_search_customer_returns_summary_fields_only(store):
    (hit,) = store.search_customer("ada")
    assert set(hit) == {"customer_id", "full_name", "email"}


def test_search_customer_blank_or_no_match_returns_empty(store):
    assert store.search_customer("   ") == []
    assert store.search_customer("nobody") == []


def test_issue_refund_mutates_in_memory_state(store):
    result = store.issue_refund("ord-1003", 4500, "duplicate charge")
    assert result["refund_id"] == "rf-0001"
    assert result["amount_cents"] == 4500
    assert result["refundable_remaining_cents"] == 4500
    assert store.get_order("ord-1003")["refunded_cents"] == 4500
    assert len(store.refunds) == 1


def test_issue_refund_allows_exact_remaining_balance_then_blocks(store):
    store.issue_refund("ord-1001", 1995, "one mug broken")
    store.issue_refund("ord-1001", 1995, "second mug broken")
    with pytest.raises(CommerceError, match="exceeds refundable balance"):
        store.issue_refund("ord-1001", 1, "more")


def test_issue_refund_over_total_raises_and_records_nothing(store):
    with pytest.raises(CommerceError, match="exceeds refundable balance"):
        store.issue_refund("ord-1001", 4000, "too much")
    assert store.refunds == []


@pytest.mark.parametrize("amount", [0, -5, 1.5, float("nan"), True])
def test_issue_refund_rejects_non_positive_amounts(store, amount):
    with pytest.raises(CommerceError, match="positive integer"):
        store.issue_refund("ord-1001", amount, "bad amount")
    assert store.refunds == []


def test_issue_refund_unknown_order_raises(store):
    with pytest.raises(CommerceError, match="unknown order_id"):
        store.issue_refund("ord-9999", 1000, "x")


def test_issue_refund_accepts_empty_reason_because_server_has_no_policy(store):
    # Documents the gap the gateway must close: downstream does not require a reason.
    store.issue_refund("ord-1003", 500, "")
    assert store.refunds[0]["reason"] == ""


def test_export_customer_record_returns_pii_and_records_egress(store):
    record = store.export_customer_record("cust-001")
    assert record["email"] == "ada.testwell@example.test"
    assert record["payment_iban"].startswith("XX00 LABS")
    assert record["date_of_birth"] == "1985-04-12"
    assert sorted(record["orders"]) == ["ord-1001", "ord-1003"]
    assert store.exports == ["cust-001"]


def test_export_unknown_customer_raises_and_records_nothing(store):
    with pytest.raises(CommerceError, match="unknown customer_id"):
        store.export_customer_record("cust-999")
    assert store.exports == []


def test_stores_are_independent_and_seed_file_is_not_written(store):
    before = SEED_PATH.read_bytes()
    store.issue_refund("ord-1003", 1000, "partial")
    store.customers["cust-001"]["email"] = "mutated@example.test"
    fresh = CommerceStore.from_seed()
    assert fresh.refunds == []
    assert fresh.customers["cust-001"]["email"] == "ada.testwell@example.test"
    assert SEED_PATH.read_bytes() == before


def test_seed_contains_only_synthetic_markers():
    fresh = CommerceStore.from_seed()
    for c in fresh.customers.values():
        assert c["email"].endswith("@example.test")
        assert c["payment_iban"].startswith("XX00 LABS")
