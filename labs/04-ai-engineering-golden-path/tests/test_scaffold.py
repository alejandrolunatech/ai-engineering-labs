"""Phase 2: deterministic tests for `ai-golden-path new`.

No network, no model, no clock. These prove the scaffold's declared properties
(name validation, contract conformance, determinism, overwrite refusal). They
do not prove anything about runtime behavior, which does not exist yet.
"""

from __future__ import annotations

import getpass
import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from typer.testing import CliRunner

from golden_path import scaffold
from golden_path.cli import app

# Reuse Phase 1 fixtures and the strict duplicate-key loader rather than
# re-declaring the contract here.
from test_capability_schema import (
    EXAMPLE_MANIFEST,
    INVALID_CASES,
    SCHEMA_PATH,
    VALID_BOUNDARY_CASES,
    load_yaml_strict,
)

LAB_ROOT = Path(__file__).resolve().parents[1]
# Tree produced by the CURRENT template version (capability@0.3.0).
EXPECTED_TREE = [
    "README.md",
    "capability.yaml",
    "evals/cases.yaml",
    "evals/evaluator.py",
    "fixtures/sample_input.json",
    "platform/capability.schema.json",
    "platform/eval-report.schema.json",
    "platform/eval-suite.schema.json",
    "pyproject.toml",
    "requirements.txt",
    "schemas/input.schema.json",
    "schemas/output.schema.json",
    "src/capability.py",
    "src/contracts.py",
    "src/model_adapter.py",
    "tests/test_capability.py",
    "tests/test_evals.py",
]

# Released templates are immutable. These digests pin each released version
# exactly as committed (0.1.0 in Phase 2, 0.2.0 in Phase 3); any change to
# generated output must become a new template version instead.
FROZEN_TEMPLATES = {
    "0.1.0": {
        "README.md.j2": "477a1d56242896f3a9c92263cf035c8a762bfc42c3236d2e9cf640e1f0a066b0",
        "capability.yaml.j2": "074444f57bfca53569e9643a988996947414fa6d4f4289c49ca634647631a97c",
        "schemas/input.schema.json": "30a49ee496efc3a7f55cf50bc74de7d16b9852d8c80c58b03d02b5f98e2b716d",
        "schemas/output.schema.json": "64b84ca89036e3c2af93c3184cfac927e468caedd314ae7463e9b5dcc785f029",
    },
    "0.2.0": {
        "README.md.j2": "7d5f4fe1e98312282e967113902d412b02798ac4d750e7017a3a980a1610895f",
        "capability.yaml.j2": "8cf2a7bdb16242a21e16bb81b19f0ae9a81f5d3b0fe3a9e21f4fda7928f546be",
        "fixtures/sample_input.json": "4c20a26777581c984e430aaf892c63c67c94ab686beba13c03a2d51105e0c6f3",
        "pyproject.toml": "5a57cde172efa412a05785571ba06e6f1764200ab386ad94a01187f1c8f2139b",
        "requirements.txt": "bcb619e79ee54b01399e61246ecf9d186224c4ac0bdb9be656bbf77314689d99",
        "schemas/input.schema.json": "30a49ee496efc3a7f55cf50bc74de7d16b9852d8c80c58b03d02b5f98e2b716d",
        "schemas/output.schema.json": "64b84ca89036e3c2af93c3184cfac927e468caedd314ae7463e9b5dcc785f029",
        "src/capability.py": "e929098ad461fb23a65e81c87f58a68d007c539c24218108e9f5882631a1d292",
        "src/contracts.py": "819c2769d41756339866dedc17f6d4aaca78487de2a9fea37bc492b3282d2ff3",
        "src/model_adapter.py": "c4d276f4749ccc3c21e4de609e87162d90a911c50ebbeac5280f2276602b0c5a",
        "tests/test_capability.py": "9d5d6c199295502caa54b32168e6c38674a6a8e830073088900277ba10d4b125",
    },
}

runner = CliRunner()


def tree_digest(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def snapshot(root: Path) -> dict[str, str]:
    """Everything under root, including symlinks and empty dirs, without following links."""
    state = {}
    for path in sorted(root.rglob("*")):
        key = path.relative_to(root).as_posix()
        if path.is_symlink():
            state[key] = "link:" + os.readlink(path)
        elif path.is_dir():
            state[key] = "dir"
        else:
            state[key] = "file:" + hashlib.sha256(path.read_bytes()).hexdigest()
    return state


def dotted_paths(node, prefix="") -> set[str]:
    if isinstance(node, dict):
        paths = set()
        for key, value in node.items():
            paths |= dotted_paths(value, f"{prefix}.{key}" if prefix else key)
        return paths
    return {prefix}


def run_new(cwd: Path, name: str, monkeypatch):
    monkeypatch.chdir(cwd)
    return runner.invoke(app, ["new", name])


# --------------------------------------------------------------------------
# Name validation: aligned with the Phase 1 schema
# --------------------------------------------------------------------------

PHASE1_INVALID_NAMES = [
    value for _, path, value in INVALID_CASES if path == "metadata.name" and isinstance(value, str)
]
PHASE1_VALID_NAMES = [value for _, path, value in VALID_BOUNDARY_CASES if path == "metadata.name"]


def schema_accepts_name(name: str) -> bool:
    schema = json.loads(SCHEMA_PATH.read_text())
    name_schema = schema["properties"]["metadata"]["properties"]["name"]
    return not list(Draft202012Validator(name_schema).iter_errors(name))


@pytest.mark.parametrize("name", PHASE1_INVALID_NAMES + PHASE1_VALID_NAMES + ["change-explainer"])
def test_cli_name_rule_matches_phase1_schema(name):
    try:
        scaffold.validate_name(name)
        cli_accepts = True
    except scaffold.InvalidNameError:
        cli_accepts = False
    assert cli_accepts == schema_accepts_name(name)


@pytest.mark.parametrize("name", ["abc\n", "change-explainer\n", "change-explainer\r\n"])
def test_cli_is_stricter_than_schema_on_trailing_line_breaks(name):
    # Documented divergence: Python's `$` matches before a trailing newline, so
    # the v1 schema accepts these. The CLI rejects them for filesystem safety.
    if name.endswith("\n") and "\r" not in name:
        assert schema_accepts_name(name)
    with pytest.raises(scaffold.InvalidNameError):
        scaffold.validate_name(name)


@pytest.mark.parametrize(
    "name",
    PHASE1_INVALID_NAMES + ["abc\n", "", ".", "..", "a/b", "/tmp/evil", "café-app", "ab\x00cd"],
)
def test_invalid_name_creates_nothing(tmp_path, monkeypatch, name):
    monkeypatch.chdir(tmp_path)
    # "--" ensures names like "-change" reach the validator instead of being
    # rejected earlier by the option parser.
    result = runner.invoke(app, ["new", "--", name])
    assert result.exit_code == 2
    assert "invalid capability name" in result.output
    assert list(tmp_path.iterdir()) == []


# --------------------------------------------------------------------------
# Generated tree and contract conformance
# --------------------------------------------------------------------------


def test_template_directory_matches_declared_version():
    root = scaffold.template_dir()
    assert root.name == scaffold.TEMPLATE_VERSION == "0.3.0"
    assert [p.relative_to(root).as_posix() for p in scaffold.template_sources()] == [
        "README.md.j2",
        "capability.yaml.j2",
        "evals/cases.yaml",
        "evals/evaluator.py",
        "fixtures/sample_input.json",
        "pyproject.toml",
        "requirements.txt",
        "schemas/input.schema.json",
        "schemas/output.schema.json",
        "src/capability.py",
        "src/contracts.py",
        "src/model_adapter.py",
        "tests/test_capability.py",
        "tests/test_evals.py",
    ]


@pytest.mark.parametrize("version", sorted(FROZEN_TEMPLATES))
def test_released_template_is_frozen(version):
    root = scaffold.TEMPLATES_ROOT / scaffold.TEMPLATE_ID / version
    committed = {
        path: digest
        for path, digest in tree_digest(root).items()
        if not any(part.startswith(".") or part == "__pycache__" for part in path.split("/"))
    }
    assert committed == FROZEN_TEMPLATES[version]


def test_new_creates_exact_tree(tmp_path, monkeypatch):
    result = run_new(tmp_path, "demo-capability", monkeypatch)
    assert result.exit_code == 0, result.output
    project = tmp_path / "demo-capability"
    assert sorted(tree_digest(project)) == EXPECTED_TREE
    assert [p.name for p in tmp_path.iterdir()] == ["demo-capability"]


@pytest.mark.parametrize("name", ["demo-capability", "change-explainer", "abc", "a" * 40, "yes", "null", "off", "true"])
def test_generated_manifest_validates_against_canonical_phase1_schema(name):
    # "yes"/"null"/"off"/"true" are valid names that YAML 1.1 would coerce to
    # bool/None if the template did not quote metadata.name.
    manifest = load_yaml_strict(scaffold.render(name)["capability.yaml"].decode())
    validator = Draft202012Validator(json.loads(SCHEMA_PATH.read_text()))
    assert [e.message for e in validator.iter_errors(manifest)] == []
    assert manifest["metadata"]["name"] == name


def test_generated_manifest_has_same_shape_as_phase1_example():
    generated = load_yaml_strict(scaffold.render("demo-capability")["capability.yaml"].decode())
    example = load_yaml_strict(EXAMPLE_MANIFEST.read_text())
    assert dotted_paths(generated) == dotted_paths(example)


def test_provenance_is_recorded_in_manifest(tmp_path, monkeypatch):
    run_new(tmp_path, "demo-capability", monkeypatch)
    manifest = load_yaml_strict((tmp_path / "demo-capability" / "capability.yaml").read_text())
    assert manifest["metadata"]["template_version"] == scaffold.TEMPLATE_VERSION
    assert manifest["metadata"]["name"] == "demo-capability"


def test_referenced_io_schemas_exist_inside_project_and_are_valid(tmp_path, monkeypatch):
    run_new(tmp_path, "demo-capability", monkeypatch)
    project = (tmp_path / "demo-capability").resolve()
    manifest = load_yaml_strict((project / "capability.yaml").read_text())
    for section in ("inputs", "outputs"):
        path = (project / manifest["spec"][section]["schema"]).resolve()
        assert path.is_relative_to(project) and path.is_file()
        Draft202012Validator.check_schema(json.loads(path.read_text()))


def test_starter_defaults_are_flagged_for_review():
    files = scaffold.render("demo-capability")
    manifest_text = files["capability.yaml"].decode()
    readme = files["README.md"].decode()
    assert manifest_text.count("STARTER DEFAULT") >= 3
    assert "NOT a safe default" in manifest_text
    assert "not** a" in readme and "before using any real data" in readme


# --------------------------------------------------------------------------
# Determinism
# --------------------------------------------------------------------------


def test_render_is_deterministic_in_memory():
    assert scaffold.render("demo-capability") == scaffold.render("demo-capability")


def test_two_generations_are_byte_for_byte_identical(tmp_path, monkeypatch):
    first, second = tmp_path / "one", tmp_path / "two"
    first.mkdir()
    second.mkdir()
    assert run_new(first, "demo-capability", monkeypatch).exit_code == 0
    assert run_new(second, "demo-capability", monkeypatch).exit_code == 0
    for relative in EXPECTED_TREE:
        assert (first / "demo-capability" / relative).read_bytes() == (
            second / "demo-capability" / relative
        ).read_bytes()


def test_generation_is_identical_across_processes_and_hash_seeds(tmp_path):
    digests = []
    for seed in ("0", "1"):
        cwd = tmp_path / f"seed-{seed}"
        cwd.mkdir()
        env = {**os.environ, "PYTHONHASHSEED": seed, "PYTHONPATH": str(LAB_ROOT / "src")}
        completed = subprocess.run(
            [sys.executable, "-m", "golden_path", "new", "demo-capability"],
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert completed.returncode == 0, completed.stderr
        digests.append(tree_digest(cwd / "demo-capability"))
    assert digests[0] == digests[1]


def test_generated_content_has_no_environment_values(tmp_path, monkeypatch):
    run_new(tmp_path, "demo-capability", monkeypatch)
    forbidden = [str(tmp_path), str(Path.home()), str(LAB_ROOT)]
    forbidden += [v for v in (getpass.getuser(), socket.gethostname()) if len(v) >= 4]
    for path in (tmp_path / "demo-capability").rglob("*"):
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        for value in forbidden:
            assert value not in text, f"{value!r} leaked into {path.name}"
        assert "\r" not in text
        assert not re.search(r"\d{4}-\d{2}-\d{2}", text), f"date-like value in {path.name}"
        assert not re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-", text), f"uuid in {path.name}"


def test_generation_works_with_network_disabled(tmp_path, monkeypatch):
    def no_network(*args, **kwargs):
        raise AssertionError("network access attempted during generation")

    monkeypatch.setattr(socket, "socket", no_network)
    monkeypatch.setattr(socket, "create_connection", no_network)
    assert run_new(tmp_path, "demo-capability", monkeypatch).exit_code == 0


# --------------------------------------------------------------------------
# Overwrite protection and transactional writes
# --------------------------------------------------------------------------


def _existing_empty_dir(path: Path):
    path.mkdir()


def _existing_project(path: Path):
    path.mkdir()
    (path / "capability.yaml").write_text("team edits\n")


def _existing_file(path: Path):
    path.write_text("not a directory\n")


def _existing_symlink_to_dir(path: Path):
    target = path.parent / "elsewhere"
    target.mkdir()
    path.symlink_to(target)


def _dangling_symlink(path: Path):
    path.symlink_to(path.parent / "does-not-exist")


@pytest.mark.parametrize(
    "setup",
    [_existing_empty_dir, _existing_project, _existing_file, _existing_symlink_to_dir, _dangling_symlink],
    ids=lambda fn: fn.__name__.lstrip("_"),
)
def test_existing_destination_is_refused_and_untouched(tmp_path, monkeypatch, setup):
    setup(tmp_path / "demo-capability")
    before = snapshot(tmp_path)
    result = run_new(tmp_path, "demo-capability", monkeypatch)
    assert result.exit_code == 1
    assert "refusing to overwrite" in result.output
    assert snapshot(tmp_path) == before


def test_second_generation_leaves_first_project_untouched(tmp_path, monkeypatch):
    assert run_new(tmp_path, "demo-capability", monkeypatch).exit_code == 0
    (tmp_path / "demo-capability" / "capability.yaml").write_text("product team edit\n")
    before = snapshot(tmp_path)
    assert run_new(tmp_path, "demo-capability", monkeypatch).exit_code == 1
    assert snapshot(tmp_path) == before


def test_force_flag_does_not_exist(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["new", "demo-capability", "--force"])
    assert result.exit_code == 2
    assert list(tmp_path.iterdir()) == []


def test_failed_write_removes_only_the_directory_this_run_created(tmp_path):
    sibling = tmp_path / "sibling"
    sibling.mkdir()
    destination = tmp_path / "demo-capability"
    # "a" is written as a file, so creating "a/b" must fail mid-write.
    with pytest.raises(OSError):
        scaffold.write(destination, {"a": b"x", "a/b": b"y"})
    assert not destination.exists()
    assert sibling.is_dir()


def test_missing_parent_directory_is_not_created(tmp_path):
    destination = tmp_path / "missing-parent" / "demo-capability"
    with pytest.raises(FileNotFoundError):
        scaffold.write(destination, scaffold.render("demo-capability"))
    assert not (tmp_path / "missing-parent").exists()


def test_template_that_violates_contract_fails_before_writing(tmp_path, monkeypatch):
    broken_root = tmp_path / "templates"
    shutil.copytree(scaffold.TEMPLATES_ROOT, broken_root)
    manifest = broken_root / scaffold.TEMPLATE_ID / scaffold.TEMPLATE_VERSION / "capability.yaml.j2"
    manifest.write_text(manifest.read_text().replace("max_model_requests: 2", "max_model_requests: 0"))
    monkeypatch.setattr(scaffold, "TEMPLATES_ROOT", broken_root)

    workdir = tmp_path / "work"
    workdir.mkdir()
    result = run_new(workdir, "demo-capability", monkeypatch)
    assert result.exit_code == 3
    assert "max_model_requests" in result.output
    assert list(workdir.iterdir()) == []


# --------------------------------------------------------------------------
# Packaging
# --------------------------------------------------------------------------


def test_console_script_is_declared():
    pyproject = tomllib.loads((LAB_ROOT / "pyproject.toml").read_text())
    assert pyproject["project"]["scripts"] == {"ai-golden-path": "golden_path.cli:app"}
    assert not any(dep.lower().startswith("setuptools") for dep in pyproject["project"]["dependencies"])
