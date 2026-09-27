"""OPA client for the gateway (PEP side of the PEP/PDP split).

The gateway does not make authorization decisions. It asks OPA and enforces
the answer. This module's only job is to turn *anything* other than a
well-formed OPA "allow" into a deny: network errors, timeouts, non-200
responses, invalid JSON, a missing result, or a result with the wrong shape.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import httpx

DECISION_PATH = "/v1/data/gateway/decision"
DEFAULT_POLICY_FILE = Path(__file__).resolve().parents[2] / "policies" / "gateway.rego"


@dataclass(frozen=True)
class PolicyMetadata:
    """Provenance of the policy artifact this gateway is configured against.

    `sha256` is computed once from the exact bytes of the policy file and then
    reused for every audit event of the Gateway instance holding it.

    LIMITATION: this identifies the artifact the gateway *expects*. It is not
    proof that the OPA instance answering decisions loaded those bytes; OPA is
    a separate process queried over HTTP and nothing here attests its state.
    """

    artifact: str
    sha256: str

    @classmethod
    def from_file(cls, path: Path = DEFAULT_POLICY_FILE) -> PolicyMetadata:
        digest = hashlib.sha256(Path(path).read_bytes()).hexdigest()
        return cls(artifact=Path(path).name, sha256=digest)


@dataclass(frozen=True)
class PolicyDecision:
    allow: bool
    reason: str
    rule_id: str


def _fail_closed(rule_id: str, reason: str) -> PolicyDecision:
    return PolicyDecision(allow=False, reason=reason, rule_id=rule_id)


class PolicyClient(Protocol):
    async def decide(self, policy_input: dict[str, Any]) -> PolicyDecision: ...


class OpaPolicyClient:
    def __init__(self, opa_url: str, timeout_s: float = 2.0) -> None:
        self._url = opa_url.rstrip("/") + DECISION_PATH
        self._timeout_s = timeout_s

    async def decide(self, policy_input: dict[str, Any]) -> PolicyDecision:
        try:
            async with httpx.AsyncClient(timeout=self._timeout_s) as http:
                response = await http.post(self._url, json={"input": policy_input})
        except httpx.TimeoutException:
            return _fail_closed("gateway.policy_timeout", "policy decision timed out; request denied")
        except httpx.HTTPError:
            return _fail_closed("gateway.policy_unavailable", "policy decision unavailable; request denied")

        if response.status_code != 200:
            return _fail_closed("gateway.policy_error", "policy engine returned an error; request denied")
        try:
            body = response.json()
        except ValueError:
            return _fail_closed("gateway.policy_malformed", "policy response was not valid JSON; request denied")
        return parse_decision(body)


def parse_decision(body: Any) -> PolicyDecision:
    """Strictly validate OPA's `{"result": {...}}` envelope. Anything unexpected denies."""
    if not isinstance(body, dict) or "result" not in body:
        # OPA omits `result` when the rule is undefined (e.g. policy not loaded).
        return _fail_closed("gateway.no_decision", "no policy decision was returned; request denied")
    result = body["result"]
    if not isinstance(result, dict):
        return _fail_closed("gateway.policy_malformed", "policy decision was malformed; request denied")

    allow, reason, rule_id = result.get("allow"), result.get("reason"), result.get("rule_id")
    # `allow` must be the JSON boolean true: "true", 1, or a missing field all deny.
    if not isinstance(allow, bool) or not isinstance(reason, str) or not isinstance(rule_id, str):
        return _fail_closed("gateway.policy_malformed", "policy decision was malformed; request denied")
    return PolicyDecision(allow=allow, reason=reason, rule_id=rule_id)
