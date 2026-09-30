"""Tests for the verifier (verifier/ai_capability.py).

Every test verifies a disposable COPY of this project. The test gate is
always a fake runner: these tests run inside `ai-capability verify`'s own
pytest subprocess, and a real nested test gate would recurse. The evaluator
defaults to a canned, clearly fake EvalReport so these tests never depend on
whether the product's current eval cases pass (tests != evals). The real
evaluator and registry probe are used where a test needs them.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator

import ai_capability as ac

ROOT = Path(__file__).resolve().parents[1]
CHECK_IDS = [check_id for check_id, _ in ac.CHECKS]
REPORT_SCHEMA = json.loads((ROOT / "platform" / "verification-report.schema.json").read_text())
PASSING_TESTS = ac.TestRun("passed", tests=10, failures=0, errors=0, skipped=0)

# A canned EvalReport (FAKE runner output) that satisfies the eval-report contract.
CANNED_EVAL_REPORT = {
    "api_version": "ai.platform/v1",
    "kind": "EvalReport",
    "capability": {"name": "canned", "version": "0.0.0", "template_version": "0.6.0"},
    "suite": {"path": "evals/cases.yaml", "sha256": "0" * 64},
    "evaluator": {"checks": "deterministic", "model_judge": "none"},
    "model": {"declared_adapter": "fake", "declared_profile": "balanced"},
    "cases": [
        {
            "id": "canned-case",
            "kind": "expect_success",
            "property": "Canned fake evaluator output for verifier unit tests.",
            "adapter": {"source": "manifest", "reported_model": "canned"},
            "outcome": {"result": "succeeded", "model_requests_used": 1},
            "checks": [{"name": "outcome", "expected": "succeeded", "observed": "succeeded", "passed": True}],
            "passed": True,
        }
    ],
    "summary": {"total": 1, "passed": 1, "failed": 0, "observed_pass_rate": 1.0, "required_pass_rate": 1.0, "gate_passed": True},
}


@pytest.fixture(scope="module")
def passing_eval_stdout() -> str:
    return json.dumps(CANNED_EVAL_REPORT)


@pytest.fixture
def project(tmp_path) -> Path:
    copy = tmp_path / "project"
    shutil.copytree(
        ROOT, copy, ignore=shutil.ignore_patterns(".venv", ".git", "__pycache__", ".pytest_cache", "*.egg-info", "build")
    )
    return copy


@pytest.fixture
def runners(passing_eval_stdout):
    def make(tests=PASSING_TESTS, evaluator=None, registry=None):
        return ac.Runners(
            run_tests=lambda root: tests,
            run_evaluator=evaluator or (lambda root: ac.EvalRun(0, passing_eval_stdout)),
            inspect_registry=(lambda root: registry) if registry is not None else ac.inspect_registry,
        )

    return make


def run_verify(root: Path, runners) -> dict:
    report, _ = ac.verify(root, runners)
    return report


def check(report: dict, check_id: str) -> dict:
    return next(c for c in report["checks"] if c["id"] == check_id)


def edit(path: Path, old: str, new: str) -> None:
    text = path.read_text()
    assert old in text, old
    path.write_text(text.replace(old, new, 1))


# --- baseline ---------------------------------------------------------------------------


def test_generated_project_passes_all_14_checks_in_fixed_order(project, runners):
    report = run_verify(project, runners())
    assert [c["id"] for c in report["checks"]] == CHECK_IDS and len(CHECK_IDS) == 14
    assert report["result"] == {"passed": True, "total": 14, "pass": 14, "fail": 0, "skipped": 0}
    assert report["meaning"] == "declared_deterministic_checks_only"
    assert report["report_schema_validation"] == "trusted_snapshot"
    assert report["evidence"]["authority"]["runtime_authorization"] == "not_evaluated_by_verifier"
    assert report["evidence"]["observability"]["delivery_tested"] is False
    assert report["evidence"]["budgets"]["enforced_at_runtime"] == ["max_model_requests"]


def test_report_validates_and_is_byte_deterministic(project, runners):
    first = ac.render_report(run_verify(project, runners()))
    second = ac.render_report(run_verify(project, runners()))
    assert first == second
    assert list(Draft202012Validator(REPORT_SCHEMA).iter_errors(json.loads(first))) == []
    assert str(project) not in first


def test_a_skip_is_never_a_soft_pass():
    checks = [{"status": "pass"}] * 13 + [{"status": "skipped"}]
    assert ac.summarize(checks) == {"passed": False, "total": 14, "pass": 13, "fail": 0, "skipped": 1}
    assert ac.summarize([{"status": "pass"}] * 14)["passed"] is True


# --- manifest ------------------------------------------------------------------------------


def test_malformed_yaml_fails_parse_and_skips_dependents(project, runners):
    (project / "capability.yaml").write_text("api_version: [unclosed\n")
    report = run_verify(project, runners())
    assert check(report, "manifest.parse")["reason"] == "unparseable"
    for dependent in ("manifest.schema", "provenance.template_version", "schemas.input", "budgets.contract"):
        assert check(report, dependent)["status"] == "skipped"
        assert check(report, dependent)["prerequisites"] == ["manifest.parse"]
    assert check(report, "tests.gate")["status"] == "pass"  # independent evidence still collected
    assert check(report, "ci.workflow")["status"] == "pass"
    assert report["result"]["passed"] is False


def test_duplicate_manifest_key_fails_parse(project, runners):
    edit(project / "capability.yaml", "kind: Capability", "kind: Capability\nkind: Capability")
    assert check(run_verify(project, runners()), "manifest.parse")["reason"] == "unparseable"


def test_unknown_manifest_field_fails_schema_and_skips_eval_gate(project, runners):
    edit(project / "capability.yaml", "kind: Capability", "kind: Capability\nunexpected_field: 1")
    report = run_verify(project, runners())
    assert check(report, "manifest.schema")["failed_rules"] == ["additionalProperties"]
    assert "manifest.schema" in check(report, "eval.gate")["prerequisites"]
    assert report["capability"] == {"name": None, "version": None, "template_version": None}


def test_offending_values_are_never_echoed(project, runners):
    edit(project / "capability.yaml", "max_model_requests: 2", "max_model_requests: 987654")
    report = run_verify(project, runners())
    rendered = ac.render_report(report)
    assert "987654" not in rendered
    assert check(report, "manifest.schema")["locations"] == ["spec/budgets/max_model_requests"]
    assert check(report, "budgets.contract")["failed_rules"] == ["maximum"]
    assert report["evidence"]["budgets"]["max_model_requests"] is None  # not surfaced when invalid


def test_tracing_disabled_fails_observability_contract(project, runners):
    edit(project / "capability.yaml", "tracing: true", "tracing: false")
    report = run_verify(project, runners())
    assert check(report, "observability.contract")["reason"] == "schema_violation"
    assert check(report, "observability.contract")["failed_rules"] == ["const"]


def test_template_version_mismatch(project, runners):
    edit(project / "capability.yaml", 'template_version: "0.6.0"', 'template_version: "0.5.0"')
    report = run_verify(project, runners())
    assert check(report, "provenance.template_version")["reason"] == "version_mismatch"
    assert check(report, "manifest.schema")["status"] == "pass"  # the claim is schema-valid, just inconsistent


# --- referenced files ---------------------------------------------------------------------------


def test_missing_input_schema(project, runners):
    (project / "schemas" / "input.schema.json").unlink()
    report = run_verify(project, runners())
    assert (check(report, "schemas.input")["status"], check(report, "schemas.input")["reason"]) == ("fail", "missing")
    assert check(report, "eval.gate")["prerequisites"] == ["schemas.input"]


def test_malformed_output_schema(project, runners):
    (project / "schemas" / "output.schema.json").write_text("{not json")
    assert check(run_verify(project, runners()), "schemas.output")["reason"] == "unparseable"


def test_output_file_that_is_not_a_json_schema(project, runners):
    (project / "schemas" / "output.schema.json").write_text('{"type": 5}')
    assert check(run_verify(project, runners()), "schemas.output")["reason"] == "not_a_json_schema"


def test_symlink_escaping_the_project_root(project, runners, tmp_path):
    outside = tmp_path / "outside.schema.json"
    outside.write_text('{"type": "object"}')
    target = project / "schemas" / "input.schema.json"
    target.unlink()
    target.symlink_to(outside)
    assert check(run_verify(project, runners()), "schemas.input")["reason"] == "path_escape"


def test_missing_pricing_file(project, runners):
    (project / "pricing.yaml").unlink()
    report = run_verify(project, runners())
    assert check(report, "pricing.contract")["reason"] == "missing"
    assert check(report, "eval.gate")["prerequisites"] == ["pricing.contract"]


def test_malformed_eval_suite(project, runners):
    path = project / "evals" / "cases.yaml"
    suite = yaml.safe_load(path.read_text())
    suite["cases"] = [c for c in suite["cases"] if c["kind"] == "expect_success"]
    path.write_text(yaml.safe_dump(suite, sort_keys=False))
    report = run_verify(project, runners())
    assert check(report, "eval.suite")["failed_rules"] == ["contains"]
    assert check(report, "eval.gate")["status"] == "skipped"


# --- trust in contract snapshots comes BEFORE contract-derived results ------------------------------


def test_tampered_capability_contract_cannot_produce_a_pass(project, runners):
    # Weaken the snapshot so an invalid budget WOULD validate against it.
    edit(project / "platform" / "capability.schema.json", '"maximum": 10', '"maximum": 1000')
    edit(project / "capability.yaml", "max_model_requests: 2", "max_model_requests: 500")
    report = run_verify(project, runners())
    snapshots = check(report, "provenance.platform_snapshots")
    assert (snapshots["reason"], snapshots["locations"]) == ("hash_mismatch", ["platform/capability.schema.json"])
    for derived in ("manifest.schema", "budgets.contract", "observability.contract"):
        assert check(report, derived)["status"] == "skipped"
        assert check(report, derived)["prerequisites"] == ["provenance.platform_snapshots"]
    assert check(report, "eval.gate")["status"] == "skipped"
    assert report["evidence"]["budgets"]["max_model_requests"] is None
    assert report["result"]["passed"] is False


def test_tampered_eval_suite_contract_skips_only_what_depends_on_it(project, runners):
    edit(project / "platform" / "eval-suite.schema.json", '"minItems": 2', '"minItems": 1')
    report = run_verify(project, runners())
    assert check(report, "provenance.platform_snapshots")["locations"] == ["platform/eval-suite.schema.json"]
    assert check(report, "eval.suite")["status"] == "skipped"
    assert check(report, "manifest.schema")["status"] == "pass"  # its own contract is still trusted


def test_tampered_report_contract_disables_trusted_self_validation(project, runners):
    edit(project / "platform" / "verification-report.schema.json", '"minItems": 14', '"minItems": 1')
    report = run_verify(project, runners())
    assert report["report_schema_validation"] == "not_performed_untrusted_snapshot"
    assert check(report, "provenance.platform_snapshots")["locations"] == ["platform/verification-report.schema.json"]
    assert report["result"]["passed"] is False


def test_missing_snapshot(project, runners):
    (project / "platform" / "pricing.schema.json").unlink()
    report = run_verify(project, runners())
    assert check(report, "provenance.platform_snapshots")["reason"] == "missing"
    assert check(report, "pricing.contract")["status"] == "skipped"


# --- authority ---------------------------------------------------------------------------------------------


# Appended to a COPY's src/tools.py: once the registry is built, any call into
# src/ (model adapter, policy, tool executors, runtime) leaves a marker file.
TRIPWIRE = """
import sys as _sys
from pathlib import Path as _Path

_SRC = str(_Path(__file__).resolve().parent)
_MARKER = _Path(__file__).resolve().parents[1] / "EXECUTION_TRIPWIRE"


def _tripwire(frame, event, arg):
    if event == "call" and frame.f_code.co_filename.startswith(_SRC):
        _MARKER.write_text(frame.f_code.co_filename + ":" + frame.f_code.co_name)


_sys.setprofile(_tripwire)
"""


def arm_tripwire(project: Path) -> Path:
    with (project / "src" / "tools.py").open("a") as handle:
        handle.write(TRIPWIRE)
    return project / "EXECUTION_TRIPWIRE"


def spy_runners(passing_eval_stdout: str, calls: list[str]) -> ac.Runners:
    def run_tests(root):
        calls.append("tests")
        return PASSING_TESTS

    def run_evaluator(root):
        calls.append("evaluator")
        return ac.EvalRun(0, passing_eval_stdout)

    def inspect_registry(root):
        calls.append("registry")
        return ac.inspect_registry(root)  # the REAL subprocess probe

    return ac.Runners(run_tests=run_tests, run_evaluator=run_evaluator, inspect_registry=inspect_registry)


def test_unregistered_declared_tool_fails_without_running_anything(project, passing_eval_stdout):
    edit(project / "capability.yaml", "    tools: []", "    tools: [search_docs]")
    marker = arm_tripwire(project)
    calls: list[str] = []
    report, diagnostics = ac.verify(project, spy_runners(passing_eval_stdout, calls))

    authority = check(report, "authority.declared_tools")
    assert (authority["status"], authority["reason"]) == ("fail", "unregistered_tools")
    assert report["evidence"]["authority"]["unregistered_count"] == 1
    assert "search_docs" not in ac.render_report(report)
    assert any("search_docs" in d for d in diagnostics)  # human diagnostics only

    # The registry probe imported the trusted registry and executed nothing.
    assert not marker.exists(), marker.read_text()

    # tests.gate is independent evidence and still runs.
    assert check(report, "tests.gate")["status"] == "pass"
    assert report["evidence"]["tests"]["tests"] == PASSING_TESTS.tests

    # eval.gate is skipped, not an evaluator error: the evaluator never ran.
    eval_gate = check(report, "eval.gate")
    assert (eval_gate["status"], eval_gate["reason"]) == ("skipped", "prerequisite_failed")
    assert eval_gate["prerequisites"] == ["authority.declared_tools"]
    assert calls == ["registry", "tests"]
    assert report["result"]["passed"] is False


def test_execution_tripwire_is_not_vacuous(project):
    marker = arm_tripwire(project)
    probe = "import sys; sys.path.insert(0, 'src'); from tools import TOOL_REGISTRY; TOOL_REGISTRY['lookup_change_context'].spec()"
    subprocess.run([sys.executable, "-c", probe], cwd=project, env=ac._subprocess_env(), check=True)
    assert marker.exists()


def test_unregistered_tool_report_is_byte_deterministic(project, runners):
    edit(project / "capability.yaml", "    tools: []", "    tools: [search_docs]")
    first = ac.render_report(run_verify(project, runners()))
    second = ac.render_report(run_verify(project, runners()))
    assert first == second
    assert list(Draft202012Validator(REPORT_SCHEMA).iter_errors(json.loads(first))) == []


def test_high_impact_declaration_is_valid_but_not_authorized(project, runners):
    edit(project / "capability.yaml", "    tools: []", "    tools: [publish_change_notice]")
    report = run_verify(project, runners())
    assert check(report, "authority.declared_tools")["status"] == "pass"
    assert report["evidence"]["authority"]["declared_tools"] == [{"name": "publish_change_notice", "impact": "high"}]
    assert report["evidence"]["authority"]["runtime_authorization"] == "not_evaluated_by_verifier"


def test_registry_unavailable(project, runners):
    edit(project / "capability.yaml", "    tools: []", "    tools: [lookup_change_context]")
    broken = ac.Runners(run_tests=lambda r: PASSING_TESTS, run_evaluator=lambda r: ac.EvalRun(0, ""), inspect_registry=lambda r: None)
    assert check(run_verify(project, broken), "authority.declared_tools")["reason"] == "registry_unavailable"


# --- tests gate ---------------------------------------------------------------------------------------------


def test_failing_tests_report_aggregates_only(project, runners):
    failing = ac.TestRun("failed", tests=12, failures=1, errors=0, skipped=0,
                         diagnostic="FAILED tests/test_x.py::test_secret_node_id[param-A]")
    report, diagnostics = ac.verify(project, runners(tests=failing))
    assert check(report, "tests.gate")["reason"] == "tests_failed"
    assert report["evidence"]["tests"] == {"outcome": "failed", "tests": 12, "failures": 1, "errors": 0, "skipped": 0}
    assert "test_secret_node_id" not in ac.render_report(report)
    assert any("test_secret_node_id" in d for d in diagnostics)  # human diagnostics only


@pytest.mark.parametrize(
    ("outcome", "reason"), [("no_tests", "no_tests"), ("error", "tests_error"), ("timeout", "timeout")]
)
def test_other_test_outcomes(project, runners, outcome, reason):
    report = run_verify(project, runners(tests=ac.TestRun(outcome)))
    assert check(report, "tests.gate")["reason"] == reason


# --- eval gate ------------------------------------------------------------------------------------------------


def test_eval_threshold_failure_is_independent_of_tests(project, runners):
    path = project / "evals" / "cases.yaml"
    suite = yaml.safe_load(path.read_text())
    original_total = len(suite["cases"])
    suite["cases"].append({
        "id": "verifier-test-authors-regression", "kind": "expect_success",
        "property": "A documentation-only change to AUTHORS is not classified as high risk.",
        "input": {"change_id": "CHG-2009", "title": "Update AUTHORS", "summary": "Adds a contributor name to AUTHORS.",
                  "files_changed": ["AUTHORS.md"]},
        "expect": {"risk_level_in": ["low"]},
    })
    path.write_text(yaml.safe_dump(suite, sort_keys=False))
    real_evaluator = runners(evaluator=ac.run_evaluator)
    report = run_verify(project, real_evaluator)
    assert check(report, "tests.gate")["status"] == "pass"
    assert check(report, "eval.gate")["reason"] == "gate_not_met"
    assert (report["evidence"]["eval"]["gate_passed"], report["evidence"]["eval"]["total"]) == (False, original_total + 1)
    assert report["result"]["passed"] is False


@pytest.mark.parametrize(
    ("run", "reason"),
    [(ac.EvalRun(3, ""), "evaluator_error"), (ac.EvalRun(None), "timeout"), (ac.EvalRun(0, "not json"), "evaluator_error")],
    ids=["config-error", "timeout", "garbage-stdout"],
)
def test_evaluator_outcomes_are_translated_not_leaked(project, runners, run, reason):
    report = run_verify(project, runners(evaluator=lambda root: run))
    assert check(report, "eval.gate")["reason"] == reason


def test_evaluator_exit_code_contradicting_its_report_is_an_error(project, runners, passing_eval_stdout):
    report = run_verify(project, runners(evaluator=lambda root: ac.EvalRun(1, passing_eval_stdout)))
    assert check(report, "eval.gate")["reason"] == "evaluator_error"


# --- CI workflow ---------------------------------------------------------------------------------------------

WORKFLOW = Path(ac.WORKFLOW_FILE)


def test_workflow_on_key_survives_yaml_parsing():
    text = (ROOT / WORKFLOW).read_text()
    assert True in yaml.safe_load(text)  # the PyYAML 1.1 pitfall: `on:` becomes boolean True
    parsed = ac.load_workflow_yaml(text)
    assert "on" in parsed and True not in parsed
    assert set(parsed["on"]) == {"push", "pull_request", "workflow_dispatch"}


@pytest.mark.parametrize(
    ("old", "new", "reason"),
    [
        ("      - run: ai-capability verify", "      - run: python -m pytest\n      - run: ai-capability verify", "workflow_duplicates_verifier"),
        ("      - run: ai-capability verify", "      - run: python evals/evaluator.py\n      - run: ai-capability verify", "workflow_duplicates_verifier"),
        ("      - run: ai-capability verify", "      - run: echo skipped", "workflow_missing_verify"),
        ("permissions:\n  contents: read", "permissions: write-all", "workflow_permissions"),
        ("on:\n", "triggers:\n", "workflow_invalid"),
    ],
    ids=["runs-pytest", "runs-evaluator", "no-verify-step", "write-all", "no-on-key"],
)
def test_workflow_semantic_failures(project, runners, old, new, reason):
    edit(project / WORKFLOW, old, new)
    assert check(run_verify(project, runners()), "ci.workflow")["reason"] == reason


def test_unrelated_workflow_steps_are_allowed(project, runners):
    edit(project / WORKFLOW, "      - run: ai-capability verify", "      - run: python -m ruff check .\n      - run: ai-capability verify")
    assert check(run_verify(project, runners()), "ci.workflow")["status"] == "pass"


def test_missing_workflow(project, runners):
    (project / WORKFLOW).unlink()
    assert check(run_verify(project, runners()), "ci.workflow")["reason"] == "missing"


# --- command line ---------------------------------------------------------------------------------------------


def test_cli_stdout_is_only_the_report(project, runners, monkeypatch, capsys):
    monkeypatch.chdir(project)
    monkeypatch.delenv(ac.RECURSION_GUARD_ENV, raising=False)
    assert ac.main(["verify"], runners=runners()) == 0
    captured = capsys.readouterr()
    assert json.loads(captured.out)["kind"] == "VerificationReport"
    assert "ai-capability verify: PASSED" in captured.err


def test_cli_exit_1_on_failed_check(project, runners, monkeypatch, capsys):
    monkeypatch.chdir(project)
    monkeypatch.delenv(ac.RECURSION_GUARD_ENV, raising=False)
    (project / "pricing.yaml").unlink()
    assert ac.main(["verify"], runners=runners()) == 1


def test_cli_exit_1_on_unregistered_tool(project, runners, monkeypatch, capsys):
    monkeypatch.chdir(project)
    monkeypatch.delenv(ac.RECURSION_GUARD_ENV, raising=False)
    edit(project / "capability.yaml", "    tools: []", "    tools: [search_docs]")
    assert ac.main(["verify"], runners=runners()) == 1
    report = json.loads(capsys.readouterr().out)
    assert check(report, "eval.gate")["status"] == "skipped"


def test_cli_usage_error_is_exit_2():
    with pytest.raises(SystemExit) as exc:
        ac.main([])
    assert exc.value.code == 2


def test_recursion_guard_refuses_nested_verification(project, runners, monkeypatch):
    # Fake runners: if the guard were broken, this test fails fast (exit 0/1)
    # instead of really recursing verifier -> pytest -> verifier.
    monkeypatch.chdir(project)
    monkeypatch.setenv(ac.RECURSION_GUARD_ENV, "1")
    assert ac.main(["verify"], runners=runners()) == 3


def test_internal_failure_is_exit_3_without_report(project, monkeypatch, capsys):
    monkeypatch.chdir(project)
    monkeypatch.delenv(ac.RECURSION_GUARD_ENV, raising=False)

    def explode(root):
        raise RuntimeError("boom")

    broken = ac.Runners(run_tests=explode, run_evaluator=explode, inspect_registry=explode)
    assert ac.main(["verify"], runners=broken) == 3
    assert capsys.readouterr().out == ""
