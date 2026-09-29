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
# Tree produced by the CURRENT template version (capability@0.5.0).
EXPECTED_TREE = [
    "README.md",
    "capability.yaml",
    "evals/cases.yaml",
    "evals/evaluator.py",
    "fixtures/sample_input.json",
    "platform/capability.schema.json",
    "platform/eval-report.schema.json",
    "platform/eval-suite.schema.json",
    "platform/pricing.schema.json",
    "platform/telemetry-record.schema.json",
    "pricing.yaml",
    "pyproject.toml",
    "requirements.txt",
    "schemas/input.schema.json",
    "schemas/output.schema.json",
    "src/capability.py",
    "src/contracts.py",
    "src/cost.py",
    "src/model_adapter.py",
    "src/policy.py",
    "src/telemetry.py",
    "src/tools.py",
    "tests/test_capability.py",
    "tests/test_evals.py",
    "tests/test_telemetry.py",
    "tests/test_tools.py",
]

# Released templates are immutable. These digests pin each released version
# exactly as committed (0.1.0 in Phase 2, 0.2.0 in Phase 3, 0.3.0 in Phase 4,
# 0.4.0 in Phase 5); any change to
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
    "0.4.0": {
        "README.md.j2": "fffd6abe07276c222888d57436662f3934a880a588c63fe2ac7884bddaa1cd2b",
        "capability.yaml.j2": "a4fb57e4cc11dc0a3b4568f31ec4fd56a31a5570b654768d31ca43c30dc04f53",
        "evals/cases.yaml": "5726963364a07b5eddcebecec9b7c4ae914a429256632f1b4da60cd643347187",
        "evals/evaluator.py": "b13d6ea402660a533baa522e838d17028d639fd66183c28539cbdbec502381af",
        "fixtures/sample_input.json": "4c20a26777581c984e430aaf892c63c67c94ab686beba13c03a2d51105e0c6f3",
        "pricing.yaml": "8cf0d2d8b4c427bc4744cb87d84d89ad9889f239913a122fe8fa2c34eb90305e",
        "pyproject.toml": "0e0b0ea22f9940538eca1098ddf495964117d382ec5bf608016120aae7e9f393",
        "requirements.txt": "bcb619e79ee54b01399e61246ecf9d186224c4ac0bdb9be656bbf77314689d99",
        "schemas/input.schema.json": "30a49ee496efc3a7f55cf50bc74de7d16b9852d8c80c58b03d02b5f98e2b716d",
        "schemas/output.schema.json": "64b84ca89036e3c2af93c3184cfac927e468caedd314ae7463e9b5dcc785f029",
        "src/capability.py": "c70e087a20dfd360b0dd91c503be5b3b84b5c1b13ad064516153aeb18c7eaa49",
        "src/contracts.py": "fce6d0325741517af89314958bfc9f7d36ad6a8da288555eabf5ba33991fa739",
        "src/cost.py": "1fd08246145ea28cca7ad68915f2969f98d52c4504d8c05b12e288c27d38b63d",
        "src/model_adapter.py": "e0ac44790feee24f6664d8e4e8bd4ec7e66af50f343a9a34b78fde04db598a82",
        "src/telemetry.py": "cf8d5e651ba9d663ec89412743c10a185262da086ba58e41aafcb82a7be07934",
        "tests/test_capability.py": "9f7c9fd92cd410ff4d64f462c319617292dad6344625353c748195705d27b281",
        "tests/test_evals.py": "7b35b2fa42a77312a762d58ce70902ba3fbca2e5da210b1e17feb1a542d99f59",
        "tests/test_telemetry.py": "4dce1676aed408fd4f046fdcb9e5c26ac278a29c718ac52f1175c4422c9902ae",
    },
    "0.3.0": {
        "README.md.j2": "9c1ef2437528be233f160b4b6706c7861ee827b5a6c4c7f4cca18d9730faa550",
        "capability.yaml.j2": "91328b8530bd487df0cffb7ce8ad052bbbfe3563c0cf71a49d8c20c58eaae35e",
        "evals/cases.yaml": "5726963364a07b5eddcebecec9b7c4ae914a429256632f1b4da60cd643347187",
        "evals/evaluator.py": "2830953b6e04538a806897451653b707b9c6795766bd1fafe30fb332347858e3",
        "fixtures/sample_input.json": "4c20a26777581c984e430aaf892c63c67c94ab686beba13c03a2d51105e0c6f3",
        "pyproject.toml": "0e0b0ea22f9940538eca1098ddf495964117d382ec5bf608016120aae7e9f393",
        "requirements.txt": "bcb619e79ee54b01399e61246ecf9d186224c4ac0bdb9be656bbf77314689d99",
        "schemas/input.schema.json": "30a49ee496efc3a7f55cf50bc74de7d16b9852d8c80c58b03d02b5f98e2b716d",
        "schemas/output.schema.json": "64b84ca89036e3c2af93c3184cfac927e468caedd314ae7463e9b5dcc785f029",
        "src/capability.py": "e929098ad461fb23a65e81c87f58a68d007c539c24218108e9f5882631a1d292",
        "src/contracts.py": "fd8835ea8d81e610c2748afc35e3ba97a19b7b3ac80632ef50e6d49c53652eba",
        "src/model_adapter.py": "f6da183af1b9aeb07e1336a615c7160c324e16f36780cb0c772e069681587371",
        "tests/test_capability.py": "9f7c9fd92cd410ff4d64f462c319617292dad6344625353c748195705d27b281",
        "tests/test_evals.py": "41eb7095dea528ac4c8c3dea656a5a75f3d51de8ac7a7fb640d490344b07dc34",
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
    assert root.name == scaffold.TEMPLATE_VERSION == "0.5.0"
    assert [p.relative_to(root).as_posix() for p in scaffold.template_sources()] == [
        "README.md.j2",
        "capability.yaml.j2",
        "evals/cases.yaml",
        "evals/evaluator.py",
        "fixtures/sample_input.json",
        "pricing.yaml",
        "pyproject.toml",
        "requirements.txt",
        "schemas/input.schema.json",
        "schemas/output.schema.json",
        "src/capability.py",
        "src/contracts.py",
        "src/cost.py",
        "src/model_adapter.py",
        "src/policy.py",
        "src/telemetry.py",
        "src/tools.py",
        "tests/test_capability.py",
        "tests/test_evals.py",
        "tests/test_telemetry.py",
        "tests/test_tools.py",
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


# --------------------------------------------------------------------------
# Platform-contract provenance: freezing template files is not enough
# --------------------------------------------------------------------------

# Released canonical contracts, pinned exactly as committed. A released
# contract is never edited: a change gets a new versioned file (telemetry v2).
FROZEN_CONTRACTS = {
    "capability.schema.json": "7a3abb6ef1eb5b5f5db0b4e5d0fefc9f21e24f1f8761d7381960a88f5801b6ac",
    "eval-report.schema.json": "43ec0b740ce43c2987ab012ac2e22802f3e5604a2c44e66c96fb64029eea3610",
    "eval-suite.schema.json": "4d38a26709012cfc5ff07dd00a3a36b2b9f243de985f0d47b12d513fd130bf83",
    "pricing.schema.json": "307d949a70fb3c9ee5c5791a5bcdc8b479b687811ee96b9a64503d241e7280b9",
    "telemetry-record.schema.json": "8e8dfd7c34c84d3963dd621342c9ec08ba59eeed4045b6d41e94008b9178e2e3",
    "telemetry-record.v2.schema.json": "52c861a6b35bdf1c0b68cc57bdc6733302226c5f44e860ddac0b58b8ea455b24",  # released in Phase 6
}


@pytest.mark.parametrize("filename", sorted(FROZEN_CONTRACTS))
def test_released_canonical_contract_is_frozen(filename):
    path = scaffold.LAB_ROOT / "schemas" / filename
    assert hashlib.sha256(path.read_bytes()).hexdigest() == FROZEN_CONTRACTS[filename]


def test_every_template_version_has_an_explicit_platform_snapshot_mapping():
    versions = sorted(p.name for p in (scaffold.TEMPLATES_ROOT / scaffold.TEMPLATE_ID).iterdir() if p.is_dir())
    assert sorted(scaffold.PLATFORM_FILES_BY_TEMPLATE_VERSION) == versions
    assert scaffold.PLATFORM_FILES is scaffold.PLATFORM_FILES_BY_TEMPLATE_VERSION[scaffold.TEMPLATE_VERSION]


def test_every_referenced_canonical_contract_is_pinned():
    referenced = {
        source.name for mapping in scaffold.PLATFORM_FILES_BY_TEMPLATE_VERSION.values() for source in mapping.values()
    }
    assert referenced <= set(FROZEN_CONTRACTS)
    assert {path.name for path in (scaffold.LAB_ROOT / "schemas").glob("*.json")} == set(FROZEN_CONTRACTS)


def test_historical_templates_keep_their_original_contracts():
    telemetry = "platform/telemetry-record.schema.json"
    mapping = scaffold.PLATFORM_FILES_BY_TEMPLATE_VERSION
    assert mapping["0.4.0"][telemetry].name == "telemetry-record.schema.json"  # v1
    assert mapping["0.5.0"][telemetry].name == "telemetry-record.v2.schema.json"
    assert telemetry not in mapping["0.3.0"] and "platform/pricing.schema.json" not in mapping["0.3.0"]
    assert set(mapping["0.3.0"]) == {
        "platform/capability.schema.json",
        "platform/eval-report.schema.json",
        "platform/eval-suite.schema.json",
    }
    assert set(mapping["0.2.0"]) == {"platform/capability.schema.json"}
    assert mapping["0.1.0"] == {}
