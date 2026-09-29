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
class ToolSpec:
    """What the model may SEE about a tool: model-usable metadata only.

    Never the executor, the trusted impact classification, or policy details.
    Seeing a tool is not authorization.
    """

    name: str
    description: str
    arguments_schema: Mapping[str, Any]


@dataclass(frozen=True)
class ToolRequest:
    """A model PROPOSAL to call a tool. It carries no authority.

    There are deliberately no authorized/approved/role/impact/permissions
    fields. Anything smuggled into `arguments` is checked against the trusted
    tool's closed argument schema, and authority never comes from arguments.
    """

    name: str
    arguments: Mapping[str, Any]


@dataclass(frozen=True)
class ModelRequest:
    capability: str
    profile: str
    instructions: str
    input: Mapping[str, Any]
    output_schema: Mapping[str, Any]
    max_output_tokens: int  # declared intent only; nothing measures usage yet
    tools: tuple[ToolSpec, ...] = ()  # declared AND registered tools only


@dataclass(frozen=True)
class ModelInfo:
    """Adapter-reported metadata. Informational only; never used for authorization."""

    adapter: str
    model: str


@dataclass(frozen=True)
class Usage:
    """Provider-neutral, adapter-reported token usage.

    None means UNKNOWN. Unknown is never the same as 0. A real adapter copies
    provider-reported counts into plain integers here; provider SDK usage
    objects must never cross this boundary.
    """

    input_tokens: int | None = None
    output_tokens: int | None = None


@dataclass(frozen=True)
class ModelResponse:
    content: str  # raw text; the runtime parses and validates it
    model: ModelInfo
    usage: Usage = Usage()  # adapter-reported; defaults to unknown
    tool_requests: tuple[ToolRequest, ...] = ()  # proposals only; default = none


class ModelAdapter(Protocol):
    name: str

    async def generate(self, request: ModelRequest) -> ModelResponse: ...


HIGH_RISK_PATH_MARKERS = ("auth", "security", "migration", "payment")

# Capability behavior (template 0.3.0): a summary this short is treated as too
# vague to support a confident risk claim, so the explanation asks for intent.
VAGUE_SUMMARY_MAX_WORDS = 4


def explain_change(change: Mapping[str, Any]) -> dict:
    """Deterministic stand-in for model reasoning.

    The risk rules are toy heuristics for exercising the runtime. They are not
    a risk assessment. Known false positive: the substring rule treats any path
    containing "auth" (for example AUTHORS.md) as high risk.

    Rules, in order:
      no files listed                 -> unknown
      path contains a high-risk marker -> high
      summary of 4 words or fewer     -> unknown (too vague for a confident claim)
      more than 10 files              -> medium
      otherwise                       -> low
    """
    files = list(change["files_changed"])
    vague = len(change["summary"].split()) <= VAGUE_SUMMARY_MAX_WORDS
    if not files:
        risk_level = "unknown"
    elif any(marker in path.lower() for path in files for marker in HIGH_RISK_PATH_MARKERS):
        risk_level = "high"
    elif vague:
        risk_level = "unknown"
    elif len(files) > 10:
        risk_level = "medium"
    else:
        risk_level = "low"
    open_questions = []
    if not files:
        open_questions.append("Which files does this change touch?")
    if vague:
        open_questions.append("What behavior is this change meant to alter?")
    return {
        "headline": f"{change['change_id']}: {change['title']}"[:120],
        "explanation": f"This change touches {len(files)} file(s). Summary: {change['summary']}"[:2000],
        "risk_level": risk_level,
        "open_questions": open_questions,
    }


class FakeModelAdapter:
    """Deterministic, offline model adapter. No I/O, clock or randomness.

    Default mode returns explain_change(request.input) as JSON text and
    proposes no tools. Scripted mode can return ModelResponse objects with
    tool_requests, to exercise the tool authority boundary.

    Usage defaults to UNKNOWN (Usage()): the fake does not tokenize anything,
    so it must not invent token counts. Tests may pass `usage=` explicitly.

    Scripted mode (for tests) returns the given items in order. Each item may be:
    a str (wrapped in a ModelResponse), an exception (raised), or any other
    object (returned as-is, to simulate a misbehaving adapter).
    Every call is recorded in `calls`.
    """

    name = "fake"
    model_label = "fake-deterministic-v2"

    def __init__(self, scripted: Sequence[Any] | None = None, usage: Usage = Usage()):
        self._scripted = list(scripted) if scripted is not None else None
        self._usage = usage
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
        return ModelResponse(
            content=content,
            model=ModelInfo(adapter=self.name, model=self.model_label),
            usage=self._usage,
        )
