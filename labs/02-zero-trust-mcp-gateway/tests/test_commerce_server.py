"""Deterministic tests for the commerce MCP server over the real MCP protocol.

Uses the SDK's in-process transport (`Client(server)`): no network, no LLM.
These tests prove the downstream tools work, and also pin down the fact that
the server itself performs no authorization.
"""

import pytest
from mcp import Client

from src.zero_trust_mcp.commerce_server import TOOL_NAMES, build_server
from src.zero_trust_mcp.store import CommerceStore


@pytest.fixture
def store() -> CommerceStore:
    return CommerceStore.from_seed()


def connect(store: CommerceStore) -> Client:
    # Opened inside each test (not an async fixture) so anyio's cancel scope is
    # entered and exited in the same task.
    return Client(build_server(store))


async def test_exposes_exactly_the_four_tools(store):
    async with connect(store) as client:
        tools = (await client.list_tools()).tools
        assert sorted(t.name for t in tools) == sorted(TOOL_NAMES)


async def test_tool_schemas_have_no_identity_or_approval_parameters(store):
    async with connect(store) as client:
        expected = {
            "get_order": {"order_id"},
            "search_customer": {"query"},
            "issue_refund": {"order_id", "amount_eur", "reason"},
            "export_customer_record": {"customer_id"},
        }
        for tool in (await client.list_tools()).tools:
            assert set(tool.input_schema["properties"]) == expected[tool.name]


async def test_get_order(store):
    async with connect(store) as client:
        result = await client.call_tool("get_order", {"order_id": "ord-1002"})
        assert not result.is_error
        assert result.structured_content["total_eur"] == 649.0


async def test_get_order_returns_injection_text_as_plain_data(store):
    async with connect(store) as client:
        result = await client.call_tool("get_order", {"order_id": "ord-1004"})
        assert not result.is_error
        assert "SYSTEM OVERRIDE" in result.structured_content["customer_note"]
        assert store.refunds == [] and store.exports == []


async def test_search_customer(store):
    async with connect(store) as client:
        result = await client.call_tool("search_customer", {"query": "cleo"})
        assert not result.is_error
        assert result.structured_content["result"] == [
            {"customer_id": "cust-003", "full_name": "Cleo Syntheticova", "email": "cleo.s@example.test"}
        ]


async def test_issue_refund_executes_side_effect(store):
    async with connect(store) as client:
        result = await client.call_tool(
            "issue_refund", {"order_id": "ord-1003", "amount_eur": 45, "reason": "duplicate charge"}
        )
        assert not result.is_error
        assert result.structured_content["refund_id"] == "rf-0001"
        assert store.refunds[0]["amount_eur"] == 45


async def test_issue_refund_business_error_is_tool_error_not_crash(store):
    async with connect(store) as client:
        result = await client.call_tool("issue_refund", {"order_id": "ord-1001", "amount_eur": 500, "reason": "x"})
        assert result.is_error
        assert "exceeds refundable balance" in result.content[0].text
        assert store.refunds == []


async def test_export_customer_record_returns_pii(store):
    async with connect(store) as client:
        result = await client.call_tool("export_customer_record", {"customer_id": "cust-002"})
        assert not result.is_error
        assert result.structured_content["payment_iban"] == "XX00 LABS 0000 0000 0000 02"
        assert store.exports == ["cust-002"]


async def test_unknown_tool_is_error(store):
    async with connect(store) as client:
        result = await client.call_tool("delete_all_customers", {})
        assert result.is_error


async def test_invalid_argument_type_is_rejected_by_schema(store):
    async with connect(store) as client:
        result = await client.call_tool(
            "issue_refund", {"order_id": "ord-1003", "amount_eur": "lots", "reason": "x"}
        )
        assert result.is_error
        assert store.refunds == []


# --- Why this server is unsafe to expose directly ---------------------------


async def test_UNSAFE_injected_actions_execute_without_any_authorization(store):
    """Exactly what the ord-1004 note asks for succeeds when called directly.

    Nothing here checks who is asking. If an agent follows the injected text,
    the full-value refund and the bulk PII export all execute.
    """
    async with connect(store) as client:
        for cid in ("cust-001", "cust-002", "cust-003"):
            assert not (await client.call_tool("export_customer_record", {"customer_id": cid})).is_error
        refund = await client.call_tool(
            "issue_refund", {"order_id": "ord-1004", "amount_eur": 1200, "reason": "approved by system"}
        )
        assert not refund.is_error
        assert store.exports == ["cust-001", "cust-002", "cust-003"]
        assert store.refunds[0]["amount_eur"] == 1200


async def test_UNSAFE_spoofed_role_and_approval_are_silently_ignored_not_rejected(store):
    """Extra fields are dropped by the server, so a spoofing attempt still succeeds.

    The server neither honours nor detects `role`/`human_approved`: they have
    no effect because the server has no authorization concept at all.
    """
    async with connect(store) as client:
        result = await client.call_tool(
            "issue_refund",
            {"order_id": "ord-1002", "amount_eur": 649, "reason": "", "role": "admin", "human_approved": True},
        )
        assert not result.is_error
        assert store.refunds[0]["amount_eur"] == 649
