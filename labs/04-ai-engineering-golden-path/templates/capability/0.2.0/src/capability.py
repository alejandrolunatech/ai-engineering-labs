"""Change Explainer capability runtime.

Run from the project root:

    python src/capability.py fixtures/sample_input.json

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
measured. max_latency_ms is declared only.

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
from model_adapter import FakeModelAdapter, ModelAdapter, ModelInfo, ModelRequest, ModelResponse

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
        )
    return validate_output(manifest, response.content, model_requests_used=used), response.model


async def run(
    payload: Any,
    *,
    manifest: Manifest | None = None,
    adapter: ModelAdapter | None = None,
) -> CapabilityResult:
    manifest = manifest if manifest is not None else load_manifest()

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

    validate_input(manifest, payload)

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
        try:
            response = await adapter.generate(request)
        except Exception as exc:
            raise ModelInvocationError(
                f"adapter {adapter.name!r} raised {type(exc).__name__} on request "
                f"{budget.used}/{budget.limit}; not retried",
                model_requests_used=budget.used,
            ) from exc
        try:
            output, info = _accept_response(manifest, response, budget.used)
        except OutputValidationError as exc:
            last_error = exc
            continue
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
    ) from last_error


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="capability.py", description="Run this capability once.")
    parser.add_argument("input", type=Path, help="path to a JSON input file")
    args = parser.parse_args(argv)

    try:
        try:
            payload = parse_json_strict(args.input.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            raise InputValidationError(f"cannot read input as strict JSON: {type(exc).__name__}") from None
        result = asyncio.run(run(payload))
    except CapabilityError as exc:
        error = {
            "error": type(exc).__name__,
            "message": str(exc),
            "model_requests_used": exc.model_requests_used,
        }
        print(json.dumps(error, sort_keys=True), file=sys.stderr)
        return exc.exit_code

    print(result.to_json())
    return 0


if __name__ == "__main__":
    sys.exit(main())
