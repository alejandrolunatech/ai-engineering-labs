"""Phase 7: platform tests for `ai-capability verify` in the current template.

Every verification here is REAL: the generated verifier runs in a subprocess
(golden_path import-blocked), running the generated project's own pytest
suite and evaluator. Reports are validated against the CANONICAL
verification-report schema, not only the project's local snapshot.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator

from golden_path import scaffold

CAPABILITY = "verified-demo"
CHECK_IDS = [
    "manifest.parse",
    "provenance.platform_snapshots",
    "manifest.schema",
    "provenance.template_version",
    "schemas.input",
    "schemas.output",
    "eval.suite",
    "pricing.contract",
    "budgets.contract",
    "observability.contract",
    "ci.workflow",
    "authority.declared_tools",
    "tests.gate",
    "eval.gate",
]
CANONICAL_REPORT_SCHEMA = json.loads((scaffold.LAB_ROOT / "schemas" / "verification-report.schema.json").read_text())
WORKFLOW = ".github/workflows/ai-capability-verify.yml"
DOCUMENTED_SETUP = [
    "python -m pip install -r requirements.txt",
    "python -m pip install -e . --no-deps --no-build-isolation",
    "ai-capability verify",
]


def new_project(tmp_path: Path) -> Path:
    destination, _ = scaffold.new_capability(CAPABILITY, tmp_path)
    return destination


def verify(project: Path, env: dict, **extra_env) -> tuple[int, dict | None, str]:
    """Runs the SAME entry point as the console script: ai_capability.main."""
    completed = subprocess.run(
        [sys.executable, "verifier/ai_capability.py", "verify"],
        cwd=project,
        env={**env, **extra_env},
        capture_output=True,
        text=True,
        check=False,
    )
    report = json.loads(completed.stdout) if completed.stdout else None
    if report is not None:
        assert list(Draft202012Validator(CANONICAL_REPORT_SCHEMA).iter_errors(report)) == []
        assert [c["id"] for c in report["checks"]] == CHECK_IDS
    return completed.returncode, report, completed.stderr


def by_id(report: dict) -> dict:
    return {c["id"]: c for c in report["checks"]}


@pytest.fixture(scope="module")
def baseline(tmp_path_factory, blocked_env):
    project = new_project(tmp_path_factory.mktemp("baseline"))
    return project, verify(project, blocked_env)


# --- baseline, determinism, independence ------------------------------------------------------


def test_fresh_capability_verifies_green(baseline):
    project, (code, report, stderr) = baseline
    assert code == 0, stderr
    assert report["result"] == {"passed": True, "total": 14, "pass": 14, "fail": 0, "skipped": 0}
    assert report["capability"]["template_version"] == scaffold.TEMPLATE_VERSION == "0.6.0"
    assert report["verifier"] == {"version": "0.6.0"}
    assert report["evidence"]["tests"]["outcome"] == "passed" and report["evidence"]["tests"]["tests"] > 0
    assert report["evidence"]["eval"]["gate_passed"] is True
    assert "ai-capability verify: PASSED" in stderr


def test_report_is_byte_identical_across_runs_and_hash_seeds(baseline, blocked_env):
    project, (_, report, _) = baseline
    first = subprocess.run([sys.executable, "verifier/ai_capability.py", "verify"], cwd=project,
                           env={**blocked_env, "PYTHONHASHSEED": "0"}, capture_output=True, text=True)
    second = subprocess.run([sys.executable, "verifier/ai_capability.py", "verify"], cwd=project,
                            env={**blocked_env, "PYTHONHASHSEED": "1"}, capture_output=True, text=True)
    assert first.stdout == second.stdout
    assert json.loads(first.stdout) == report


def test_report_has_no_nondeterministic_or_machine_values(baseline):
    project, (_, report, _) = baseline
    text = json.dumps(report)
    for value in (str(project), str(Path.home()), str(scaffold.LAB_ROOT), "/tmp", "/var/folders"):
        assert value not in text
    assert not re.search(r"\d{4}-\d{2}-\d{2}", text)
    assert not re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-", text)
    for key in ('"duration', '"time', '"timestamp', '"correlation', '"trace', "stdout", "stderr"):
        assert key not in text


def test_verifier_is_independent_of_golden_path_and_product_runtime(baseline):
    project, _ = baseline
    tree = ast.parse((project / "verifier" / "ai_capability.py").read_text())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert imported <= set(sys.stdlib_module_names) | {"yaml", "jsonschema"}
    assert not imported & {"golden_path", "capability", "contracts", "tools", "policy", "telemetry", "cost",
                           "model_adapter", "evaluator"}


def test_embedded_released_hashes_match_canonical_contracts(baseline, blocked_env):
    project, _ = baseline
    probe = "import json, sys; sys.path.insert(0, 'verifier'); import ai_capability as a; print(json.dumps(a.RELEASED_SNAPSHOTS))"
    completed = subprocess.run([sys.executable, "-c", probe], cwd=project, env=blocked_env, capture_output=True, text=True)
    embedded = json.loads(completed.stdout)
    canonical = {out: hashlib.sha256(src.read_bytes()).hexdigest()
                 for out, src in scaffold.PLATFORM_FILES_BY_TEMPLATE_VERSION["0.6.0"].items()}
    assert embedded == canonical


def test_nested_verification_is_refused(baseline, blocked_env):
    project, _ = baseline
    code, report, stderr = verify(project, blocked_env, AI_CAPABILITY_VERIFY_ACTIVE="1")
    assert (code, report) == (3, None)
    assert "refusing nested verification" in stderr


# --- packaging: only the verifier becomes a command ----------------------------------------------


def test_only_the_verifier_module_is_installable(baseline):
    project, _ = baseline
    pyproject = tomllib.loads((project / "pyproject.toml").read_text())
    assert pyproject["project"]["scripts"] == {"ai-capability": "ai_capability:main"}
    assert pyproject["tool"]["setuptools"] == {"package-dir": {"": "verifier"}, "py-modules": ["ai_capability"]}
    assert pyproject["project"]["dependencies"] == []
    assert pyproject["project"]["name"] == CAPABILITY and pyproject["project"]["version"] == "0.0.0"
    assert pyproject["build-system"]["requires"] == ["setuptools>=70.1"]
    requirements = (project / "requirements.txt").read_text()
    assert "setuptools>=70.1" in requirements  # build backend declared: no hidden fetch
    assert sorted(p.name for p in (project / "verifier").iterdir()) == ["ai_capability.py"]


# --- workflow structure (GitHub Actions is not executed locally) ------------------------------------


def test_workflow_is_transport_only_and_runs_the_same_command(baseline):
    project, _ = baseline
    workflow = yaml.load((project / WORKFLOW).read_text(), Loader=yaml.BaseLoader)  # keeps `on` a string
    assert set(workflow) == {"name", "on", "permissions", "jobs"}
    assert set(workflow["on"]) == {"push", "pull_request", "workflow_dispatch"}
    assert workflow["permissions"] == {"contents": "read"}
    [job] = workflow["jobs"].values()
    uses = [s["uses"] for s in job["steps"] if "uses" in s]
    runs = [s["run"] for s in job["steps"] if "run" in s]
    assert uses == ["actions/checkout@v4", "actions/setup-python@v5"]
    assert job["steps"][0]["with"] == {"persist-credentials": "false"}
    assert job["steps"][1]["with"] == {"python-version": "3.12"}
    assert runs == DOCUMENTED_SETUP  # identical to the documented local sequence
    text = (project / WORKFLOW).read_text().lower()
    step_text = "\n".join(runs).lower()
    for token in ("pytest", "evaluator", "jsonschema", "check_schema", "tool_registry", "secrets."):
        assert token not in step_text
    assert "secrets." not in text and "deploy" not in step_text


def test_readme_documents_the_same_setup_and_command(baseline):
    project, _ = baseline
    readme = (project / "README.md").read_text()
    for command in DOCUMENTED_SETUP:
        assert command in readme


def test_pyyaml_on_key_pitfall_is_handled_by_the_verifier(baseline, blocked_env):
    project, _ = baseline
    text = (project / WORKFLOW).read_text()
    assert True in yaml.safe_load(text)  # plain PyYAML turns `on:` into True
    probe = (
        "import json, sys; sys.path.insert(0, 'verifier'); import ai_capability as a;"
        f"w = a.load_workflow_yaml(open({WORKFLOW!r}).read()); print(json.dumps(sorted(map(str, w))))"
    )
    completed = subprocess.run([sys.executable, "-c", probe], cwd=project, env=blocked_env, capture_output=True, text=True)
    assert json.loads(completed.stdout) == ["jobs", "name", "on", "permissions"]


# --- mutation matrix: every broken state fails the named check ---------------------------------------


def _edit(path: Path, old: str, new: str) -> None:
    text = path.read_text()
    assert old in text, old
    path.write_text(text.replace(old, new, 1))


def _drop_rejection_cases(project: Path) -> None:
    path = project / "evals" / "cases.yaml"
    suite = yaml.safe_load(path.read_text())
    suite["cases"] = [c for c in suite["cases"] if c["kind"] == "expect_success"]
    path.write_text(yaml.safe_dump(suite, sort_keys=False))


def _add_authors_case(project: Path) -> None:
    path = project / "evals" / "cases.yaml"
    suite = yaml.safe_load(path.read_text())
    suite["cases"].append({
        "id": "docs-only-authors-update", "kind": "expect_success",
        "property": "A documentation-only change to AUTHORS is not classified as high risk.",
        "input": {"change_id": "CHG-2009", "title": "Update AUTHORS", "summary": "Adds a contributor name to AUTHORS.",
                  "files_changed": ["AUTHORS.md"]},
        "expect": {"risk_level_in": ["low"]},
    })
    path.write_text(yaml.safe_dump(suite, sort_keys=False))


def _symlink_input_outside(project: Path) -> None:
    outside = project.parent / "outside.schema.json"
    outside.write_text('{"type": "object"}')
    target = project / "schemas" / "input.schema.json"
    target.unlink()
    target.symlink_to(outside)


MUTATIONS = {
    "yaml-syntax": (lambda p: (p / "capability.yaml").write_text("api_version: [unclosed\n"),
                    {"manifest.parse": ("fail", "unparseable"), "manifest.schema": ("skipped", "prerequisite_failed"),
                     "ci.workflow": ("pass", None)}),
    "schema-unknown-field": (lambda p: _edit(p / "capability.yaml", "kind: Capability", "kind: Capability\nextra: 1"),
                             {"manifest.schema": ("fail", "schema_violation"), "eval.gate": ("skipped", "prerequisite_failed")}),
    "input-schema-missing": (lambda p: (p / "schemas" / "input.schema.json").unlink(),
                             {"schemas.input": ("fail", "missing"), "eval.gate": ("skipped", "prerequisite_failed")}),
    "output-schema-malformed": (lambda p: (p / "schemas" / "output.schema.json").write_text("{not json"),
                                {"schemas.output": ("fail", "unparseable")}),
    "path-escape-symlink": (_symlink_input_outside, {"schemas.input": ("fail", "path_escape")}),
    "template-version-mismatch": (lambda p: _edit(p / "capability.yaml", 'template_version: "0.6.0"', 'template_version: "0.5.0"'),
                                  {"provenance.template_version": ("fail", "version_mismatch"), "manifest.schema": ("pass", None)}),
    "snapshot-tampered": (lambda p: _edit(p / "platform" / "pricing.schema.json", '"maxItems": 100', '"maxItems": 101'),
                          {"provenance.platform_snapshots": ("fail", "hash_mismatch"), "pricing.contract": ("skipped", "prerequisite_failed")}),
    "tool-unregistered": (lambda p: _edit(p / "capability.yaml", "    tools: []", "    tools: [search_docs]"),
                          {"authority.declared_tools": ("fail", "unregistered_tools"),
                           "eval.gate": ("skipped", "prerequisite_failed")}),
    "budget-out-of-contract": (lambda p: _edit(p / "capability.yaml", "max_model_requests: 2", "max_model_requests: 11"),
                               {"manifest.schema": ("fail", "schema_violation"), "budgets.contract": ("fail", "schema_violation")}),
    "tracing-disabled": (lambda p: _edit(p / "capability.yaml", "tracing: true", "tracing: false"),
                         {"observability.contract": ("fail", "schema_violation")}),
    "pytest-failure": (lambda p: (p / "tests" / "test_intentional_failure.py").write_text("def test_intentional_failure_marker():\n    assert False\n"),
                       {"tests.gate": ("fail", "tests_failed"), "eval.gate": ("pass", None)}),
    "eval-threshold": (_add_authors_case, {"eval.gate": ("fail", "gate_not_met"), "tests.gate": ("pass", None)}),
    "eval-suite-malformed": (_drop_rejection_cases, {"eval.suite": ("fail", "schema_violation"), "eval.gate": ("skipped", "prerequisite_failed")}),
    "pricing-missing": (lambda p: (p / "pricing.yaml").unlink(), {"pricing.contract": ("fail", "missing")}),
    "workflow-runs-pytest": (lambda p: _edit(p / WORKFLOW, "      - run: ai-capability verify", "      - run: python -m pytest\n      - run: ai-capability verify"),
                             {"ci.workflow": ("fail", "workflow_duplicates_verifier")}),
    # Trust in contract snapshots must come BEFORE contract-derived results.
    "capability-contract-weakened": (
        lambda p: (_edit(p / "platform" / "capability.schema.json", '"maximum": 10', '"maximum": 1000'),
                   _edit(p / "capability.yaml", "max_model_requests: 2", "max_model_requests: 500")),
        {"provenance.platform_snapshots": ("fail", "hash_mismatch"), "manifest.schema": ("skipped", "prerequisite_failed"),
         "budgets.contract": ("skipped", "prerequisite_failed")}),
    "eval-suite-contract-tampered": (
        lambda p: _edit(p / "platform" / "eval-suite.schema.json", '"minItems": 2', '"minItems": 1'),
        {"provenance.platform_snapshots": ("fail", "hash_mismatch"), "eval.suite": ("skipped", "prerequisite_failed"),
         "manifest.schema": ("pass", None)}),
    "report-contract-tampered": (
        lambda p: _edit(p / "platform" / "verification-report.schema.json", '"minItems": 14', '"minItems": 1'),
        {"provenance.platform_snapshots": ("fail", "hash_mismatch")}),
}


@pytest.mark.parametrize("name", list(MUTATIONS))
def test_mutation_fails_the_named_check(tmp_path, blocked_env, name):
    mutate, expected = MUTATIONS[name]
    project = new_project(tmp_path)
    mutate(project)
    code, report, stderr = verify(project, blocked_env)
    assert code == 1, stderr
    assert report["result"]["passed"] is False
    checks = by_id(report)
    for check_id, (status, reason) in expected.items():
        assert (checks[check_id]["status"], checks[check_id]["reason"]) == (status, reason), check_id
    for check in report["checks"]:  # every skip names a prerequisite that did not pass
        if check["status"] == "skipped":
            assert check["prerequisites"] and all(checks[p]["status"] != "pass" for p in check["prerequisites"])
    if name == "pytest-failure":
        assert report["evidence"]["tests"]["failures"] == 1
        assert "test_intentional_failure_marker" not in json.dumps(report)  # aggregates only
        assert "test_intentional_failure_marker" in stderr  # diagnostics stay on stderr
    if name == "tool-unregistered":
        assert "authority.declared_tools" in checks["eval.gate"]["prerequisites"]
        assert checks["tests.gate"]["status"] != "skipped"  # independent evidence still collected
        assert report["evidence"]["tests"]["tests"] > 0
        assert report["evidence"]["eval"]["gate_passed"] is None  # the evaluator never ran
        assert "search_docs" not in json.dumps(report) and "search_docs" in stderr
        reruns = [subprocess.run([sys.executable, "verifier/ai_capability.py", "verify"], cwd=project,
                                 env={**blocked_env, "PYTHONHASHSEED": seed}, capture_output=True)
                  for seed in ("0", "1")]
        assert [r.returncode for r in reruns] == [1, 1]
        assert reruns[0].stdout == reruns[1].stdout  # byte-identical
        assert json.loads(reruns[0].stdout) == report
    if name == "report-contract-tampered":
        assert report["report_schema_validation"] == "not_performed_untrusted_snapshot"
    if name == "budget-out-of-contract":
        assert report["evidence"]["budgets"]["max_model_requests"] is None
