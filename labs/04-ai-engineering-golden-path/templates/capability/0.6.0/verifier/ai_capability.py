"""ai-capability: the single verification command for this capability.

    ai-capability verify          (run from the capability root)

stdout: the VerificationReport (JSON). Identical capability state produces
        identical bytes: no timestamps, ids, paths, durations or raw output.
stderr: a concise human checklist plus diagnostics. Never part of the report.

Exit codes:
    0  every required check passed
    1  verification completed and one or more checks failed or were skipped
    2  command-line usage error
    3  the verifier could not construct trustworthy verification evidence

PLATFORM-MANAGED generated code (template 0.6.0). Local development and CI
run exactly this implementation; the CI workflow only invokes it.

Trust boundaries:
- This module imports no golden_path code and none of the capability's own
  runtime modules. Project code (tests, evaluator, tool registry) runs only in
  subprocesses.
- Platform contract snapshots are trusted only after their SHA-256 matches the
  released hash embedded below. A check derived from a snapshot that failed
  that comparison is SKIPPED, never passed.
- The verifier, the snapshots and the embedded hashes all live in this
  repository and can be edited together. There is no signing: this is
  provenance CONSISTENCY evidence, not tamper-proof attestation.

A passing report means only: the declared deterministic checks passed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import yaml
from jsonschema import Draft202012Validator

VERIFIER_VERSION = "0.6.0"
TEMPLATE_VERSION = "0.6.0"  # the capability template this verifier was released with

# Engineering recursion guard (verifier -> pytest -> tests -> verifier). Not a
# security boundary: anyone can unset an environment variable.
RECURSION_GUARD_ENV = "AI_CAPABILITY_VERIFY_ACTIVE"

MANIFEST_FILE = "capability.yaml"
PRICING_FILE = "pricing.yaml"
WORKFLOW_FILE = ".github/workflows/ai-capability-verify.yml"
EVALUATOR_FILE = "evals/evaluator.py"
VERIFY_COMMAND = "ai-capability verify"

CAPABILITY_CONTRACT = "platform/capability.schema.json"
EVAL_REPORT_CONTRACT = "platform/eval-report.schema.json"
EVAL_SUITE_CONTRACT = "platform/eval-suite.schema.json"
PRICING_CONTRACT = "platform/pricing.schema.json"
TELEMETRY_CONTRACT = "platform/telemetry-record.schema.json"
REPORT_CONTRACT = "platform/verification-report.schema.json"

# Released canonical contracts for template 0.6.0 (golden-path schemas/).
RELEASED_SNAPSHOTS = {
    CAPABILITY_CONTRACT: "7a3abb6ef1eb5b5f5db0b4e5d0fefc9f21e24f1f8761d7381960a88f5801b6ac",  # capability v1
    EVAL_REPORT_CONTRACT: "43ec0b740ce43c2987ab012ac2e22802f3e5604a2c44e66c96fb64029eea3610",  # eval-report v1
    EVAL_SUITE_CONTRACT: "4d38a26709012cfc5ff07dd00a3a36b2b9f243de985f0d47b12d513fd130bf83",  # eval-suite v1
    PRICING_CONTRACT: "307d949a70fb3c9ee5c5791a5bcdc8b479b687811ee96b9a64503d241e7280b9",  # pricing v1
    TELEMETRY_CONTRACT: "52c861a6b35bdf1c0b68cc57bdc6733302226c5f44e860ddac0b58b8ea455b24",  # telemetry-record v2
    REPORT_CONTRACT: "795b8182e5f266b838df3c496e2c9486ffd61aaeab501995d11fa75dae435dd2",  # verification-report v1
}

CHECKS: tuple[tuple[str, str], ...] = (
    ("manifest.parse", "static"),
    ("provenance.platform_snapshots", "static"),
    ("manifest.schema", "static"),
    ("provenance.template_version", "static"),
    ("schemas.input", "static"),
    ("schemas.output", "static"),
    ("eval.suite", "static"),
    ("pricing.contract", "static"),
    ("budgets.contract", "static"),
    ("observability.contract", "static"),
    ("ci.workflow", "static"),
    ("authority.declared_tools", "subprocess"),
    ("tests.gate", "subprocess"),
    ("eval.gate", "subprocess"),
)

# eval.gate runs the real evaluator only when everything it depends on passed.
# authority.declared_tools is included because the evaluator executes the real
# runtime: a declared tool with no trusted implementation makes the configuration
# statically invalid, so there is no declared behaviour left to evaluate.
# tests.gate deliberately has no prerequisites and always runs.
EVAL_GATE_PREREQUISITES = (
    "provenance.platform_snapshots",
    "manifest.schema",
    "schemas.input",
    "schemas.output",
    "eval.suite",
    "pricing.contract",
    "authority.declared_tools",
)

# Lexical: a CI step mentioning these would re-implement a verifier-owned gate.
VERIFIER_OWNED_TOKENS = ("pytest", "evaluator.py", "evals/evaluator", "jsonschema", "check_schema", "tool_registry")

TESTS_TIMEOUT_SECONDS = 900
EVAL_TIMEOUT_SECONDS = 600
REGISTRY_TIMEOUT_SECONDS = 60


class VerifierInternalError(Exception):
    """The verifier could not construct trustworthy evidence (exit 3)."""


# --------------------------------------------------------------------------
# Independent strict parsers (deliberately not shared with src/contracts.py:
# weakening product code must not weaken verification).
# --------------------------------------------------------------------------


class _StrictYamlLoader(yaml.SafeLoader):
    """SafeLoader that rejects duplicate mapping keys."""


def _unique_mapping(loader, node, deep=False):
    seen = set()
    for key_node, _ in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in seen:
            raise yaml.constructor.ConstructorError(None, None, "duplicate key", key_node.start_mark)
        seen.add(key)
    return yaml.SafeLoader.construct_mapping(loader, node, deep=deep)


_StrictYamlLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _unique_mapping)


class _WorkflowYamlLoader(_StrictYamlLoader):
    """GitHub Actions YAML: booleans are only true/false (YAML 1.2 style).

    PyYAML's YAML 1.1 resolver turns the key `on:` into boolean True. This
    loader keeps `on` a string. It is separate so the manifest loader is not
    changed.
    """


_BOOL_TAG = "tag:yaml.org,2002:bool"
_WorkflowYamlLoader.yaml_implicit_resolvers = {
    first: [(tag, regexp) for tag, regexp in resolvers if tag != _BOOL_TAG]
    for first, resolvers in _StrictYamlLoader.yaml_implicit_resolvers.items()
}
_WorkflowYamlLoader.add_implicit_resolver(
    _BOOL_TAG, re.compile(r"^(?:true|True|TRUE|false|False|FALSE)$"), list("tTfF")
)


def load_yaml_strict(text: str) -> Any:
    return yaml.load(text, Loader=_StrictYamlLoader)


def load_workflow_yaml(text: str) -> Any:
    return yaml.load(text, Loader=_WorkflowYamlLoader)


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def _reject_constant(name):
    raise ValueError("non-standard JSON constant")


def parse_json_strict(text: str) -> Any:
    return json.loads(text, object_pairs_hook=_unique_object, parse_constant=_reject_constant)


# --------------------------------------------------------------------------
# Check results
# --------------------------------------------------------------------------


@dataclass
class Check:
    id: str
    kind: str
    status: str = "pass"
    reason: str | None = None
    prerequisites: list[str] = field(default_factory=list)
    failed_rules: list[str] = field(default_factory=list)
    locations: list[str] = field(default_factory=list)

    def fail(self, reason: str, failed_rules=(), locations=()) -> None:
        self.status, self.reason = "fail", reason
        self.failed_rules = sorted(set(failed_rules))[:20]
        self.locations = sorted({loc for loc in locations if _safe_location(loc)})[:20]

    def skip(self, prerequisites) -> None:
        self.status, self.reason = "skipped", "prerequisite_failed"
        self.prerequisites = list(prerequisites)

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "kind": self.kind,
            "status": self.status,
            "reason": self.reason,
            "prerequisites": self.prerequisites,
            "failed_rules": self.failed_rules,
            "locations": self.locations,
        }


def _safe_location(location: str) -> bool:
    return 0 < len(location) <= 200 and all(c.isalnum() or c in "_./-" for c in location)


def _schema_problems(schema: dict, instance: Any, prefix: str = "") -> tuple[list[str], list[str]]:
    """(failed JSON Schema keywords, schema paths). Never values."""
    rules, locations = set(), set()
    for error in Draft202012Validator(schema).iter_errors(instance):
        rules.add(str(error.validator))
        path = "/".join(str(p) for p in error.absolute_path)
        locations.add("/".join(part for part in (prefix, path) if part) or prefix or ".")
    return sorted(rules), sorted(locations)


def _contained(root: Path, relative: str) -> Path | None:
    """Resolved path if it stays inside root (symlinks included), else None."""
    try:
        path = (root / relative).resolve()
    except (OSError, RuntimeError, ValueError):
        return None
    return path if path.is_relative_to(root.resolve()) else None


def _dig(data: Any, *keys: str) -> Any:
    for key in keys:
        if not isinstance(data, dict):
            return None
        data = data.get(key)
    return data


def _tail(text: str, lines: int = 40) -> str:
    return "\n".join(text.strip().splitlines()[-lines:])


# --------------------------------------------------------------------------
# Subprocess runners (injectable so the verifier's own unit tests never run a
# real nested test gate)
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class TestRun:
    outcome: str  # passed | failed | no_tests | error | timeout
    tests: int | None = None
    failures: int | None = None
    errors: int | None = None
    skipped: int | None = None
    diagnostic: str = ""


@dataclass(frozen=True)
class EvalRun:
    exit_code: int | None  # None: timed out
    stdout: str = ""
    diagnostic: str = ""


@dataclass(frozen=True)
class Runners:
    run_tests: Callable[[Path], TestRun]
    run_evaluator: Callable[[Path], EvalRun]
    inspect_registry: Callable[[Path], dict | None]


def _subprocess_env() -> dict:
    env = dict(os.environ)
    env[RECURSION_GUARD_ENV] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def _junit_counts(path: Path) -> dict | None:
    try:
        suites = list(ET.parse(path).getroot().iter("testsuite"))
    except (OSError, ET.ParseError):
        return None
    counts = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}
    for suite in suites:
        for key in counts:
            counts[key] += int(suite.get(key, "0"))
    return counts


def run_pytest(root: Path) -> TestRun:
    with tempfile.TemporaryDirectory() as tmp:
        junit = Path(tmp) / "junit.xml"
        try:
            completed = subprocess.run(
                [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", f"--junitxml={junit}"],
                cwd=root,
                env=_subprocess_env(),
                capture_output=True,
                text=True,
                timeout=TESTS_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            return TestRun("timeout", diagnostic="pytest timed out")
        counts = _junit_counts(junit) or {}
    outcome = {0: "passed", 1: "failed", 5: "no_tests"}.get(completed.returncode, "error")
    if outcome == "passed" and not counts.get("tests"):
        outcome = "no_tests" if counts else "error"
    diagnostic = "" if outcome == "passed" else _tail(completed.stdout + "\n" + completed.stderr)
    return TestRun(outcome, diagnostic=diagnostic, **{k: counts.get(k) for k in ("tests", "failures", "errors", "skipped")})


def run_evaluator(root: Path) -> EvalRun:
    with tempfile.TemporaryDirectory() as tmp:
        try:
            completed = subprocess.run(
                [
                    sys.executable,
                    EVALUATOR_FILE,
                    "--correlation-id",
                    "ai-capability-verify",
                    "--telemetry-file",
                    str(Path(tmp) / "eval-telemetry.jsonl"),  # discarded; never in the report
                ],
                cwd=root,
                env=_subprocess_env(),
                capture_output=True,
                text=True,
                timeout=EVAL_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            return EvalRun(None, diagnostic="evaluator timed out")
    return EvalRun(completed.returncode, completed.stdout, _tail(completed.stderr, 10))


_REGISTRY_PROBE = (
    "import json, sys\n"
    "sys.path.insert(0, 'src')\n"
    "from tools import TOOL_REGISTRY\n"
    "print(json.dumps({name: tool.impact for name, tool in sorted(TOOL_REGISTRY.items())}))\n"
)


def inspect_registry(root: Path) -> dict | None:
    """Imports the trusted registry in a subprocess. Calls no model, tool or policy."""
    try:
        completed = subprocess.run(
            [sys.executable, "-c", _REGISTRY_PROBE],
            cwd=root,
            env=_subprocess_env(),
            capture_output=True,
            text=True,
            timeout=REGISTRY_TIMEOUT_SECONDS,
        )
        registry = parse_json_strict(completed.stdout) if completed.returncode == 0 else None
    except (subprocess.TimeoutExpired, ValueError):
        return None
    if not isinstance(registry, dict) or not all(
        isinstance(k, str) and v in ("low", "high") for k, v in registry.items()
    ):
        return None
    return registry


DEFAULT_RUNNERS = Runners(run_tests=run_pytest, run_evaluator=run_evaluator, inspect_registry=inspect_registry)


# --------------------------------------------------------------------------
# Verification
# --------------------------------------------------------------------------


def verify(root: Path, runners: Runners = DEFAULT_RUNNERS) -> tuple[dict, list[str]]:
    """Returns (VerificationReport, human diagnostics for stderr)."""
    checks = {check_id: Check(check_id, kind) for check_id, kind in CHECKS}
    diagnostics: list[str] = []
    evidence = {
        "authority": {"declared_tools": [], "unregistered_count": None, "runtime_authorization": "not_evaluated_by_verifier"},
        "budgets": {"max_model_requests": None, "max_output_tokens": None, "max_latency_ms": None,
                    "enforced_at_runtime": ["max_model_requests"]},
        "observability": {"tracing": None, "usage": None, "cost": None, "delivery_tested": False},
        "tests": {"outcome": "error", "tests": None, "failures": None, "errors": None, "skipped": None},
        "eval": {"gate_passed": None, "total": None, "passed": None, "failed": None,
                 "observed_pass_rate": None, "required_pass_rate": None, "suite_sha256": None},
    }

    # 1. manifest.parse
    manifest = None
    manifest_path = root / MANIFEST_FILE
    if not manifest_path.is_file():
        checks["manifest.parse"].fail("missing", locations=[MANIFEST_FILE])
    else:
        try:
            manifest = load_yaml_strict(manifest_path.read_text(encoding="utf-8"))
        except (UnicodeDecodeError, yaml.YAMLError) as exc:
            mark = getattr(exc, "problem_mark", None)
            diagnostics.append(f"{MANIFEST_FILE}: {type(exc).__name__}" + (f" at line {mark.line + 1}" if mark else ""))
            checks["manifest.parse"].fail("unparseable", locations=[MANIFEST_FILE])
            manifest = None
        if manifest is not None and not isinstance(manifest, dict):
            checks["manifest.parse"].fail("unparseable", locations=[MANIFEST_FILE])
            manifest = None

    # 2. provenance.platform_snapshots: establish trust BEFORE any contract use.
    trusted: dict[str, dict] = {}
    problems: dict[str, str] = {}
    for relative, digest in RELEASED_SNAPSHOTS.items():
        path = _contained(root, relative)
        if path is None or not path.is_file():
            problems[relative] = "missing"
            continue
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != digest:
            problems[relative] = "hash_mismatch"
            continue
        trusted[relative] = parse_json_strict(data.decode("utf-8"))
    if problems:
        reason = "hash_mismatch" if "hash_mismatch" in problems.values() else "missing"
        checks["provenance.platform_snapshots"].fail(reason, locations=problems)
        diagnostics.extend(f"{path}: {problem} (not the released contract; derived checks skipped)" for path, problem in sorted(problems.items()))

    def blocked(check_id: str, *, needs_manifest: bool = False, contracts: tuple[str, ...] = ()) -> bool:
        prerequisites = []
        if needs_manifest and manifest is None:
            prerequisites.append("manifest.parse")
        if any(contract not in trusted for contract in contracts):
            prerequisites.append("provenance.platform_snapshots")
        if prerequisites:
            checks[check_id].skip(prerequisites)
            return True
        return False

    # 3. manifest.schema (against the TRUSTED capability contract only)
    if not blocked("manifest.schema", needs_manifest=True, contracts=(CAPABILITY_CONTRACT,)):
        rules, locations = _schema_problems(trusted[CAPABILITY_CONTRACT], manifest)
        if rules:
            checks["manifest.schema"].fail("schema_violation", rules, locations)

    # 4. provenance.template_version (consistency of a claim, not attestation)
    if not blocked("provenance.template_version", needs_manifest=True):
        claimed = _dig(manifest, "metadata", "template_version")
        if claimed is None:
            checks["provenance.template_version"].fail("missing", locations=["metadata/template_version"])
        elif claimed != TEMPLATE_VERSION:
            checks["provenance.template_version"].fail("version_mismatch", locations=["metadata/template_version"])
            diagnostics.append(f"metadata.template_version does not match this verifier's template {TEMPLATE_VERSION}")

    # 5-6. schemas.input / schemas.output
    for check_id, section in (("schemas.input", "inputs"), ("schemas.output", "outputs")):
        if blocked(check_id, needs_manifest=True):
            continue
        reference = _dig(manifest, "spec", section, "schema")
        _check_json_schema_file(root, checks[check_id], reference, f"spec/{section}/schema")

    # 7. eval.suite
    if not blocked("eval.suite", needs_manifest=True, contracts=(EVAL_SUITE_CONTRACT,)):
        reference = _dig(manifest, "spec", "evaluation", "suite")
        _check_yaml_contract_file(root, checks["eval.suite"], reference, trusted[EVAL_SUITE_CONTRACT], "spec/evaluation/suite")

    # 8. pricing.contract
    if not blocked("pricing.contract", contracts=(PRICING_CONTRACT,)):
        _check_yaml_contract_file(root, checks["pricing.contract"], PRICING_FILE, trusted[PRICING_CONTRACT], PRICING_FILE)

    # 9-10. budgets.contract / observability.contract: canonical SUBSCHEMAS of
    # the trusted capability contract; no bounds are duplicated here.
    for check_id, section in (("budgets.contract", "budgets"), ("observability.contract", "observability")):
        if blocked(check_id, needs_manifest=True, contracts=(CAPABILITY_CONTRACT,)):
            continue
        subschema = trusted[CAPABILITY_CONTRACT]["properties"]["spec"]["properties"][section]
        value = _dig(manifest, "spec", section)
        if value is None:
            checks[check_id].fail("missing", locations=[f"spec/{section}"])
            continue
        rules, locations = _schema_problems(subschema, value, f"spec/{section}")
        if rules:
            checks[check_id].fail("schema_violation", rules, locations)
        else:  # surface configured values only once they satisfy the contract
            evidence[section].update({key: value[key] for key in evidence[section] if key in value})

    # 11. ci.workflow
    _check_workflow(root, checks["ci.workflow"], diagnostics)

    # 12. authority.declared_tools: declared ⊆ registered. No model, tool or policy.
    if not blocked("authority.declared_tools", needs_manifest=True):
        declared = _dig(manifest, "spec", "authority", "tools")
        if not isinstance(declared, list) or not all(isinstance(t, str) for t in declared):
            checks["authority.declared_tools"].fail("schema_violation", locations=["spec/authority/tools"])
        elif declared:
            registry = runners.inspect_registry(root)
            if registry is None:
                checks["authority.declared_tools"].fail("registry_unavailable", locations=["src/tools.py"])
            else:
                unregistered = sorted({t for t in declared if t not in registry})
                evidence["authority"]["declared_tools"] = [
                    {"name": t, "impact": registry[t]} for t in sorted(set(declared)) if t in registry
                ]
                evidence["authority"]["unregistered_count"] = len(unregistered)
                if unregistered:
                    checks["authority.declared_tools"].fail("unregistered_tools", locations=["spec/authority/tools"])
                    diagnostics.append(f"declared tools with no trusted registry implementation: {', '.join(unregistered)}")
        else:
            evidence["authority"]["unregistered_count"] = 0

    # 13. tests.gate: the project's own suite, run by pytest in a subprocess.
    test_run = runners.run_tests(root)
    evidence["tests"] = {
        "outcome": test_run.outcome,
        "tests": test_run.tests,
        "failures": test_run.failures,
        "errors": test_run.errors,
        "skipped": test_run.skipped,
    }
    if test_run.outcome != "passed":
        reason = {"failed": "tests_failed", "no_tests": "no_tests", "timeout": "timeout"}.get(test_run.outcome, "tests_error")
        checks["tests.gate"].fail(reason, locations=["tests"])
        if test_run.diagnostic:
            diagnostics.append("pytest output (tail):\n" + test_run.diagnostic)

    # 14. eval.gate: the capability's own evaluator decides; nothing re-implemented.
    missing_prerequisites = [c for c in EVAL_GATE_PREREQUISITES if checks[c].status != "pass"]
    if missing_prerequisites:
        checks["eval.gate"].skip(missing_prerequisites)
    else:
        _check_eval_gate(root, checks["eval.gate"], evidence["eval"], trusted[EVAL_REPORT_CONTRACT], runners, diagnostics)

    ordered = [checks[check_id].as_dict() for check_id, _ in CHECKS]
    schema_passed = checks["manifest.schema"].status == "pass"
    report = {
        "api_version": "ai.platform/v1",
        "kind": "VerificationReport",
        "meaning": "declared_deterministic_checks_only",
        "verifier": {"version": VERIFIER_VERSION},
        "capability": {
            "name": _dig(manifest, "metadata", "name") if schema_passed else None,
            "version": _dig(manifest, "metadata", "version") if schema_passed else None,
            "template_version": _dig(manifest, "metadata", "template_version") if schema_passed else None,
        },
        "report_schema_validation": "trusted_snapshot" if REPORT_CONTRACT in trusted else "not_performed_untrusted_snapshot",
        "result": summarize(ordered),
        "checks": ordered,
        "evidence": evidence,
    }
    if REPORT_CONTRACT in trusted:
        rules, locations = _schema_problems(trusted[REPORT_CONTRACT], report)
        if rules:
            raise VerifierInternalError(f"report violates {REPORT_CONTRACT}: {rules} at {locations}")
    return report, diagnostics


def summarize(ordered: list[dict]) -> dict:
    """A skip is never a soft warning: the result passes only with 0 fail AND 0 skipped."""
    counts = {status: sum(c["status"] == status for c in ordered) for status in ("pass", "fail", "skipped")}
    return {"passed": counts["fail"] == 0 and counts["skipped"] == 0, "total": len(ordered), **counts}


def _check_json_schema_file(root: Path, check: Check, reference: Any, location: str) -> None:
    if not isinstance(reference, str) or not reference:
        check.fail("missing", locations=[location])
        return
    path = _contained(root, reference)
    if path is None:
        check.fail("path_escape", locations=[location])
        return
    if not path.is_file():
        check.fail("missing", locations=[location])
        return
    try:
        schema = parse_json_strict(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, ValueError):
        check.fail("unparseable", locations=[location])
        return
    try:
        Draft202012Validator.check_schema(schema)
    except Exception:
        check.fail("not_a_json_schema", locations=[location])


def _check_yaml_contract_file(root: Path, check: Check, reference: Any, contract: dict, location: str) -> None:
    if not isinstance(reference, str) or not reference:
        check.fail("missing", locations=[location])
        return
    path = _contained(root, reference)
    if path is None:
        check.fail("path_escape", locations=[location])
        return
    if not path.is_file():
        check.fail("missing", locations=[location])
        return
    try:
        document = load_yaml_strict(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, yaml.YAMLError):
        check.fail("unparseable", locations=[location])
        return
    rules, locations = _schema_problems(contract, document)
    if rules:
        check.fail("schema_violation", rules, locations)


def _check_workflow(root: Path, check: Check, diagnostics: list[str]) -> None:
    """Semantic, lexical check: CI must invoke the verifier, not duplicate it.

    Unrelated steps (e.g. linting) are allowed; the workflow need not be
    byte-identical to the generated one.
    """
    path = _contained(root, WORKFLOW_FILE)
    if path is None or not path.is_file():
        check.fail("missing", locations=[WORKFLOW_FILE])
        return
    try:
        workflow = load_workflow_yaml(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, yaml.YAMLError):
        check.fail("unparseable", locations=[WORKFLOW_FILE])
        return
    if not isinstance(workflow, dict) or "on" not in workflow or not isinstance(workflow.get("jobs"), dict):
        check.fail("workflow_invalid", locations=[WORKFLOW_FILE])
        return
    least = {"contents": "read"}
    jobs = [job for job in workflow["jobs"].values() if isinstance(job, dict)]
    if workflow.get("permissions") != least or any(
        "permissions" in job and job["permissions"] not in ({}, least) for job in jobs
    ):
        check.fail("workflow_permissions", locations=[WORKFLOW_FILE])
        return
    runs = [
        step["run"]
        for job in jobs
        for step in (job.get("steps") or [])
        if isinstance(step, dict) and isinstance(step.get("run"), str)
    ]
    if not any(run.strip() == VERIFY_COMMAND for run in runs):
        check.fail("workflow_missing_verify", locations=[WORKFLOW_FILE])
        return
    duplicated = [run for run in runs if any(token in run.lower() for token in VERIFIER_OWNED_TOKENS)]
    if duplicated:
        check.fail("workflow_duplicates_verifier", locations=[WORKFLOW_FILE])
        diagnostics.append(f"{WORKFLOW_FILE}: CI re-implements a verifier-owned gate; run only `{VERIFY_COMMAND}`")


def _check_eval_gate(
    root: Path, check: Check, evidence: dict, report_contract: dict, runners: Runners, diagnostics: list[str]
) -> None:
    run = runners.run_evaluator(root)
    if run.exit_code is None:
        check.fail("timeout", locations=[EVALUATOR_FILE])
        return
    try:
        eval_report = parse_json_strict(run.stdout) if run.stdout.strip() else None
    except ValueError:
        eval_report = None
    if eval_report is None or _schema_problems(report_contract, eval_report)[0]:
        check.fail("evaluator_error", locations=[EVALUATOR_FILE])
        if run.diagnostic:
            diagnostics.append("evaluator (stderr tail):\n" + run.diagnostic)
        return
    summary = eval_report["summary"]
    evidence.update(
        {
            "gate_passed": summary["gate_passed"],
            "total": summary["total"],
            "passed": summary["passed"],
            "failed": summary["failed"],
            "observed_pass_rate": summary["observed_pass_rate"],
            "required_pass_rate": summary["required_pass_rate"],
            "suite_sha256": eval_report["suite"]["sha256"],
        }
    )
    if run.exit_code == 0 and summary["gate_passed"] is True:
        return
    if run.exit_code == 1 and summary["gate_passed"] is False:
        check.fail("gate_not_met", locations=[EVALUATOR_FILE])
        failed = [case["id"] for case in eval_report["cases"] if not case["passed"]]
        diagnostics.append(f"eval gate not met: {summary['passed']}/{summary['total']} passed; failing cases: {', '.join(failed)}")
        return
    check.fail("evaluator_error", locations=[EVALUATOR_FILE])  # exit code contradicts the report


# --------------------------------------------------------------------------
# Command line
# --------------------------------------------------------------------------


def render_report(report: dict) -> str:
    return json.dumps(report, indent=2, sort_keys=True) + "\n"


def _checklist(report: dict) -> str:
    result = report["result"]
    lines = [
        f"ai-capability verify: {'PASSED' if result['passed'] else 'FAILED'}  "
        f"({result['pass']} pass, {result['fail']} fail, {result['skipped']} skipped)"
    ]
    for check in report["checks"]:
        label = {"pass": "PASS", "fail": "FAIL", "skipped": "SKIP"}[check["status"]]
        detail = check["reason"] or ""
        if check["prerequisites"]:
            detail += ": " + ", ".join(check["prerequisites"])
        elif check["locations"]:
            detail += "  " + ", ".join(check["locations"][:3])
        lines.append(f"  {label}  {check['id']:<30} {detail}".rstrip())
    lines.append("meaning: declared deterministic checks only (not production readiness)")
    lines.append("full report: stdout (VerificationReport JSON)")
    return "\n".join(lines)


def main(argv: list[str] | None = None, runners: Runners | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ai-capability", description="Verify this AI capability.")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("verify", help="run every deterministic verification check (run from the capability root)")
    parser.parse_args(argv)

    if os.environ.get(RECURSION_GUARD_ENV):
        print(f"ai-capability verify: refusing nested verification ({RECURSION_GUARD_ENV} is set)", file=sys.stderr)
        return 3
    try:
        report, diagnostics = verify(Path.cwd(), runners or DEFAULT_RUNNERS)
    except Exception as exc:  # noqa: BLE001 - any failure here means no trustworthy report
        print(f"ai-capability verify: internal error ({type(exc).__name__}); no report produced", file=sys.stderr)
        return 3

    sys.stdout.write(render_report(report))
    print(_checklist(report), file=sys.stderr)
    for diagnostic in diagnostics:
        print(diagnostic, file=sys.stderr)
    return 0 if report["result"]["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
