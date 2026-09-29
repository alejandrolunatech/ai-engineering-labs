"""Trusted tool registry, synthetic tools, and deterministic tool preflight.

Concepts kept separate:
  REGISTERED  a trusted implementation exists in TOOL_REGISTRY (this file)
  DECLARED    capability.yaml authority.tools allows the capability to use it
  EXPOSED     declared AND registered tools described to the model
  PROPOSED    the model asked for it (a ModelResponse.tool_requests entry)
  AUTHORIZED  every runtime gate passed AND the policy allowed it
  EXECUTED    the executor actually ran

  registered != declared;  declared != authorized;  authorized != executed.
The model is only ever the source of proposals.

Both tools are SYNTHETIC: they only touch an in-memory SyntheticLedger. There
is no filesystem, network or external system, and nothing is really published.
Tool results are not fed back to the model: this template proves the
authority/execution boundary, not an agent tool-use loop.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Mapping

from contracts import ToolRequestRejected, schema_failed_rules
from model_adapter import ToolRequest, ToolSpec

# Phase-6 runtime ceiling, NOT a manifest budget and NOT a universal
# recommendation. One proposal per response avoids partial multi-tool
# execution, ordering, rollback and transaction semantics entirely. A future
# capability contract version may add budgets.max_tool_requests.
MAX_TOOL_REQUESTS_PER_RESPONSE = 1


@dataclass
class SyntheticLedger:
    """In-memory stand-in for external state. Tests read it directly."""

    lookups: list[str] = field(default_factory=list)
    notices: list[dict] = field(default_factory=list)
    fail_writes: bool = False  # makes publish_change_notice fail, for tests


class SyntheticToolError(Exception):
    pass


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    impact: str  # "low" | "high": trusted classification, never from the model
    description: str
    arguments_schema: dict
    execute: Callable[[Mapping[str, Any], SyntheticLedger], Awaitable[dict]]

    def spec(self) -> ToolSpec:
        """Model-visible metadata only: no executor, no impact."""
        return ToolSpec(name=self.name, description=self.description, arguments_schema=self.arguments_schema)


_CHANGE_ID = {"type": "string", "pattern": "^CHG-[0-9]{1,8}$"}


async def _lookup_change_context(arguments: Mapping[str, Any], ledger: SyntheticLedger) -> dict:
    ledger.lookups.append(arguments["change_id"])
    return {"change_id": arguments["change_id"], "related_changes": 0}  # synthetic; not fed back


async def _publish_change_notice(arguments: Mapping[str, Any], ledger: SyntheticLedger) -> dict:
    if ledger.fail_writes:
        raise SyntheticToolError("synthetic write failure")
    ledger.notices.append(dict(arguments))
    return {"published": True}  # synthetic; nothing is really published


LOOKUP_CHANGE_CONTEXT = ToolDefinition(
    name="lookup_change_context",
    impact="low",
    description="Read synthetic context about a change (read-like, synthetic).",
    arguments_schema={
        "type": "object",
        "additionalProperties": False,
        "required": ["change_id"],
        "properties": {"change_id": _CHANGE_ID},
    },
    execute=_lookup_change_context,
)

PUBLISH_CHANGE_NOTICE = ToolDefinition(
    name="publish_change_notice",
    impact="high",
    description="Publish a notice about a change to an audience (write-like, synthetic).",
    arguments_schema={
        "type": "object",
        "additionalProperties": False,
        "required": ["change_id", "audience", "risk_level"],
        "properties": {
            "change_id": _CHANGE_ID,
            "audience": {"enum": ["engineering", "stakeholders"]},
            "risk_level": {"enum": ["low", "medium", "high", "unknown"]},
        },
    },
    execute=_publish_change_notice,
)

# Explicit, closed registry. No dynamic imports, no plugin discovery.
TOOL_REGISTRY: dict[str, ToolDefinition] = {
    tool.name: tool for tool in (LOOKUP_CHANGE_CONTEXT, PUBLISH_CHANGE_NOTICE)
}


@dataclass
class ToolProposal:
    """Runtime-side lifecycle state of ONE proposal. Never holds model claims
    about authority; `definition` and `impact` come from the trusted registry."""

    attempt: int
    index: int
    name: str  # a registered name, or "unrecognized" (arbitrary text is never kept)
    declared: bool
    registered: bool
    definition: ToolDefinition | None
    arguments: dict | None
    preflight_status: str = "passed"
    rejection_reason: str | None = None
    failed_rules: tuple[str, ...] = ()
    authorization_status: str = "not_evaluated"
    policy_reason_code: str | None = None
    execution_status: str = "not_attempted"
    outcome: str | None = None
    error_type: str | None = None

    def reject(self, reason: str, failed_rules: tuple[str, ...] = ()) -> None:
        self.preflight_status, self.rejection_reason, self.failed_rules = "rejected", reason, failed_rules
        self.outcome = "rejected"

    def attributes(self) -> dict:
        attributes = {
            "model_request.attempt": self.attempt,
            "tool.index": self.index,
            "tool.name": self.name,
            "tool.declared": self.declared,
            "tool.registered": self.registered,
            "tool.impact": self.definition.impact if self.definition else None,
            "tool.proposed": True,
            "tool.preflight_status": self.preflight_status,
            "tool.rejection_reason": self.rejection_reason,
            "tool.authorization_status": self.authorization_status,
            "tool.policy.reason_code": self.policy_reason_code,
            "tool.execution_status": self.execution_status,
            "tool.outcome": self.outcome,
        }
        if self.failed_rules:
            attributes["tool.arguments.failed_rules"] = list(self.failed_rules)
        if self.error_type:
            attributes["error.type"] = self.error_type
        return attributes


def preflight(
    tool_requests: Any,
    declared: tuple[str, ...],
    registry: Mapping[str, ToolDefinition],
    attempt: int,
    model_requests_used: int,
) -> list[ToolProposal]:
    """Deterministic checks that need no policy and cause no side effects.

    Raises ToolRequestRejected for a malformed or oversized proposal
    container. Individual proposals are returned with their preflight status;
    the caller fails closed if any was rejected.
    """
    if not isinstance(tool_requests, (tuple, list)):
        raise ToolRequestRejected(
            "tool_requests is not a sequence", reason="malformed_request", model_requests_used=model_requests_used
        )
    if len(tool_requests) > MAX_TOOL_REQUESTS_PER_RESPONSE:
        raise ToolRequestRejected(
            f"{len(tool_requests)} tool requests exceed the per-response ceiling of {MAX_TOOL_REQUESTS_PER_RESPONSE}",
            reason="tool_request_limit",
            model_requests_used=model_requests_used,
        )

    proposals = []
    for index, request in enumerate(tool_requests):
        name = request.name if isinstance(request, ToolRequest) else None
        registered = isinstance(name, str) and name in registry
        proposal = ToolProposal(
            attempt=attempt,
            index=index,
            name=name if registered else "unrecognized",
            declared=isinstance(name, str) and name in declared,
            registered=registered,
            definition=registry[name] if registered else None,
            arguments=None,
        )
        if not isinstance(request, ToolRequest) or not isinstance(name, str) or not isinstance(
            request.arguments, Mapping
        ):
            proposal.reject("malformed_request")
        elif not proposal.declared:
            proposal.reject("undeclared")
        elif not proposal.registered:
            proposal.reject("unregistered")  # defense in depth: also checked at load
        else:
            arguments = dict(request.arguments)
            failed = schema_failed_rules(proposal.definition.arguments_schema, arguments)
            if failed:
                proposal.reject("invalid_arguments", failed)
            else:
                proposal.arguments = arguments
        proposals.append(proposal)
    return proposals


class ExecutionGuard:
    """Per-run defense in depth: the same tool + arguments never executes twice.

    The normal control flow already prevents this (execution happens only for
    the accepted response, and the run returns immediately afterwards).
    """

    def __init__(self) -> None:
        self._executed: set[str] = set()

    def claim(self, name: str, arguments: Mapping[str, Any]) -> None:
        key = name + ":" + json.dumps(arguments, sort_keys=True, separators=(",", ":"))
        if key in self._executed:
            raise RuntimeError("duplicate tool execution blocked by ExecutionGuard")
        self._executed.add(key)
