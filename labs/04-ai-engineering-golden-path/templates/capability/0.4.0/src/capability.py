"""Change Explainer capability runtime.

Run from the project root:

    python src/capability.py fixtures/sample_input.json [--correlation-id ID] [--telemetry-file PATH]

stdout: the CapabilityResult (JSON) on success.
stderr: typed JSONL records: {"record": "span", ...} telemetry and
        {"record": "error", ...} on failure. With --telemetry-file, span
        records are appended to that file instead (never created implicitly).

Flow:
    load + validate capability.yaml            deterministic
    refuse declared tools (no tool runtime)    deterministic
    resolve adapter from explicit registry     deterministic
    validate input                             deterministic, BEFORE any model call
    while the request budget has capacity:
        consume one request                    deterministic, BEFORE each adapter call
        await adapter.generate(request)        probabilistic with a real model;
                                               deterministic with FakeModelAdapter
        validate output                        deterministic; invalid output may retry
    return CapabilityResult                    only schema-valid output is ever returned

Budgets: only spec.budgets.max_model_requests is enforced here.
max_output_tokens is passed to the adapter as declared intent and is not
measured. max_latency_ms is MEASURED in telemetry (latency.over_declared_max)
but not enforced: measurement is not enforcement.

Telemetry (src/telemetry.py) observes the flow; it never changes the outcome.
One root "capability.run" span per call, one "capability.model_request" span
per attempted adapter call, and an "input_validation" event.

Retrying schema-invalid output within the request budget is this template's
runtime policy, not a universal recommendation for every AI capability.
Adapter exceptions are not retried.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from contracts import (
    CapabilityError,
    InputValidationError,
    Manifest,
    ManifestError,
    ModelInvocationError,
    ModelRequestBudgetExceeded,
    OutputValidationError,
    load_manifest,
    parse_json_strict,
    validate_input,
    validate_output,
)
from cost import Attempt, Pricing, attempt_attributes, load_pricing, run_attributes
from model_adapter import FakeModelAdapter, ModelAdapter, ModelInfo, ModelRequest, ModelResponse
from telemetry import (
    JsonlSink,
    NullSink,
    Span,
    Telemetry,
    is_valid_identifier,
    new_identifier,
    safe_model_label,
)

INSTRUCTIONS = (
    "Explain the software change described in the input for a non-specialist "
    "stakeholder. Respond only with JSON that matches the output schema."
)

# Explicit adapter registry. The manifest selects an adapter by slug; nothing
# named in the manifest is ever imported dynamically. Unknown slugs fail closed.
ADAPTERS = {"fake": FakeModelAdapter}


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


def resolve_adapter(manifest: Manifest) -> ModelAdapter:
    factory = ADAPTERS.get(manifest.adapter)
    if factory is None:
        raise ManifestError(
            f"unknown adapter {manifest.adapter!r}; this project registers {sorted(ADAPTERS)}"
        )
    return factory()


def _accept_response(manifest: Manifest, response: Any, used: int) -> tuple[dict, ModelInfo]:
    if not isinstance(response, ModelResponse) or not isinstance(response.model, ModelInfo):
        raise OutputValidationError(
            f"adapter returned {type(response).__name__}, expected ModelResponse",
            model_requests_used=used,
            failed_rules=("model_response_type",),
        )
    return validate_output(manifest, response.content, model_requests_used=used), response.model


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
) -> CapabilityResult:
    """Run the capability once.

    Library callers that pass no `telemetry` get a NullSink: records are built
    and validated but discarded. The command line always passes a real sink.
    """
    if telemetry is None:
        telemetry = Telemetry(NullSink(), correlation_id=new_identifier())
    attempts: list[Attempt] = []
    state: dict[str, Any] = {"pricing": pricing}
    with telemetry.span("capability.run") as root:
        try:
            return await _execute(payload, manifest, adapter, telemetry, root, attempts, state)
        except CapabilityError as exc:
            root.fail(type(exc).__name__)
            raise
        finally:
            root.set("model_requests.used", len(attempts))
            root.set_all(run_attributes(attempts, state["pricing"]))


async def _execute(
    payload: Any,
    manifest: Manifest | None,
    adapter: ModelAdapter | None,
    telemetry: Telemetry,
    root: Span,
    attempts: list[Attempt],
    state: dict[str, Any],
) -> CapabilityResult:
    manifest = manifest if manifest is not None else load_manifest()
    root.set_all(_declared_attributes(manifest))
    root.declared_max_latency_ms = manifest.max_latency_ms
    if state["pricing"] is None:
        state["pricing"] = load_pricing()
    pricing: Pricing = state["pricing"]

    if manifest.tools:
        raise ManifestError(
            f"authority.tools declares {len(manifest.tools)} tool(s), but this template "
            f"version has no tool runtime; refusing to run"
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
            try:
                output, info = _accept_response(manifest, response, budget.used)
            except OutputValidationError as exc:
                span.set("model_request.outcome", "output_invalid")
                span.set("output_validation.failed_rules", list(exc.failed_rules))
                span.fail(type(exc).__name__)
                last_error = exc
                continue
            span.set("model_request.outcome", "output_valid")

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


def _error_record(error: str, message: str, model_requests_used: int | None) -> str:
    return json.dumps(
        {"record": "error", "error": error, "message": message, "model_requests_used": model_requests_used},
        sort_keys=True,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="capability.py", description="Run this capability once.")
    parser.add_argument("input", type=Path, help="path to a JSON input file")
    parser.add_argument("--correlation-id", help="label grouping related runs; generated when absent")
    parser.add_argument(
        "--telemetry-file",
        type=Path,
        help="append telemetry span records (JSONL) to this file instead of stderr",
    )
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
        print(_error_record(type(exc).__name__, str(exc), exc.model_requests_used), file=sys.stderr)
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
