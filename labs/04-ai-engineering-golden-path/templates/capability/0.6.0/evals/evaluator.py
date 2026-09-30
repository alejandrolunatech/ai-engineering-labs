"""Deterministic eval runner for this capability.

Run from the project root:

    python evals/evaluator.py [--correlation-id ID] [--telemetry-file PATH]

stdout: the EvalReport (JSON). It is byte-for-byte deterministic: it contains
        no trace ids, correlation ids, latency, token usage or cost.
stderr: typed JSONL records only: {"record": "span"} telemetry for every case,
        {"record": "eval_summary"} and, on failure, {"record": "error"}.
        With --telemetry-file, span records go to that file instead.

Telemetry joins the report through eval.suite_sha256 + eval.case_id;
eval.run_id (the correlation id) groups the spans of one execution.

Exit codes (the exit code IS the eval gate):
    0  observed pass rate meets evaluation.required_pass_rate
    1  it does not
    2  command-line usage error
    3  malformed manifest, eval suite, pricing or configuration (no report)
    5  gate satisfied but some telemetry records could not be delivered

What this does:
- reads evaluation.suite and evaluation.required_pass_rate from capability.yaml;
- validates the suite against platform/eval-suite.schema.json;
- runs every case through the real runtime (capability.run), never a copy of it;
- applies only deterministic, named checks. There is no model judge, and the
  substring checks are lexical, not semantic;
- prints a report with no timestamps, durations, identifiers, absolute paths,
  raw model output or error messages, so the same inputs give identical bytes.

Eval case data is evidence: a case's model_script is replayed exactly as
written. The evaluator never pads, repeats or rewrites it.

A passing gate means the declared expectations in this finite synthetic suite
were met by the configured adapter. It is not a measure of accuracy.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from dataclasses import replace
from fractions import Fraction
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# This project is not packaged, so the runtime is imported from src/ directly.
if str(PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "src"))

from capability import resolve_adapter, run  # noqa: E402
from contracts import (  # noqa: E402
    CapabilityError,
    Manifest,
    ManifestError,
    OutputValidationError,
    describe_errors,
    load_manifest,
    load_yaml_strict,
    parse_json_strict,
    validate_output,
)
from cost import Pricing, load_pricing  # noqa: E402
from model_adapter import FakeModelAdapter  # noqa: E402
from telemetry import (  # noqa: E402
    JsonlSink,
    NullSink,
    Sink,
    Telemetry,
    is_valid_identifier,
    new_identifier,
)

SUITE_SCHEMA_FILE = "platform/eval-suite.schema.json"
REPORT_SCHEMA_FILE = "platform/eval-report.schema.json"

EXPECTED_RESULT = {
    "expect_success": "succeeded",
    "expect_input_rejected": "InputValidationError",
    "expect_output_rejected": "OutputValidationError",
}


class EvalSuiteError(ManifestError):
    """The eval suite is missing, malformed or ambiguous. Exit code 3."""


def _load_platform_schema(root: Path, relative: str) -> dict:
    try:
        return parse_json_strict((root / relative).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise EvalSuiteError(f"cannot load {relative}: {type(exc).__name__}") from None


def load_suite(root: Path, manifest: Manifest) -> tuple[dict, bytes]:
    path = (root / manifest.eval_suite_path).resolve()
    if not path.is_relative_to(root.resolve()):
        raise EvalSuiteError(f"{manifest.eval_suite_path} resolves outside the project root")
    try:
        raw = path.read_bytes()
        suite = load_yaml_strict(raw.decode("utf-8"))
    except Exception as exc:  # OSError, UnicodeDecodeError, YAMLError
        raise EvalSuiteError(f"cannot load {manifest.eval_suite_path}: {type(exc).__name__}") from None

    problems = describe_errors(_load_platform_schema(root, SUITE_SCHEMA_FILE), suite)
    if problems:
        raise EvalSuiteError(f"{manifest.eval_suite_path} violates {SUITE_SCHEMA_FILE}: {problems}")

    ids = [case["id"] for case in suite["cases"]]
    duplicates = sorted({case_id for case_id in ids if ids.count(case_id) > 1})
    if duplicates:
        raise EvalSuiteError(f"{manifest.eval_suite_path} has duplicate case ids: {duplicates}")
    return suite, raw


def _check(name: str, expected: Any, passed: bool, **details: Any) -> dict:
    return {"name": name, "expected": expected, "passed": passed, **details}


def _output_checks(manifest: Manifest, expect: dict, output: dict) -> list[dict]:
    checks = []
    try:
        validate_output(manifest, json.dumps(output), model_requests_used=0)
        schema_valid = True
    except OutputValidationError:
        schema_valid = False
    checks.append(_check("output_schema_valid", True, schema_valid, observed=schema_valid))

    if "risk_level_in" in expect:
        observed = output["risk_level"]
        checks.append(
            _check("risk_level_in", expect["risk_level_in"], observed in expect["risk_level_in"], observed=observed)
        )
    if expect.get("open_questions", "any") != "any":
        count = len(output["open_questions"])
        wanted = expect["open_questions"]
        passed = count == 0 if wanted == "empty" else count > 0
        checks.append(_check("open_questions", wanted, passed, observed=count))
    if "headline_contains" in expect:
        missing = [s for s in expect["headline_contains"] if s not in output["headline"]]
        checks.append(_check("headline_contains", expect["headline_contains"], not missing, missing=missing))
    if "explanation_contains" in expect:
        text = output["explanation"].lower()
        missing = [s for s in expect["explanation_contains"] if s.lower() not in text]
        checks.append(_check("explanation_contains", expect["explanation_contains"], not missing, missing=missing))
    return checks


async def run_case(case: dict, manifest: Manifest, pricing: Pricing, telemetry: Telemetry) -> dict:
    kind = case["kind"]
    if kind == "expect_output_rejected":
        # Explicit dependency injection: a scripted fake replays exactly the
        # declared responses. It is recorded as "scripted", never as the
        # configured adapter.
        adapter = FakeModelAdapter(scripted=case["model_script"])
        case_manifest = replace(manifest, adapter=adapter.name)
        source = "scripted"
    else:
        adapter = resolve_adapter(manifest)
        case_manifest = manifest
        source = "manifest"

    output = None
    reported_model = None
    try:
        result = await run(
            case["input"], manifest=case_manifest, adapter=adapter, pricing=pricing, telemetry=telemetry
        )
        observed_result = "succeeded"
        used = result.model_requests["used"]
        output = result.output
        reported_model = result.model["adapter_reported"]["model"]
    except ManifestError:
        raise  # configuration problem (e.g. declared tools): abort the run, exit 3
    except CapabilityError as exc:
        observed_result = type(exc).__name__
        used = exc.model_requests_used
    except Exception as exc:  # a bug, not a declared boundary: fail the case, keep going
        observed_result = f"unexpected_error:{type(exc).__name__}"
        used = None

    limit = manifest.max_model_requests
    expected_result = EXPECTED_RESULT[kind]
    checks = [
        _check("outcome", expected_result, observed_result == expected_result, observed=observed_result),
        _check(
            "within_request_budget",
            {"max": limit},
            used is not None and used <= limit,
            observed=used,
        ),
    ]
    if kind == "expect_success" and output is not None:
        checks.extend(_output_checks(manifest, case["expect"], output))
    elif kind == "expect_input_rejected":
        checks.append(_check("no_model_request", 0, used == 0, observed=used))
    elif kind == "expect_output_rejected":
        checks.append(_check("budget_exhausted_not_exceeded", limit, used == limit, observed=used))

    return {
        "id": case["id"],
        "kind": kind,
        "property": case["property"],
        "adapter": {"source": source, "reported_model": reported_model},
        "outcome": {"result": observed_result, "model_requests_used": used},
        "checks": checks,
        "passed": all(check["passed"] for check in checks),
    }


def gate_passed(passed: int, total: int, required_pass_rate: float) -> bool:
    """Exact comparison. Float math can misjudge boundaries: 0.07 * 100 == 7.000000000000001,
    so a naive `passed >= ceil(rate * total)` would wrongly fail 7/100 at 0.07."""
    return Fraction(passed, total) >= Fraction(str(required_pass_rate))


async def _run_cases(
    cases: list[dict], manifest: Manifest, pricing: Pricing, telemetries: list[Telemetry]
) -> list[dict]:
    return [await run_case(case, manifest, pricing, tel) for case, tel in zip(cases, telemetries)]


def evaluate(root: Path = PROJECT_ROOT, *, sink: Sink | None = None, correlation_id: str | None = None) -> dict:
    """Run the suite and return the deterministic EvalReport.

    Telemetry (one trace per case) goes to `sink`; with no sink, records are
    validated and discarded. Nothing telemetry-related enters the report.
    """
    return _evaluate(root, sink or NullSink(), correlation_id or new_identifier())[0]


def _evaluate(root: Path, sink: Sink, run_id: str) -> tuple[dict, int]:
    """Returns (report, number of telemetry records that could not be delivered)."""
    manifest = load_manifest(root)
    pricing = load_pricing(root)
    suite, raw = load_suite(root, manifest)
    suite_sha256 = hashlib.sha256(raw).hexdigest()
    telemetries = [
        Telemetry(
            sink,
            correlation_id=run_id,
            base_attributes={
                "eval.run_id": run_id,
                "eval.case_id": case["id"],
                "eval.suite_sha256": suite_sha256,
                "eval.adapter_source": "scripted" if case["kind"] == "expect_output_rejected" else "manifest",
            },
            root=root,
        )
        for case in suite["cases"]
    ]
    results = asyncio.run(_run_cases(suite["cases"], manifest, pricing, telemetries))

    total = len(results)
    passed = sum(1 for case in results if case["passed"])
    report = {
        "api_version": "ai.platform/v1",
        "kind": "EvalReport",
        "capability": {
            "name": manifest.name,
            "version": manifest.version,
            "template_version": manifest.template_version,
        },
        "suite": {"path": manifest.eval_suite_path, "sha256": suite_sha256},
        "evaluator": {"checks": "deterministic", "model_judge": "none"},
        "model": {"declared_adapter": manifest.adapter, "declared_profile": manifest.profile},
        "cases": results,
        "summary": {
            "total": total,
            "passed": passed,
            "failed": total - passed,
            "observed_pass_rate": passed / total,
            "required_pass_rate": manifest.required_pass_rate,
            "gate_passed": gate_passed(passed, total, manifest.required_pass_rate),
        },
    }

    problems = describe_errors(_load_platform_schema(root, REPORT_SCHEMA_FILE), report)
    if problems:
        raise EvalSuiteError(f"report violates {REPORT_SCHEMA_FILE}: {problems}")
    return report, sum(len(t.delivery_failures) for t in telemetries)


def render_report(report: dict) -> str:
    return json.dumps(report, indent=2, sort_keys=True) + "\n"


TELEMETRY_DELIVERY_EXIT_CODE = 5


def _stderr_record(record: dict) -> None:
    print(json.dumps(record, sort_keys=True), file=sys.stderr)


def main(argv: list[str] | None = None, root: Path = PROJECT_ROOT) -> int:
    parser = argparse.ArgumentParser(prog="evaluator.py", description="Run this capability's eval suite.")
    parser.add_argument("--correlation-id", help="eval.run_id for this execution; generated when absent")
    parser.add_argument("--telemetry-file", type=Path, help="append span records (JSONL) here instead of stderr")
    args = parser.parse_args(argv)
    if args.correlation_id is not None and not is_valid_identifier(args.correlation_id):
        parser.error("--correlation-id must match [A-Za-z0-9._:-]{1,128}")
    run_id = args.correlation_id or new_identifier()

    stream = sys.stderr
    if args.telemetry_file is not None:
        try:
            stream = args.telemetry_file.open("a", encoding="utf-8")
        except OSError as exc:
            _stderr_record(
                {"record": "error", "error": "TelemetryDeliveryError", "message": f"cannot open telemetry file: {type(exc).__name__}"}
            )
            return TELEMETRY_DELIVERY_EXIT_CODE

    try:
        report, undelivered = _evaluate(root, JsonlSink(stream), run_id)
    except CapabilityError as exc:
        _stderr_record({"record": "error", "error": type(exc).__name__, "message": str(exc)})
        return exc.exit_code
    finally:
        if stream is not sys.stderr:
            stream.close()

    sys.stdout.write(render_report(report))
    summary = report["summary"]
    _stderr_record({"record": "eval_summary", "eval.run_id": run_id, **summary})
    exit_code = 0 if summary["gate_passed"] else 1
    if undelivered:
        # The eval outcome above stands; only the telemetry evidence is incomplete.
        _stderr_record(
            {"record": "error", "error": "TelemetryDeliveryError", "message": f"{undelivered} telemetry record(s) not delivered"}
        )
        return exit_code or TELEMETRY_DELIVERY_EXIT_CODE
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
