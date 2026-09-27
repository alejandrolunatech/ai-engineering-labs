"""Deterministic tests for telemetry, usage and cost evidence.

Every test injects a fake clock, fixed trace/correlation ids and an in-memory
sink. No real time, network or exporter is involved. These prove what
evidence is produced and what is never recorded. They do not prove real
latency, provider usage honesty or billing accuracy.
"""

from __future__ import annotations

import asyncio
import io
import json
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest

from capability import run
from contracts import CapabilityError, ManifestError, load_manifest
from cost import Price, Pricing, load_pricing, run_attributes
from model_adapter import FakeModelAdapter, ModelInfo, ModelResponse, Usage
from telemetry import (
    InMemorySink,
    JsonlSink,
    Telemetry,
    TelemetryContractError,
    safe_model_label,
)

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = json.loads((ROOT / "fixtures" / "sample_input.json").read_text(encoding="utf-8"))
LABEL = FakeModelAdapter.model_label

# Synthetic test evidence only: not a real price for any real model.
TEST_PRICING = Pricing(
    currency="USD",
    prices=(Price("fake", LABEL, Decimal("0.50"), Decimal("1.50")),),
)
NO_PRICING = Pricing(currency="USD")

VALID = json.dumps(
    {"headline": "CHG-1: Example", "explanation": "A valid explanation.", "risk_level": "low", "open_questions": []}
)
MARKERS = ("SECRET-TITLE-MARKER", "SECRET-SUMMARY-MARKER", "secret/path/marker.py", "SECRET-OUTPUT-MARKER", "SECRET-EXCEPTION-MARKER")
MARKED_INPUT = {
    **SAMPLE,
    "title": "SECRET-TITLE-MARKER",
    "summary": "SECRET-SUMMARY-MARKER explains the change in enough words.",
    "files_changed": ["secret/path/marker.py"],
}


class FakeClock:
    """Each reading advances 1 ms (monotonic) and 1 s (wall)."""

    def __init__(self) -> None:
        self.ticks = 0

    def monotonic_ns(self) -> int:
        self.ticks += 1
        return self.ticks * 1_000_000

    def time_ns(self) -> int:
        return 1_700_000_000_000_000_000 + self.ticks * 1_000_000_000


def reply(content, usage=Usage(), model=LABEL) -> ModelResponse:
    return ModelResponse(content=content, model=ModelInfo("fake", model), usage=usage)


def traced(payload, adapter, *, pricing=NO_PRICING, **manifest_changes):
    sink = InMemorySink()
    telemetry = Telemetry(sink, correlation_id="test-correlation", clock=FakeClock(), new_trace_id=lambda: "trace-1")
    manifest = replace(load_manifest(), **manifest_changes)
    try:
        result = asyncio.run(run(payload, manifest=manifest, adapter=adapter, pricing=pricing, telemetry=telemetry))
        error = None
    except CapabilityError as exc:
        result, error = None, exc
    return result, error, sink.records


def root_of(records):
    [root] = [r for r in records if r["name"] == "capability.run"]
    return root


def requests_of(records):
    return sorted(
        (r for r in records if r["name"] == "capability.model_request"),
        key=lambda r: r["attributes"]["model_request.attempt"],
    )


def assert_common(records, *, status, used):
    root = root_of(records)
    assert root["status"] == status
    assert root["attributes"]["model_requests.used"] == used
    assert len(requests_of(records)) == used
    assert root["duration_ms"] > 0  # present; exact value comes from the fake clock
    assert all(r["duration_ms"] > 0 for r in requests_of(records))
    assert all(r["trace_id"] == "trace-1" and r["correlation_id"] == "test-correlation" for r in records)
    serialized = json.dumps(records)
    for marker in MARKERS:
        assert marker not in serialized
    return root


# --- the scenarios ---------------------------------------------------------------------


def test_one_request_success_usage_unknown_not_zero():
    result, error, records = traced(MARKED_INPUT, FakeModelAdapter())
    assert error is None and result is not None
    root = assert_common(records, status="ok", used=1)
    [request] = requests_of(records)
    assert request["attributes"]["model_request.outcome"] == "output_valid"
    assert request["attributes"]["adapter.reported_model"] == LABEL
    for span in (root, request):
        assert span["attributes"]["usage.status"] == "unknown"
        assert span["attributes"]["usage.input_tokens"] is None  # unknown, NOT 0
        assert span["attributes"]["usage.output_tokens"] is None
        assert span["attributes"]["cost.status"] == "unknown"
        assert span["attributes"]["cost.unknown_reason"] == "no_pricing"
        assert span["attributes"]["cost.estimated"] is None
    assert root["events"] == [
        {"name": "input_validation", "attributes": {"input_validation.result": "passed", "input_validation.failed_rules": []}}
    ]
    assert root["attributes"]["capability.template_version"] == load_manifest().template_version


def test_invalid_input_zero_requests_is_a_known_zero():
    adapter = FakeModelAdapter()
    _, error, records = traced({**MARKED_INPUT, "change_id": "SECRET-TITLE-MARKER"}, adapter)
    assert type(error).__name__ == "InputValidationError"
    root = assert_common(records, status="error", used=0)
    assert adapter.calls == []
    assert root["attributes"]["error.type"] == "InputValidationError"
    assert root["events"][0]["attributes"] == {
        "input_validation.result": "failed",
        "input_validation.failed_rules": ["pattern"],
    }
    assert root["attributes"]["usage.status"] == "no_requests"
    assert (root["attributes"]["usage.input_tokens"], root["attributes"]["usage.output_tokens"]) == (0, 0)
    assert root["attributes"]["cost.status"] == "no_requests"
    assert root["attributes"]["cost.estimated"] == "0"


def test_invalid_output_then_retry_success():
    adapter = FakeModelAdapter(scripted=["SECRET-OUTPUT-MARKER prose", VALID])
    result, _, records = traced(SAMPLE, adapter)
    assert result is not None
    assert_common(records, status="ok", used=2)
    first, second = requests_of(records)
    assert (first["status"], first["attributes"]["model_request.outcome"]) == ("error", "output_invalid")
    assert first["attributes"]["output_validation.failed_rules"] == ["strict_json"]
    assert first["attributes"]["error.type"] == "OutputValidationError"
    assert (second["status"], second["attributes"]["model_request.outcome"]) == ("ok", "output_valid")


def test_invalid_output_exhausting_budget():
    missing_fields = json.dumps({"headline": "SECRET-OUTPUT-MARKER"})
    _, error, records = traced(SAMPLE, FakeModelAdapter(scripted=["prose", missing_fields]))
    assert type(error).__name__ == "OutputValidationError"
    root = assert_common(records, status="error", used=2)
    assert root["attributes"]["error.type"] == "OutputValidationError"
    assert [r["attributes"]["model_request.outcome"] for r in requests_of(records)] == ["output_invalid"] * 2
    assert requests_of(records)[1]["attributes"]["output_validation.failed_rules"] == ["required"]


def test_adapter_exception_records_class_name_only():
    adapter = FakeModelAdapter(scripted=[TimeoutError("SECRET-EXCEPTION-MARKER upstream detail")])
    _, error, records = traced(SAMPLE, adapter)
    assert type(error).__name__ == "ModelInvocationError"
    root = assert_common(records, status="error", used=1)
    [request] = requests_of(records)
    assert request["attributes"]["model_request.outcome"] == "adapter_error"
    assert request["attributes"]["error.type"] == "TimeoutError"
    assert request["attributes"]["adapter.reported_model"] is None
    assert request["attributes"]["usage.status"] == "unknown"  # no response; a provider may still have billed
    assert root["attributes"]["error.type"] == "ModelInvocationError"
    assert root["attributes"]["cost.status"] == "unknown"


def test_known_usage_and_pricing_produce_an_estimate():
    # Synthetic test evidence: 1200 input tokens at 0.50/M + 300 output tokens at 1.50/M.
    _, _, records = traced(SAMPLE, FakeModelAdapter(usage=Usage(1200, 300)), pricing=TEST_PRICING)
    root = assert_common(records, status="ok", used=1)
    assert root["attributes"]["usage.status"] == "known"
    assert (root["attributes"]["usage.input_tokens"], root["attributes"]["usage.output_tokens"]) == (1200, 300)
    assert root["attributes"]["cost.status"] == "estimated"
    assert root["attributes"]["cost.currency"] == "USD"
    assert root["attributes"]["cost.estimated"] == "0.0010500000"  # 0.0006 + 0.00045


def test_known_usage_across_retries_is_summed():
    adapter = FakeModelAdapter(scripted=[reply("prose", Usage(100, 10)), reply(VALID, Usage(200, 20))])
    _, _, records = traced(SAMPLE, adapter, pricing=TEST_PRICING)
    root = assert_common(records, status="ok", used=2)
    assert (root["attributes"]["usage.input_tokens"], root["attributes"]["usage.output_tokens"]) == (300, 30)
    # 300 * 0.50/M + 30 * 1.50/M = 0.000150 + 0.000045
    assert root["attributes"]["cost.estimated"] == "0.0001950000"


def test_partial_usage_never_becomes_a_total_or_cost():
    adapter = FakeModelAdapter(scripted=[reply("prose", Usage(100, 10)), reply(VALID)])
    _, _, records = traced(SAMPLE, adapter, pricing=TEST_PRICING)
    root = assert_common(records, status="ok", used=2)
    first, second = requests_of(records)
    assert first["attributes"]["cost.status"] == "estimated"  # per-request evidence is kept
    assert second["attributes"]["usage.status"] == "unknown"
    assert root["attributes"]["usage.status"] == "partial"
    assert root["attributes"]["usage.input_tokens"] is None
    assert root["attributes"]["usage.output_tokens"] is None
    assert root["attributes"]["cost.status"] == "unknown"
    assert root["attributes"]["cost.unknown_reason"] == "usage_partial"
    assert root["attributes"]["cost.estimated"] is None


@pytest.mark.parametrize("bad_usage", [Usage(-5, 10), Usage(True, 10), Usage(1.5, 10), {"input_tokens": 1}])
def test_invalid_usage_report_is_flagged_without_changing_outcome(bad_usage):
    result, error, records = traced(SAMPLE, FakeModelAdapter(scripted=[reply(VALID, bad_usage)]), pricing=TEST_PRICING)
    assert error is None and result is not None  # observability never changes the outcome
    root = assert_common(records, status="ok", used=1)
    assert root["attributes"]["usage.status"] == "invalid_reported"
    assert root["attributes"]["usage.input_tokens"] is None
    assert root["attributes"]["cost.status"] == "unknown"
    assert root["attributes"]["cost.unknown_reason"] == "invalid_usage"


def test_no_matching_price_means_unknown_cost_even_with_known_usage():
    _, _, records = traced(SAMPLE, FakeModelAdapter(usage=Usage(10, 10)), pricing=NO_PRICING)
    root = assert_common(records, status="ok", used=1)
    assert root["attributes"]["usage.status"] == "known"
    assert root["attributes"]["cost.status"] == "unknown"
    assert root["attributes"]["cost.unknown_reason"] == "no_pricing"


def test_price_requires_exact_reported_model_match():
    adapter = FakeModelAdapter(scripted=[reply(VALID, Usage(10, 10), model="fake-other")])
    _, _, records = traced(SAMPLE, adapter, pricing=TEST_PRICING)
    assert root_of(records)["attributes"]["cost.unknown_reason"] == "no_pricing"


# --- contract and safety ---------------------------------------------------------------


def test_untrusted_model_label_is_sanitized():
    adapter = FakeModelAdapter(scripted=[reply(VALID, model="SECRET-OUTPUT-MARKER with spaces")])
    _, _, records = traced(SAMPLE, adapter)
    assert requests_of(records)[0]["attributes"]["adapter.reported_model"] == "unrecognized"
    assert safe_model_label("model-1.0") == "model-1.0"


def test_every_record_validates_and_config_failures_are_traced():
    _, error, records = traced(SAMPLE, FakeModelAdapter(), tools=("search_docs",))
    assert isinstance(error, ManifestError)
    root = assert_common(records, status="error", used=0)
    assert root["attributes"]["error.type"] == "ManifestError"


def _root_span_with(extra: dict) -> list[dict]:
    """A root span that is valid except for `extra`, so only `extra` can fail it."""
    sink = InMemorySink()
    telemetry = Telemetry(sink, correlation_id="c", clock=FakeClock(), new_trace_id=lambda: "t")
    with telemetry.span("capability.run") as span:
        span.set("model_requests.used", 0)
        span.set_all(run_attributes([], None))
        span.set_all(extra)
    return sink.records


def test_baseline_root_span_is_valid():
    assert len(_root_span_with({})) == 1


@pytest.mark.parametrize(
    "extra",
    [
        {"change.title": "not allowed"},
        {"metadata": {"anything": "goes"}},
        {"labels": {"team": "x"}},
        {"custom.attributes": "free text"},
        {"input.summary": "free text"},
        {"exception.message": "free text"},
    ],
    ids=["unknown-key", "metadata-map", "labels-map", "custom-attributes", "input-summary", "exception-message"],
)
def test_attributes_outside_the_allowlist_are_rejected(extra):
    with pytest.raises(TelemetryContractError):
        _root_span_with(extra)


@pytest.mark.parametrize("bad", ["has space", "line\nbreak", "", "x" * 129])
def test_invalid_correlation_id_is_rejected(bad):
    with pytest.raises(TelemetryContractError):
        Telemetry(InMemorySink(), correlation_id=bad)


def test_latency_is_observed_not_enforced():
    result, error, records = traced(SAMPLE, FakeModelAdapter(), max_latency_ms=1)
    assert error is None and result is not None  # measurement != enforcement
    assert root_of(records)["attributes"]["latency.over_declared_max"] is True


def test_delivery_failure_never_retries_or_fails_the_capability():
    stream = io.StringIO()
    stream.close()  # every write now raises
    telemetry = Telemetry(JsonlSink(stream), correlation_id="c", clock=FakeClock(), new_trace_id=lambda: "t")
    adapter = FakeModelAdapter()
    result = asyncio.run(run(SAMPLE, adapter=adapter, pricing=NO_PRICING, telemetry=telemetry))
    assert result.output["headline"].startswith("CHG-1042")
    assert len(adapter.calls) == 1  # no retry caused by telemetry
    assert len(telemetry.delivery_failures) == 2  # model_request span + root span


def test_records_are_deterministic_with_injected_clock_and_ids():
    first = traced(SAMPLE, FakeModelAdapter())[2]
    second = traced(SAMPLE, FakeModelAdapter())[2]
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


# --- pricing file ------------------------------------------------------------------------


def test_template_pricing_has_no_prices():
    assert load_pricing() == Pricing(currency="USD", prices=())


@pytest.mark.parametrize(
    "prices",
    [
        '[{adapter: fake, model: m, input_per_million_tokens: 0.5, output_per_million_tokens: "1"}]',  # YAML float
        '[{adapter: fake, model: m, input_per_million_tokens: "-1", output_per_million_tokens: "1"}]',
        '[{adapter: fake, model: m, input_per_million_tokens: "1", output_per_million_tokens: "1"},'
        ' {adapter: fake, model: m, input_per_million_tokens: "2", output_per_million_tokens: "2"}]',
    ],
    ids=["float-price", "negative-price", "duplicate-entry"],
)
def test_malformed_pricing_fails_closed(tmp_path, prices):
    (tmp_path / "platform").mkdir()
    (tmp_path / "platform" / "pricing.schema.json").write_bytes((ROOT / "platform" / "pricing.schema.json").read_bytes())
    (tmp_path / "pricing.yaml").write_text(f"api_version: ai.platform/v1\nkind: Pricing\ncurrency: USD\nprices: {prices}\n")
    with pytest.raises(ManifestError):
        load_pricing(tmp_path)
