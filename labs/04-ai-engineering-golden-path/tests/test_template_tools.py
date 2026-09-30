"""Phase 6: platform tests for tool authority in the current template.

The generated project runs in subprocesses with golden_path import-blocked.
The detailed adversarial cases live in the generated tests/test_tools.py
(product-team-owned); this file runs them in isolation and adds command-line
and telemetry-contract evidence: every lifecycle outcome validates against
the canonical telemetry v2 contract and carries no arguments or results.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator

from conftest import only_record, stderr_records
from golden_path import scaffold

CAPABILITY = "guarded-demo"
V2 = json.loads((scaffold.LAB_ROOT / "schemas" / "telemetry-record.v2.schema.json").read_text())

# Runs inside the generated project (golden_path blocked). Emits one JSON
# object per scenario: the capability outcome plus all telemetry records.
SCENARIOS = r'''
import asyncio, json, sys
from dataclasses import replace
sys.path.insert(0, "src")
from capability import run
from contracts import CapabilityError, load_manifest
from cost import Pricing
from model_adapter import FakeModelAdapter, ModelInfo, ModelResponse, ToolRequest
from policy import PolicyDecision
from telemetry import InMemorySink, Telemetry
from tools import SyntheticLedger

VALID = json.dumps({"headline": "CHG-1: x", "explanation": "e", "risk_level": "low", "open_questions": []})
PUBLISH = ToolRequest("publish_change_notice", {"change_id": "CHG-777001", "audience": "stakeholders", "risk_level": "medium"})
LOOKUP = ToolRequest("lookup_change_context", {"change_id": "CHG-777002"})

class Allow:
    async def authorize(self, context, arguments):
        return PolicyDecision(True, "trusted_test_policy")

def reply(content, requests):
    return ModelResponse(content, ModelInfo("fake", FakeModelAdapter.model_label), tool_requests=requests)

cases = {
    "rejected": ([reply(VALID, (ToolRequest("drop_all_tables", {"confirm": "yes-really"}),))], ("lookup_change_context",), None, None),
    "denied": ([reply(VALID, (PUBLISH,))], ("publish_change_notice",), None, None),
    "discarded": ([reply("not json", (LOOKUP,))], ("lookup_change_context",), None, None),
    "executed": ([reply(VALID, (LOOKUP,))], ("lookup_change_context",), None, None),
    "execution_failed": ([reply(VALID, (PUBLISH,))], ("publish_change_notice",), Allow(), SyntheticLedger(fail_writes=True)),
}
for name, (responses, tools, policy, ledger) in cases.items():
    ledger = ledger or SyntheticLedger()
    sink = InMemorySink()
    manifest = replace(load_manifest(), tools=tools, max_model_requests=1)
    try:
        asyncio.run(run(json.load(open("fixtures/sample_input.json")), manifest=manifest,
                        adapter=FakeModelAdapter(scripted=responses), pricing=Pricing("USD"),
                        telemetry=Telemetry(sink, correlation_id="platform-" + name.replace("_", "-")),
                        policy=policy, ledger=ledger))
        error, exit_code = None, 0
    except CapabilityError as exc:
        error, exit_code = type(exc).__name__, exc.exit_code
    print(json.dumps({"scenario": name, "error": error, "exit_code": exit_code,
                      "ledger": {"lookups": ledger.lookups, "notices": ledger.notices}, "records": sink.records}))
'''


@pytest.fixture(scope="module")
def project(tmp_path_factory) -> Path:
    destination, _ = scaffold.new_capability(CAPABILITY, tmp_path_factory.mktemp("tools"))
    return destination


@pytest.fixture(scope="module")
def scenarios(project, blocked_env) -> dict:
    completed = subprocess.run(
        [sys.executable, "-c", SCENARIOS], cwd=project, env=blocked_env, capture_output=True, text=True, check=False
    )
    assert completed.returncode == 0, completed.stderr
    return {row["scenario"]: row for row in map(json.loads, completed.stdout.splitlines())}


def tool_span(row: dict) -> dict:
    [span] = [r for r in row["records"] if r["name"] == "capability.tool_request"]
    return span


def test_generated_default_grants_no_tools(project):
    manifest = yaml.safe_load((project / "capability.yaml").read_text())
    assert manifest["metadata"]["template_version"] == scaffold.TEMPLATE_VERSION  # 0.5.0+: tools supported, none granted
    assert manifest["spec"]["authority"]["tools"] == []


def test_generated_tool_security_suite_passes_without_golden_path(project, blocked_env):
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests/test_tools.py"],
        cwd=project,
        env=blocked_env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


@pytest.mark.parametrize(
    ("scenario", "exit_code", "lifecycle", "ledger"),
    [
        ("rejected", 6, ("rejected", "not_evaluated", "not_attempted", "rejected"), {"lookups": [], "notices": []}),
        ("denied", 6, ("passed", "denied", "not_attempted", "denied"), {"lookups": [], "notices": []}),
        ("discarded", 4, ("passed", "not_evaluated", "not_attempted", "discarded"), {"lookups": [], "notices": []}),
        ("executed", 0, ("passed", "allowed", "succeeded", "executed"), {"lookups": ["CHG-777002"], "notices": []}),
        ("execution_failed", 7, ("passed", "allowed", "failed", "execution_failed"), {"lookups": [], "notices": []}),
    ],
)
def test_lifecycle_outcomes_validate_against_telemetry_v2(scenarios, scenario, exit_code, lifecycle, ledger):
    row = scenarios[scenario]
    assert row["exit_code"] == exit_code
    assert row["ledger"] == ledger
    span = tool_span(row)
    a = span["attributes"]
    assert (a["tool.preflight_status"], a["tool.authorization_status"], a["tool.execution_status"], a["tool.outcome"]) == lifecycle
    for record in row["records"]:
        assert record["schema"] == "telemetry-record/v2"
        assert list(Draft202012Validator(V2).iter_errors(record)) == []


def test_no_arguments_results_or_unknown_names_in_tool_telemetry(scenarios):
    serialized = json.dumps([row["records"] for row in scenarios.values()])
    for value in ("CHG-777001", "CHG-777002", "stakeholders", "drop_all_tables", "yes-really", "related_changes"):
        assert value not in serialized
    assert tool_span(scenarios["rejected"])["attributes"]["tool.name"] == "unrecognized"


def test_v2_contract_rejects_inconsistent_lifecycle_combinations(scenarios):
    record = json.loads(json.dumps(tool_span(scenarios["denied"])))
    record["attributes"]["tool.execution_status"] = "succeeded"  # "denied but executed" is not representable
    assert list(Draft202012Validator(V2).iter_errors(record))


def test_v1_contract_cannot_represent_tool_spans(scenarios):
    v1 = json.loads((scaffold.LAB_ROOT / "schemas" / "telemetry-record.schema.json").read_text())
    assert list(Draft202012Validator(v1).iter_errors(tool_span(scenarios["executed"])))


# --- command line --------------------------------------------------------------------------


def run_cli(project: Path, env: dict) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "src/capability.py", "fixtures/sample_input.json"],
        cwd=project,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_cli_declared_but_unregistered_tool_exits_3_before_model(tmp_path, blocked_env):
    destination, _ = scaffold.new_capability(CAPABILITY, tmp_path)
    manifest = destination / "capability.yaml"
    manifest.write_text(manifest.read_text().replace("tools: []", "tools: [search_docs]", 1))
    completed = run_cli(destination, blocked_env)
    assert completed.returncode == 3 and completed.stdout == ""
    error = only_record(completed.stderr, "error")
    assert "no trusted registry implementation" in error["message"]
    assert error["model_requests_used"] == 0
    assert [r for r in stderr_records(completed.stderr) if r.get("name") == "capability.model_request"] == []


def test_cli_with_declared_tool_but_no_proposal_runs_normally(tmp_path, blocked_env):
    destination, _ = scaffold.new_capability(CAPABILITY, tmp_path)
    manifest = destination / "capability.yaml"
    manifest.write_text(manifest.read_text().replace("tools: []", "tools: [lookup_change_context]", 1))
    completed = run_cli(destination, blocked_env)
    assert completed.returncode == 0
    root = next(r for r in stderr_records(completed.stderr) if r.get("name") == "capability.run")
    assert (root["attributes"]["tools.proposed"], root["attributes"]["tools.executed"]) == (0, 0)


def test_cli_has_no_policy_or_authority_option(project, blocked_env):
    completed = subprocess.run(
        [sys.executable, "src/capability.py", "--help"], cwd=project, env=blocked_env, capture_output=True, text=True
    )
    help_text = completed.stdout.lower()
    for forbidden in ("policy", "allow", "high-impact", "authorize", "approve"):
        assert forbidden not in help_text
