"""Starter tests for this capability's runtime boundaries.

Deterministic and offline: every test uses FakeModelAdapter. These prove the
runtime's contract enforcement, not the quality of any model's explanations.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from pathlib import Path

import pytest

from capability import ADAPTERS, RequestBudget, run
from contracts import (
    InputValidationError,
    ManifestError,
    ModelInvocationError,
    ModelRequestBudgetExceeded,
    OutputValidationError,
    load_manifest,
    validate_output,
)
from model_adapter import FakeModelAdapter, ModelInfo, ModelResponse

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = json.loads((ROOT / "fixtures" / "sample_input.json").read_text(encoding="utf-8"))

VALID_OUTPUT = {
    "headline": "CHG-1: Example",
    "explanation": "A valid explanation.",
    "risk_level": "low",
    "open_questions": [],
}


def as_text(value) -> str:
    return json.dumps(value)


def execute(payload, adapter, **manifest_changes):
    manifest = replace(load_manifest(), **manifest_changes)
    return asyncio.run(run(payload, manifest=manifest, adapter=adapter))


# --- manifest -----------------------------------------------------------------


def test_manifest_is_valid_against_contract_snapshot():
    manifest = load_manifest()
    assert manifest.adapter in ADAPTERS
    assert manifest.tools == ()
    assert 1 <= manifest.max_model_requests <= 10


# --- happy path -----------------------------------------------------------------


def test_sample_input_produces_schema_valid_result():
    adapter = FakeModelAdapter()
    result = execute(SAMPLE, adapter)
    validate_output(load_manifest(), json.dumps(result.output), model_requests_used=1)
    assert result.model_requests == {"used": 1, "limit": load_manifest().max_model_requests}
    assert result.model["adapter_reported"] == {"adapter": "fake", "model": "fake-deterministic-v1"}
    assert len(adapter.calls) == 1


def test_fake_adapter_is_deterministic():
    assert execute(SAMPLE, FakeModelAdapter()) == execute(SAMPLE, FakeModelAdapter())


def test_request_is_built_from_manifest_and_validated_input():
    adapter = FakeModelAdapter()
    manifest = load_manifest()
    execute(SAMPLE, adapter)
    request = adapter.calls[0]
    assert request.input == SAMPLE
    assert request.profile == manifest.profile
    assert request.max_output_tokens == manifest.max_output_tokens
    assert request.output_schema == manifest.output_schema


# --- invalid input never reaches the model ---------------------------------------

INVALID_INPUTS = {
    "missing-field": {k: v for k, v in SAMPLE.items() if k != "summary"},
    "extra-field": {**SAMPLE, "priority": "high"},
    "bad-change-id": {**SAMPLE, "change_id": "1042"},
    "files-not-list": {**SAMPLE, "files_changed": "src/app.py"},
    "empty-title": {**SAMPLE, "title": ""},
    "list-instead-of-object": [SAMPLE],
    "string-instead-of-object": "CHG-1042",
    "null": None,
}


@pytest.mark.parametrize("payload", INVALID_INPUTS.values(), ids=INVALID_INPUTS.keys())
def test_invalid_input_never_invokes_model(payload):
    adapter = FakeModelAdapter()
    with pytest.raises(InputValidationError) as caught:
        execute(payload, adapter)
    assert adapter.calls == []
    assert caught.value.model_requests_used == 0


def test_input_error_does_not_echo_values():
    marker = "SENSITIVE-INPUT-MARKER"
    with pytest.raises(InputValidationError) as caught:
        execute({**SAMPLE, "change_id": marker}, FakeModelAdapter())
    assert marker not in str(caught.value)
    assert "change_id" in str(caught.value)


# --- invalid output is rejected --------------------------------------------------

INVALID_OUTPUTS = {
    "not-json": "The change looks fine.",
    "json-array": as_text([VALID_OUTPUT]),
    "missing-risk-level": as_text({k: v for k, v in VALID_OUTPUT.items() if k != "risk_level"}),
    "extra-key": as_text({**VALID_OUTPUT, "approved": True}),
    "unknown-risk-level": as_text({**VALID_OUTPUT, "risk_level": "catastrophic"}),
    "headline-too-long": as_text({**VALID_OUTPUT, "headline": "x" * 121}),
    "duplicate-key": '{"headline": "a", "headline": "b", "explanation": "e", "risk_level": "low", "open_questions": []}',
    "nan-constant": '{"headline": NaN}',
    "content-not-text": ModelResponse(content=VALID_OUTPUT, model=ModelInfo("fake", "x")),
    "not-a-model-response": {"content": as_text(VALID_OUTPUT)},
}


@pytest.mark.parametrize("scripted", INVALID_OUTPUTS.values(), ids=INVALID_OUTPUTS.keys())
def test_invalid_output_is_rejected(scripted):
    adapter = FakeModelAdapter(scripted=[scripted])
    with pytest.raises(OutputValidationError) as caught:
        execute(SAMPLE, adapter, max_model_requests=1)
    assert len(adapter.calls) == 1
    assert caught.value.model_requests_used == 1


def test_output_error_does_not_echo_values():
    marker = "SENSITIVE-OUTPUT-MARKER"
    adapter = FakeModelAdapter(scripted=[as_text({**VALID_OUTPUT, "risk_level": marker})])
    with pytest.raises(OutputValidationError) as caught:
        execute(SAMPLE, adapter, max_model_requests=1)
    assert marker not in str(caught.value)
    assert "risk_level" in str(caught.value)


# --- request budget ----------------------------------------------------------------


def test_invalid_output_retries_while_budget_remains():
    adapter = FakeModelAdapter(scripted=["not json", as_text(VALID_OUTPUT)])
    result = execute(SAMPLE, adapter, max_model_requests=2)
    assert result.output == VALID_OUTPUT
    assert result.model_requests == {"used": 2, "limit": 2}


def test_never_exceeds_max_model_requests():
    adapter = FakeModelAdapter(scripted=["bad", "bad", as_text(VALID_OUTPUT)])
    with pytest.raises(OutputValidationError) as caught:
        execute(SAMPLE, adapter, max_model_requests=2)
    assert len(adapter.calls) == 2  # the valid third response is never requested
    assert caught.value.model_requests_used == 2


def test_budget_of_one_means_no_retry():
    adapter = FakeModelAdapter(scripted=["bad", as_text(VALID_OUTPUT)])
    with pytest.raises(OutputValidationError):
        execute(SAMPLE, adapter, max_model_requests=1)
    assert len(adapter.calls) == 1


def test_adapter_exception_counts_and_is_not_retried():
    adapter = FakeModelAdapter(scripted=[TimeoutError("upstream"), as_text(VALID_OUTPUT)])
    with pytest.raises(ModelInvocationError) as caught:
        execute(SAMPLE, adapter, max_model_requests=2)
    assert len(adapter.calls) == 1
    assert caught.value.model_requests_used == 1


def test_request_budget_refuses_beyond_limit():
    budget = RequestBudget(2)
    budget.consume()
    budget.consume()
    with pytest.raises(ModelRequestBudgetExceeded):
        budget.consume()
    assert budget.used == 2


# --- fail closed on unsupported configuration --------------------------------------


def test_declared_tools_fail_closed_before_model():
    adapter = FakeModelAdapter()
    with pytest.raises(ManifestError, match="no tool runtime"):
        execute(SAMPLE, adapter, tools=("search_docs",))
    assert adapter.calls == []


def test_unknown_adapter_fails_closed():
    manifest = replace(load_manifest(), adapter="some-provider")
    with pytest.raises(ManifestError, match="unknown adapter"):
        asyncio.run(run(SAMPLE, manifest=manifest))


def test_injected_adapter_must_match_declared_adapter():
    adapter = FakeModelAdapter()
    adapter.name = "other"
    with pytest.raises(ManifestError, match="does not match declared adapter"):
        execute(SAMPLE, adapter)
    assert adapter.calls == []
