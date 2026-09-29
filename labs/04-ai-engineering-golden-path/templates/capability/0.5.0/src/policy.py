"""Tool authorization policy: the DECISION side of the tool boundary.

The runtime (src/capability.py) ENFORCES decisions; this module only makes
them. A policy is supplied by trusted code (`run(..., policy=...)`), never by
model output, and the command line always uses DefaultPolicy.

What a policy knows (PolicyContext) comes only from trusted runtime state:
the validated manifest and the trusted tool registry. It deliberately has NO
caller identity, role or approval state: this lab has no trusted identity, so
the contract does not pretend to have one. The correlation id is excluded
because it is a caller-supplied label, not authority.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol


@dataclass(frozen=True)
class PolicyContext:
    capability: str
    capability_version: str
    template_version: str
    data_sensitivity: str  # declared label from capability.yaml
    tool_name: str  # from the trusted registry
    tool_impact: str  # from the trusted registry: "low" | "high"


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    reason_code: str  # stable slug, e.g. "low_impact_default"


class PolicyHook(Protocol):
    async def authorize(self, context: PolicyContext, arguments: Mapping[str, Any]) -> PolicyDecision:
        """`arguments` were already validated against the tool's schema.

        A business policy may inspect them; they are never recorded in telemetry.
        """
        ...


class DefaultPolicy:
    """Low-impact declared tools are allowed; high-impact tools are denied.

    A high-impact tool runs only when trusted code injects a policy that
    explicitly allows it. There is intentionally no command-line override.
    """

    async def authorize(self, context: PolicyContext, arguments: Mapping[str, Any]) -> PolicyDecision:
        if context.tool_impact == "low":
            return PolicyDecision(allowed=True, reason_code="low_impact_default")
        return PolicyDecision(allowed=False, reason_code="high_impact_requires_policy")
