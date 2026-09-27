"""Regression tests for the eval kit itself (evals/evaluator.py).

These prove that the evaluator interprets eval cases correctly and reports
deterministically. The product's behavioral expectations live in
evals/cases.yaml. The runtime's engineering boundaries are covered in
tests/test_capability.py.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest
import yaml

import evaluator
from contracts import describe_errors, parse_json_strict

ROOT = Path(__file__).resolve().parents[1]
REPORT_SCHEMA = parse_json_strict((ROOT / "platform" / "eval-report.schema.json").read_text())


@pytest.fixture
def project(tmp_path) -> Path:
    """A disposable copy of this project, for editing cases or the manifest."""
    copy = tmp_path / "project"
    shutil.copytree(ROOT, copy, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))
    return copy


def read_cases(root: Path) -> dict:
    return yaml.safe_load((root / "evals" / "cases.yaml").read_text())


def write_cases(root: Path, suite: dict) -> None:
    (root / "evals" / "cases.yaml").write_text(yaml.safe_dump(suite, sort_keys=False))


def case_by_id(report: dict, case_id: str) -> dict:
    return next(case for case in report["cases"] if case["id"] == case_id)


# --- the default suite ---------------------------------------------------------


def test_default_suite_passes_gate():
    report = evaluator.evaluate()
    failed = [case["id"] for case in report["cases"] if not case["passed"]]
    assert failed == []
    assert report["summary"]["gate_passed"] is True
    assert evaluator.main([]) == 0


def test_report_matches_platform_report_schema():
    assert describe_errors(REPORT_SCHEMA, evaluator.evaluate()) == ""


def test_report_is_byte_for_byte_deterministic():
    assert evaluator.render_report(evaluator.evaluate()) == evaluator.render_report(evaluator.evaluate())


def test_report_identifies_exact_suite_bytes():
    report = evaluator.evaluate()
    expected = hashlib.sha256((ROOT / "evals" / "cases.yaml").read_bytes()).hexdigest()
    assert report["suite"] == {"path": "evals/cases.yaml", "sha256": expected}


def test_case_order_follows_suite_file():
    assert [c["id"] for c in evaluator.evaluate()["cases"]] == [c["id"] for c in read_cases(ROOT)["cases"]]


def test_scripted_cases_are_never_reported_as_configured_adapter():
    for case in evaluator.evaluate()["cases"]:
        expected_source = "scripted" if case["kind"] == "expect_output_rejected" else "manifest"
        assert case["adapter"]["source"] == expected_source


def test_report_contains_no_raw_model_output():
    rendered = evaluator.render_report(evaluator.evaluate())
    # The fake's full headline for clear-change; only the expected substring may appear.
    assert "CHG-2001: Add CSV export" not in rendered
    assert "This change touches" not in rendered


# --- failures are reported, not hidden ------------------------------------------


def test_behavioral_mismatch_fails_case_and_gate(project, capsys):
    suite = read_cases(project)
    suite["cases"][0]["expect"]["risk_level_in"] = ["high"]  # clear-change is actually low
    write_cases(project, suite)
    report = evaluator.evaluate(project)
    case = case_by_id(report, "clear-change")
    assert case["passed"] is False
    assert {"name": "risk_level_in", "expected": ["high"], "observed": "low", "passed": False} in case["checks"]
    assert report["summary"]["gate_passed"] is False
    assert evaluator.main([], root=project) == 1


def test_negative_case_that_unexpectedly_succeeds_fails(project):
    suite = read_cases(project)
    bad_id_case = next(c for c in suite["cases"] if c["id"] == "reject-input-bad-change-id")
    bad_id_case["input"]["change_id"] = "CHG-2007"  # now valid, so no rejection happens
    write_cases(project, suite)
    case = case_by_id(evaluator.evaluate(project), "reject-input-bad-change-id")
    assert case["outcome"]["result"] == "succeeded"
    assert case["passed"] is False


def test_exhausted_model_script_surfaces_as_failure(project):
    suite = read_cases(project)
    scripted = next(c for c in suite["cases"] if c["kind"] == "expect_output_rejected")
    scripted["model_script"] = scripted["model_script"][:1]  # fewer responses than the budget
    write_cases(project, suite)
    case = case_by_id(evaluator.evaluate(project), scripted["id"])
    assert case["outcome"]["result"] == "ModelInvocationError"
    assert case["passed"] is False


def test_gate_below_threshold_but_satisfied_exits_0(project):
    suite = read_cases(project)
    suite["cases"][0]["expect"]["risk_level_in"] = ["high"]  # 1 of 8 fails -> 0.875
    write_cases(project, suite)
    manifest = project / "capability.yaml"
    manifest.write_text(manifest.read_text().replace("required_pass_rate: 1.0", "required_pass_rate: 0.875"))
    report = evaluator.evaluate(project)
    assert report["summary"]["observed_pass_rate"] == 0.875
    assert report["summary"]["gate_passed"] is True
    assert evaluator.main([], root=project) == 0


@pytest.mark.parametrize(
    ("passed", "total", "required", "expected"),
    [(7, 100, 0.07, True), (6, 100, 0.07, False), (7, 10, 0.7, True), (6, 10, 0.7, False), (1, 3, 0.3333, True), (9, 10, 1.0, False), (3, 3, 1.0, True)],
)
def test_gate_uses_exact_arithmetic(passed, total, required, expected):
    assert evaluator.gate_passed(passed, total, required) is expected


# --- malformed suites are configuration errors: exit 3, no report ----------------


def _drop_negative_cases(suite):
    suite["cases"] = [c for c in suite["cases"] if c["kind"] == "expect_success"]


def _duplicate_id(suite):
    suite["cases"][1]["id"] = suite["cases"][0]["id"]


def _missing_property(suite):
    del suite["cases"][0]["property"]


def _unknown_expectation(suite):
    suite["cases"][0]["expect"]["sounds_helpful"] = True


def _script_on_success_case(suite):
    suite["cases"][0]["model_script"] = ["{}"]


def _success_without_expectations(suite):
    del suite["cases"][0]["expect"]


@pytest.mark.parametrize(
    "corrupt",
    [
        _drop_negative_cases,
        _duplicate_id,
        _missing_property,
        _unknown_expectation,
        _script_on_success_case,
        _success_without_expectations,
    ],
    ids=lambda fn: fn.__name__.lstrip("_"),
)
def test_malformed_suite_exits_3_without_report(project, capsys, corrupt):
    suite = read_cases(project)
    corrupt(suite)
    write_cases(project, suite)
    assert evaluator.main([], root=project) == 3
    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err)["error"] == "EvalSuiteError"


def test_duplicate_yaml_keys_in_suite_exit_3(project, capsys):
    path = project / "evals" / "cases.yaml"
    path.write_text(path.read_text().replace("kind: EvalSuite", "kind: EvalSuite\nkind: EvalSuite"))
    assert evaluator.main([], root=project) == 3
    assert capsys.readouterr().out == ""


def test_missing_suite_file_exits_3(project, capsys):
    (project / "evals" / "cases.yaml").unlink()
    assert evaluator.main([], root=project) == 3
    assert capsys.readouterr().out == ""
