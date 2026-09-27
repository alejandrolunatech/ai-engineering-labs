"""Zero-Trust MCP Gateway (Lab 02, Phase 4): the Policy Enforcement Point.

    agent --MCP--> [gateway: PEP] --HTTP--> OPA (PDP: policies/gateway.rego)
                          |
                          +--MCP (stdio child)--> synthetic commerce server

Trust model:
- TrustedContext (principal, role, environment, channel, human_approved) is
  fixed from gateway configuration at startup. No MCP request can change it.
- tool name and arguments come from the agent and are untrusted. They are
  passed to OPA as data under `tool` / `arguments`, never merged into the
  trusted fields.
- Every tools/call goes through `Gateway.call_tool`, including unknown tools.
  A call reaches the downstream server only after OPA returns allow == true.

Run (agent launches this over stdio; OPA must be running separately):
    opa run --server --addr 127.0.0.1:8181 policies/gateway.rego
    LAB_PRINCIPAL_ID=support-42 LAB_PRINCIPAL_ROLE=support \\
        python -m src.zero_trust_mcp.gateway
"""

from __future__ import annotations

import os
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import anyio
from mcp import Client, StdioServerParameters, types
from mcp.server import Server, ServerRequestContext
from mcp.server.stdio import stdio_server

from .audit import AuditLog, summarize_arguments
from .policy import OpaPolicyClient, PolicyClient, PolicyDecision

LAB_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class TrustedContext:
    """Authorization context established by the gateway, never by the model."""

    principal_id: str | None
    role: str | None
    environment: str = "lab"
    channel: str = "agent"
    # Stand-in for a real human-approval workflow. Only gateway config sets it.
    human_approved: bool = False

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> TrustedContext:
        env = dict(os.environ) if env is None else env
        return cls(
            principal_id=env.get("LAB_PRINCIPAL_ID"),
            role=env.get("LAB_PRINCIPAL_ROLE"),
            environment=env.get("LAB_ENVIRONMENT", "lab"),
            channel=env.get("LAB_CHANNEL", "agent"),
            human_approved=env.get("LAB_HUMAN_APPROVED", "").strip().lower() == "true",
        )


def build_policy_input(context: TrustedContext, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Trusted fields come only from `context`. Untrusted input is nested, never merged."""
    return {
        "principal": {"id": context.principal_id, "role": context.role},
        "environment": context.environment,
        "channel": context.channel,
        "human_approved": context.human_approved,
        "tool": {"name": tool_name},
        "arguments": arguments,
    }


def allowlist_downstream_arguments(arguments: dict[str, Any], input_schema: dict[str, Any]) -> dict[str, Any]:
    """Forward only arguments declared by the downstream MCP tool schema.

    The policy still receives the original untrusted arguments so spoofing
    attempts remain observable and cannot influence trusted context. After an
    allow decision, this function narrows what crosses the gateway boundary.
    """
    properties = input_schema.get("properties") if isinstance(input_schema, dict) else None
    if not isinstance(properties, dict):
        raise ValueError("downstream tool has no usable object input schema")
    return {key: value for key, value in arguments.items() if key in properties}


def denial_result(decision_id: str, decision: PolicyDecision) -> types.CallToolResult:
    # Only the policy's own reason and rule_id are returned; argument values are not echoed.
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=f"Denied by gateway policy: {decision.reason}")],
        structured_content={
            "denied": True,
            "decision_id": decision_id,
            "rule_id": decision.rule_id,
            "reason": decision.reason,
        },
        is_error=True,
    )


class Gateway:
    def __init__(self, context: TrustedContext, policy: PolicyClient, downstream: Client, audit: AuditLog) -> None:
        self.context = context
        self.policy = policy
        self.downstream = downstream
        self.audit = audit

    async def list_tools(self) -> types.ListToolsResult:
        # Discovery is not authorization: listing a tool grants nothing.
        return await self.downstream.list_tools()

    async def _downstream_arguments(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Resolve the downstream schema and strip undeclared model-supplied fields."""
        listed = await self.downstream.list_tools()
        downstream_tool = next((tool for tool in listed.tools if tool.name == tool_name), None)
        if downstream_tool is None:
            raise ValueError("authorized tool is not exposed by downstream server")
        return allowlist_downstream_arguments(arguments, downstream_tool.input_schema)

    async def call_tool(self, tool_name: str, arguments: dict[str, Any] | None) -> types.CallToolResult:
        decision_id = str(uuid.uuid4())
        started = time.perf_counter()
        args = arguments if isinstance(arguments, dict) else {}
        who = {
            "principal_id": self.context.principal_id,
            "role": self.context.role,
            "tool_name": tool_name[:64],
        }
        self.audit.record("requested", decision_id, **who, **summarize_arguments(args))

        try:
            decision = await self.policy.decide(build_policy_input(self.context, tool_name, args))
        except Exception:  # any PEP-side failure is a deny, never a pass-through
            decision = PolicyDecision(False, "policy evaluation failed; request denied", "gateway.policy_exception")

        verdict = {"rule_id": decision.rule_id, "reason": decision.reason}
        if decision.allow is not True:
            latency = round((time.perf_counter() - started) * 1000, 2)
            self.audit.record("denied", decision_id, **who, **verdict, downstream_executed=False, gateway_latency_ms=latency)
            return denial_result(decision_id, decision)

        self.audit.record("allowed", decision_id, **who, **verdict)
        try:
            # The policy evaluates the original request, including any spoofed
            # fields. Only schema-declared arguments cross the gateway after
            # authorization, preventing today's ignored extras from becoming
            # tomorrow's accidental authority-bearing parameters.
            downstream_args = await self._downstream_arguments(tool_name, args)
            result = await self.downstream.call_tool(tool_name, downstream_args)
        except Exception as exc:
            self.audit.record("downstream_failed", decision_id, **who, error_type=type(exc).__name__)
            return types.CallToolResult(
                content=[types.TextContent(type="text", text="Downstream call failed.")], is_error=True
            )

        latency = round((time.perf_counter() - started) * 1000, 2)
        # downstream_error=True means the tool ran but reported a business error
        # (e.g. unknown order), so no side effect is expected.
        self.audit.record(
            "executed",
            decision_id,
            **who,
            downstream_executed=True,
            downstream_error=bool(result.is_error),
            gateway_latency_ms=latency,
        )
        return result


def build_gateway_server(gateway: Gateway) -> Server:
    """Low-level server: one handler sees every tools/call before any routing or validation."""

    async def on_list_tools(ctx: ServerRequestContext, params: types.PaginatedRequestParams | None):
        return await gateway.list_tools()

    async def on_call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams):
        # params.meta and any other request fields are deliberately ignored.
        return await gateway.call_tool(params.name, params.arguments)

    return Server("zero-trust-mcp-gateway", on_list_tools=on_list_tools, on_call_tool=on_call_tool)


def downstream_stdio_params() -> StdioServerParameters:
    # Child process with the SDK's minimal inherited environment: the downstream
    # server does not receive LAB_* identity or OPA settings.
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "src.zero_trust_mcp.commerce_server"],
        cwd=str(LAB_ROOT),
    )


async def serve() -> None:
    context = TrustedContext.from_env()
    policy = OpaPolicyClient(os.environ.get("OPA_URL", "http://127.0.0.1:8181"))
    audit = AuditLog(Path(os.environ.get("GATEWAY_AUDIT_LOG", LAB_ROOT / "reports" / "gateway-audit.jsonl")))
    async with Client(downstream_stdio_params()) as downstream:
        server = build_gateway_server(Gateway(context, policy, downstream, audit))
        async with stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream, server.create_initialization_options())


def main() -> None:
    anyio.run(serve)


if __name__ == "__main__":
    main()
