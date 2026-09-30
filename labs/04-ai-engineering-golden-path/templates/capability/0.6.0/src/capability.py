"""Change Explainer capability runtime.

Run from the project root:

    python src/capability.py fixtures/sample_input.json [--correlation-id ID] [--telemetry-file PATH]

stdout: the CapabilityResult (JSON) on success.
stderr: typed JSONL records: {"record": "span", ...} telemetry and
        {"record": "error", ...} on failure. With --telemetry-file, span
        records are appended to that file instead (never created implicitly).

Flow:
    load + validate capability.yaml            deterministic
    declared tools must be registered          deterministic, BEFORE any model call
    resolve adapter from explicit registry     deterministic
    validate input                             deterministic, BEFORE any model call
    while the request budget has capacity:
        consume one request                    deterministic, BEFORE each adapter call
        await adapter.generate(request)        probabilistic with a real model;
                                               deterministic with FakeModelAdapter
        validate response envelope             deterministic
        TOOL PREFLIGHT (every proposal)        deterministic: structure, ceiling,
                                               declared, registered, arguments
            any rejection -> fail closed (exit 6): no policy, no execution, no retry
        validate business output               deterministic
            invalid -> proposals DISCARDED: no policy call, no execution; may retry
        POLICY AUTHORIZATION (all proposals)   trusted policy hook; accepted response only
            any denial/error -> fail closed (exit 6), execute NOTHING
        EXECUTE (all authorized proposals)     strictly last, at most once per run
            executor failure -> exit 7 (side effects may exist)
    return CapabilityResult                    only schema-valid output is ever returned

preflight != authorization != execution. No tool can execute from a response
that will be retried, and no model request happens after an execution.

Budgets: only spec.budgets.max_model_requests is enforced here.
max_output_tokens is passed to the adapter as declared intent and is not
measured. max_latency_ms is MEASURED in telemetry (latency.over_declared_max)
but not enforced: measurement is not enforcement.

Telemetry (src/telemetry.py) observes the flow; it never changes the outcome.
One root "capability.run" span per call, one "capability.model_request" span
per attempted adapter call, an "input_validation" event, and one
"capability.tool_request" span (a child of the root) per tool proposal.

Retrying schema-invalid output within the request budget is this template's
runtime policy, not a universal recommendation for every AI capability.
Adapter exceptions and tool rejections are not retried.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from contextlib import ExitStack
from dataclasses import asdict, dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from contracts import (
    CapabilityError,
    InputValidationError,
    Manifest,
    ManifestError,
    ModelInvocationError,
    ModelRequestBudgetExceeded,
    OutputValidationError,
    ToolExecutionFailed,
    ToolPolicyDenied,
    ToolPolicyError,
    ToolRequestRejected,
    load_manifest,
    parse_json_strict,
    validate_input,
    validate_output,
)
from cost import Attempt, Pricing, attempt_attributes, load_pricing, run_attributes
from model_adapter import FakeModelAdapter, ModelAdapter, ModelInfo, ModelRequest, ModelResponse
from policy import DefaultPolicy, PolicyContext, PolicyDecision, PolicyHook
from telemetry import (
    JsonlSink,
    NullSink,
    Span,
    Telemetry,
    is_valid_identifier,
    new_identifier,
    safe_model_label,
)
from tools import TOOL_REGISTRY, ExecutionGuard, SyntheticLedger, ToolDefinition, ToolProposal, preflight

INSTRUCTIONS = (
    "Explain the software change described in the input for a non-specialist "
    "stakeholder. Respond only with JSON that matches the output schema."
)

# Explicit adapter registry. The manifest selects an adapter by slug; nothing
# named in the manifest is ever imported dynamically. Unknown slugs fail closed.
ADAPTERS = {"fake": FakeModelAdapter}

_REASON_CODE = re.compile(r"[a-z][a-z0-9_]{0,63}")


class RequestBudget:
    """Counts model requests. The only gate in front of every adapter call."""

    def __init__(self, limit: int):
        self.limit = limit
        self.used = 0

    @property
    def remaining(self) -> int:
        return self.limit - self.used

    def consume(self) -> None:
        if self.used >= self.limit:
            raise ModelRequestBudgetExceeded(
                f"max_model_requests={self.limit} exhausted", model_requests_used=self.used
            )
        self.used += 1


@dataclass(frozen=True)
class CapabilityResult:
    capability: dict  # declared: from capability.yaml
    model: dict  # declared adapter/profile plus adapter-reported (untrusted) labels
    model_requests: dict  # enforced budget: used / limit
    output: dict  # schema-valid model output

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, sort_keys=True)


@dataclass
class _ToolRuntime:
    """Trusted, per-run tool state. None of it can be influenced by the model."""

    policy: PolicyHook
    ledger: SyntheticLedger
    registry: Mapping[str, ToolDefinition]
    guard: ExecutionGuard
    proposals: list[ToolProposal]
    unspanned_proposals: int = 0  # proposals in a container rejected as a whole


def resolve_adapter(manifest: Manifest) -> ModelAdapter:
    factory = ADAPTERS.get(manifest.adapter)
    if factory is None:
        raise ManifestError(
            f"unknown adapter {manifest.adapter!r}; this project registers {sorted(ADAPTERS)}"
        )
    return factory()


def _declared_attributes(manifest: Manifest) -> dict:
    return {
        "capability.name": manifest.name,
        "capability.version": manifest.version,
        "capability.template_version": manifest.template_version,
        "capability.model.declared_adapter": manifest.adapter,
        "capability.model.declared_profile": manifest.profile,
        "capability.budget.max_model_requests": manifest.max_model_requests,
        "capability.budget.max_latency_ms": manifest.max_latency_ms,
        "capability.data.sensitivity": manifest.data_sensitivity,
    }


async def run(
    payload: Any,
    *,
    manifest: Manifest | None = None,
    adapter: ModelAdapter | None = None,
    pricing: Pricing | None = None,
    telemetry: Telemetry | None = None,
    policy: PolicyHook | None = None,
    ledger: SyntheticLedger | None = None,
    registry: Mapping[str, ToolDefinition] | None = None,
) -> CapabilityResult:
    """Run the capability once.

    `policy`, `ledger` and `registry` are trusted-code injection points (tests,
    or a product team's own code). Nothing in model output can set them. The
    command line always uses DefaultPolicy and TOOL_REGISTRY.

    Library callers that pass no `telemetry` get a NullSink: records are built
    and validated but discarded. The command line always passes a real sink.
    """
    if telemetry is None:
        telemetry = Telemetry(NullSink(), correlation_id=new_identifier())
    tools = _ToolRuntime(
        policy=policy if policy is not None else DefaultPolicy(),
        ledger=ledger if ledger is not None else SyntheticLedger(),
        registry=registry if registry is not None else TOOL_REGISTRY,
        guard=ExecutionGuard(),
        proposals=[],
    )
    attempts: list[Attempt] = []
    state: dict[str, Any] = {"pricing": pricing}
    with telemetry.span("capability.run") as root:
        try:
            return await _execute(payload, manifest, adapter, telemetry, root, attempts, tools, state)
        except CapabilityError as exc:
            root.fail(type(exc).__name__)
            raise
        finally:
            root.set("model_requests.used", len(attempts))
            root.set_all(run_attributes(attempts, state["pricing"]))
            root.set_all(
                {
                    "tools.proposed": len(tools.proposals) + tools.unspanned_proposals,
                    "tools.authorized": sum(p.authorization_status == "allowed" for p in tools.proposals),
                    "tools.executed": sum(p.execution_status == "succeeded" for p in tools.proposals),
                }
            )


def _record_tool_span(span: Span, proposal: ToolProposal) -> None:
    span.set_all(proposal.attributes())
    if proposal.outcome in ("rejected", "denied", "execution_failed"):
        span.fail(proposal.error_type or "ToolRequestRejected")


def _emit_tool_spans(telemetry: Telemetry, root: Span, proposals: list[ToolProposal]) -> None:
    for proposal in proposals:
        with telemetry.span("capability.tool_request", parent=root) as span:
            _record_tool_span(span, proposal)


async def _authorize_all(proposals: list[ToolProposal], manifest: Manifest, tools: _ToolRuntime, used: int) -> None:
    """Every policy decision happens before the first executor call."""
    for proposal in proposals:
        context = PolicyContext(
            capability=manifest.name,
            capability_version=manifest.version,
            template_version=manifest.template_version,
            data_sensitivity=manifest.data_sensitivity,
            tool_name=proposal.definition.name,
            tool_impact=proposal.definition.impact,
        )
        try:
            # A read-only copy: the policy cannot change what would execute.
            decision = await tools.policy.authorize(context, MappingProxyType(dict(proposal.arguments)))
            valid = isinstance(decision, PolicyDecision) and type(decision.allowed) is bool
        except Exception:
            valid = False
        if not valid:
            proposal.authorization_status, proposal.outcome = "policy_error", "denied"
            proposal.error_type = "ToolPolicyError"
            raise ToolPolicyError(
                f"policy failed for tool {proposal.name!r}; treated as denied, nothing executed",
                reason="policy_error",
                model_requests_used=used,
            )
        code = decision.reason_code
        proposal.policy_reason_code = code if isinstance(code, str) and _REASON_CODE.fullmatch(code) else "unrecognized"
        if not decision.allowed:
            proposal.authorization_status, proposal.outcome = "denied", "denied"
            proposal.error_type = "ToolPolicyDenied"
            raise ToolPolicyDenied(
                f"policy denied tool {proposal.name!r} ({proposal.policy_reason_code}); nothing executed",
                reason=proposal.policy_reason_code,
                model_requests_used=used,
            )
        proposal.authorization_status = "allowed"


async def _execute_all(proposals: list[ToolProposal], tools: _ToolRuntime, used: int) -> None:
    """Strictly last. Tool results are discarded: there is no tool-result loop."""
    for proposal in proposals:
        tools.guard.claim(proposal.name, proposal.arguments)
        try:
            await proposal.definition.execute(MappingProxyType(dict(proposal.arguments)), tools.ledger)
        except Exception as exc:
            proposal.execution_status, proposal.outcome = "failed", "execution_failed"
            proposal.error_type = type(exc).__name__  # class name only
            raise ToolExecutionFailed(
                f"tool {proposal.name!r} raised {type(exc).__name__}; side effects may exist",
                reason="execution_failed",
                model_requests_used=used,
            ) from exc
        proposal.execution_status, proposal.outcome = "succeeded", "executed"


async def _execute(
    payload: Any,
    manifest: Manifest | None,
    adapter: ModelAdapter | None,
    telemetry: Telemetry,
    root: Span,
    attempts: list[Attempt],
    tools: _ToolRuntime,
    state: dict[str, Any],
) -> CapabilityResult:
    manifest = manifest if manifest is not None else load_manifest()
    root.set_all(_declared_attributes(manifest))
    root.declared_max_latency_ms = manifest.max_latency_ms
    if state["pricing"] is None:
        state["pricing"] = load_pricing()
    pricing: Pricing = state["pricing"]

    unregistered = [name for name in manifest.tools if name not in tools.registry]
    if unregistered:
        raise ManifestError(
            f"authority.tools declares {len(unregistered)} tool(s) with no trusted registry "
            f"implementation; refusing to run"
        )

    adapter = adapter if adapter is not None else resolve_adapter(manifest)
    if adapter.name != manifest.adapter:
        raise ManifestError(
            f"adapter {adapter.name!r} does not match declared adapter {manifest.adapter!r}"
        )

    try:
        validate_input(manifest, payload)
    except InputValidationError as exc:
        root.event(
            "input_validation",
            {"input_validation.result": "failed", "input_validation.failed_rules": list(exc.failed_rules)},
        )
        raise
    root.event("input_validation", {"input_validation.result": "passed", "input_validation.failed_rules": []})

    request = ModelRequest(
        capability=manifest.name,
        profile=manifest.profile,
        instructions=INSTRUCTIONS,
        input=payload,
        output_schema=manifest.output_schema,
        max_output_tokens=manifest.max_output_tokens,
        # Exposed = declared AND registered. Visibility is not authorization.
        tools=tuple(tools.registry[name].spec() for name in manifest.tools),
    )
    budget = RequestBudget(manifest.max_model_requests)
    last_error: OutputValidationError | None = None

    while budget.remaining > 0:
        budget.consume()
        with telemetry.span("capability.model_request", parent=root) as span:
            span.set("model_request.attempt", budget.used)
            span.set("adapter.name", adapter.name)
            try:
                response = await adapter.generate(request)
            except Exception as exc:
                attempt = Attempt.no_response(adapter.name)
                attempts.append(attempt)
                span.set_all(attempt_attributes(attempt, pricing))
                span.set("adapter.reported_model", None)
                span.set("model_request.outcome", "adapter_error")
                span.fail(type(exc).__name__)  # class name only, never the message
                raise ModelInvocationError(
                    f"adapter {adapter.name!r} raised {type(exc).__name__} on request "
                    f"{budget.used}/{budget.limit}; not retried",
                    model_requests_used=budget.used,
                ) from exc

            attempt = Attempt.from_response(adapter.name, response)
            attempts.append(attempt)
            span.set_all(attempt_attributes(attempt, pricing))
            span.set(
                "adapter.reported_model",
                safe_model_label(attempt.reported_model) if attempt.reported_model is not None else None,
            )

            # 1. Envelope. A malformed envelope carries no usable proposals.
            if not isinstance(response, ModelResponse) or not isinstance(response.model, ModelInfo):
                error = OutputValidationError(
                    f"adapter returned {type(response).__name__}, expected ModelResponse",
                    model_requests_used=budget.used,
                    failed_rules=("model_response_type",),
                )
                span.set("model_request.outcome", "output_invalid")
                span.set("output_validation.failed_rules", list(error.failed_rules))
                span.fail(type(error).__name__)
                last_error = error
                continue

            # 2. Tool preflight: deterministic, no policy call, no side effects.
            container = response.tool_requests
            sized = isinstance(container, (tuple, list))
            span.set("model_request.tool_requests", len(container) if sized else None)
            try:
                proposals = preflight(container, manifest.tools, tools.registry, budget.used, budget.used)
            except ToolRequestRejected as exc:
                tools.unspanned_proposals += len(container) if sized else 0
                span.set("model_request.outcome", "tool_rejected")
                span.set("model_request.tool_rejection_reason", exc.reason)
                span.fail(type(exc).__name__)
                raise
            tools.proposals.extend(proposals)

            # 3. Business output validation.
            try:
                output = validate_output(manifest, response.content, model_requests_used=budget.used)
                output_error = None
            except OutputValidationError as exc:
                output, output_error = None, exc

            rejected = [p for p in proposals if p.preflight_status == "rejected"]
            if rejected:
                span.set("model_request.outcome", "tool_rejected")
                span.fail("ToolRequestRejected")
            elif output_error is not None:
                span.set("model_request.outcome", "output_invalid")
                span.set("output_validation.failed_rules", list(output_error.failed_rules))
                span.fail(type(output_error).__name__)
            else:
                span.set("model_request.outcome", "output_valid")

        if rejected:
            # Fail closed: nothing from this response proceeds, and there is no retry.
            for proposal in proposals:
                if proposal.preflight_status == "rejected":
                    proposal.error_type = "ToolRequestRejected"
                else:
                    proposal.outcome = "discarded"
            _emit_tool_spans(telemetry, root, proposals)
            raise ToolRequestRejected(
                f"tool proposal rejected in preflight ({rejected[0].rejection_reason}); nothing executed",
                reason=rejected[0].rejection_reason,
                model_requests_used=budget.used,
            )
        if output_error is not None:
            # Unusable response: no policy call, no execution. May retry.
            for proposal in proposals:
                proposal.outcome = "discarded"
            _emit_tool_spans(telemetry, root, proposals)
            last_error = output_error
            continue

        # 4 + 5. Accepted response: authorize ALL, then execute. With the
        # Phase-6 ceiling of one proposal, partial multi-tool states cannot occur.
        with ExitStack() as stack:
            tool_spans = [stack.enter_context(telemetry.span("capability.tool_request", parent=root)) for _ in proposals]
            try:
                await _authorize_all(proposals, manifest, tools, budget.used)
                await _execute_all(proposals, tools, budget.used)
            finally:
                for tool_span, proposal in zip(tool_spans, proposals):
                    _record_tool_span(tool_span, proposal)

        info = response.model
        return CapabilityResult(
            capability={
                "name": manifest.name,
                "version": manifest.version,
                "template_version": manifest.template_version,
            },
            model={
                "declared_adapter": manifest.adapter,
                "declared_profile": manifest.profile,
                "adapter_reported": {"adapter": info.adapter, "model": info.model},
            },
            model_requests={"used": budget.used, "limit": budget.limit},
            output=output,
        )

    raise OutputValidationError(
        f"no schema-valid output after {budget.used}/{budget.limit} model requests; "
        f"last error: {last_error}",
        model_requests_used=budget.used,
        failed_rules=last_error.failed_rules if last_error else (),
    ) from last_error


TELEMETRY_DELIVERY_EXIT_CODE = 5


def _error_record(error: str, message: str, model_requests_used: int | None, reason: str | None = None) -> str:
    record = {"record": "error", "error": error, "message": message, "model_requests_used": model_requests_used}
    if reason is not None:
        record["reason"] = reason
    return json.dumps(record, sort_keys=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="capability.py", description="Run this capability once.")
    parser.add_argument("input", type=Path, help="path to a JSON input file")
    parser.add_argument("--correlation-id", help="label grouping related runs; generated when absent")
    parser.add_argument(
        "--telemetry-file",
        type=Path,
        help="append telemetry span records (JSONL) to this file instead of stderr",
    )
    # Deliberately no option to change the policy or allow high-impact tools:
    # the command line must not become an authority bypass.
    args = parser.parse_args(argv)
    if args.correlation_id is not None and not is_valid_identifier(args.correlation_id):
        parser.error("--correlation-id must match [A-Za-z0-9._:-]{1,128}")

    telemetry_stream = sys.stderr
    if args.telemetry_file is not None:
        try:
            telemetry_stream = args.telemetry_file.open("a", encoding="utf-8")
        except OSError as exc:
            # Tracing is declared as required, so refuse to run untraced.
            print(_error_record("TelemetryDeliveryError", f"cannot open telemetry file: {type(exc).__name__}", 0), file=sys.stderr)
            return TELEMETRY_DELIVERY_EXIT_CODE
    telemetry = Telemetry(JsonlSink(telemetry_stream), correlation_id=args.correlation_id or new_identifier())

    try:
        try:
            payload = parse_json_strict(args.input.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            raise InputValidationError(f"cannot read input as strict JSON: {type(exc).__name__}") from None
        result = asyncio.run(run(payload, telemetry=telemetry))
    except CapabilityError as exc:
        print(_error_record(type(exc).__name__, str(exc), exc.model_requests_used, exc.reason), file=sys.stderr)
        exit_code = exc.exit_code
    else:
        print(result.to_json())
        exit_code = 0
    finally:
        if telemetry_stream is not sys.stderr:
            telemetry_stream.close()

    if telemetry.delivery_failures:
        # The capability outcome above stands (and is never retried); only the
        # telemetry evidence is incomplete.
        print(
            _error_record("TelemetryDeliveryError", f"{len(telemetry.delivery_failures)} telemetry record(s) not delivered", None),
            file=sys.stderr,
        )
        return exit_code or TELEMETRY_DELIVERY_EXIT_CODE
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
