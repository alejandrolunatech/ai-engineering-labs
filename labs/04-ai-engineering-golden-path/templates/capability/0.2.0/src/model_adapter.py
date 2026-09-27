"""Provider-neutral model adapter boundary.

The runtime depends only on the types in this module. A real provider adapter
(not part of this template version) would translate a ModelRequest into its
SDK call and return a ModelResponse containing plain text. Provider SDK objects
must never cross this boundary.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping, Protocol, Sequence


@dataclass(frozen=True)
class ModelRequest:
    capability: str
    profile: str
    instructions: str
    input: Mapping[str, Any]
    output_schema: Mapping[str, Any]
    max_output_tokens: int  # declared intent only; nothing measures usage yet


@dataclass(frozen=True)
class ModelInfo:
    """Adapter-reported metadata. Informational only; never used for authorization."""

    adapter: str
    model: str


@dataclass(frozen=True)
class ModelResponse:
    content: str  # raw text; the runtime parses and validates it
    model: ModelInfo


class ModelAdapter(Protocol):
    name: str

    async def generate(self, request: ModelRequest) -> ModelResponse: ...


HIGH_RISK_PATH_MARKERS = ("auth", "security", "migration", "payment")


def explain_change(change: Mapping[str, Any]) -> dict:
    """Deterministic stand-in for model reasoning.

    The risk rule is a toy heuristic for exercising the runtime. It is not a
    risk assessment.
    """
    files = list(change["files_changed"])
    if not files:
        risk_level = "unknown"
    elif any(marker in path.lower() for path in files for marker in HIGH_RISK_PATH_MARKERS):
        risk_level = "high"
    elif len(files) > 10:
        risk_level = "medium"
    else:
        risk_level = "low"
    return {
        "headline": f"{change['change_id']}: {change['title']}"[:120],
        "explanation": f"This change touches {len(files)} file(s). Summary: {change['summary']}"[:2000],
        "risk_level": risk_level,
        "open_questions": [] if files else ["Which files does this change touch?"],
    }


class FakeModelAdapter:
    """Deterministic, offline model adapter. No I/O, clock or randomness.

    Default mode returns explain_change(request.input) as JSON text.

    Scripted mode (for tests) returns the given items in order. Each item may be:
    a str (wrapped in a ModelResponse), an exception (raised), or any other
    object (returned as-is, to simulate a misbehaving adapter).
    Every call is recorded in `calls`.
    """

    name = "fake"
    model_label = "fake-deterministic-v1"

    def __init__(self, scripted: Sequence[Any] | None = None):
        self._scripted = list(scripted) if scripted is not None else None
        self.calls: list[ModelRequest] = []

    async def generate(self, request: ModelRequest) -> ModelResponse:
        self.calls.append(request)
        if self._scripted is None:
            return self._response(json.dumps(explain_change(request.input), sort_keys=True))
        if not self._scripted:
            raise RuntimeError("FakeModelAdapter script exhausted")
        item = self._scripted.pop(0)
        if isinstance(item, BaseException):
            raise item
        if isinstance(item, str):
            return self._response(item)
        return item

    def _response(self, content: str) -> ModelResponse:
        return ModelResponse(content=content, model=ModelInfo(adapter=self.name, model=self.model_label))
