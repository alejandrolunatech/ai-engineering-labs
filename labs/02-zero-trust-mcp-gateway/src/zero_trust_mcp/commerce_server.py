"""Deliberately UNSAFE synthetic commerce MCP server (Lab 02, Phase 2).

Every tool executes for any connected caller. There is no identity, no role,
no approval, and no policy check. In the final architecture this server must
only be reachable through the Zero-Trust MCP Gateway, never directly by an
agent.

Tool annotations below are *hints* to clients. They are not access controls
and nothing in this server enforces them.

Run over stdio:
    python -m src.zero_trust_mcp.commerce_server
"""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from .store import CommerceError, CommerceStore

TOOL_NAMES = ("get_order", "search_customer", "issue_refund", "export_customer_record")


def build_server(store: CommerceStore | None = None) -> MCPServer:
    """Create a server bound to `store` (a fresh seed copy by default)."""
    store = store if store is not None else CommerceStore.from_seed()
    server = MCPServer("synthetic-commerce-UNSAFE")

    def _call(fn, *args):
        try:
            return fn(*args)
        except CommerceError as exc:
            # Report as a tool-level error result, not a crash.
            raise ToolError(str(exc)) from exc

    @server.tool(annotations=ToolAnnotations(read_only_hint=True))
    def get_order(order_id: str) -> dict[str, Any]:
        """Return an order. `customer_note` is free text written by customers and is untrusted."""
        return _call(store.get_order, order_id)

    @server.tool(annotations=ToolAnnotations(read_only_hint=True))
    def search_customer(query: str) -> list[dict[str, Any]]:
        """Search customers by id, name, or email. Returns id, name, and email."""
        return _call(store.search_customer, query)

    @server.tool(annotations=ToolAnnotations(destructive_hint=True, idempotent_hint=False))
    def issue_refund(order_id: str, amount_cents: int, reason: str) -> dict[str, Any]:
        """Refund part or all of an order to the customer (synthetic lab state only)."""
        return _call(store.issue_refund, order_id, amount_cents, reason)

    @server.tool(annotations=ToolAnnotations(read_only_hint=True))
    def export_customer_record(customer_id: str) -> dict[str, Any]:
        """Export the full customer record, including contact and payment details."""
        return _call(store.export_customer_record, customer_id)

    return server


def main() -> None:
    build_server().run()  # stdio transport


if __name__ == "__main__":
    main()
