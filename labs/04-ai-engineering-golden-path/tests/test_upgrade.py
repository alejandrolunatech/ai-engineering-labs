"""Phase 8: template upgrades, exercised on the REAL capability@0.1.0 -> 0.2.0 edge.

Projects are real historical renders (scaffold.render(name, "0.1.0")), written
the same way `new` writes. The CLI runs in-process on cwd; generated 0.2.0
code runs only in subprocesses with golden_path import-blocked.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator
from typer.testing import CliRunner

from golden_path import scaffold
from golden_path import upgrade as upgrades
from golden_path.cli import app

NAME = "upgrade-demo"
SOURCE, TARGET = "0.1.0", "0.2.0"
runner = CliRunner()


def make_project(parent: Path, version: str = SOURCE, name: str = NAME) -> Path:
    destination = parent / name
    scaffold.write(destination, scaffold.render(name, version))
    return destination


def tree_state(root: Path) -> dict[str, str]:
    """Everything under root (files, dirs, symlinks), without following links."""
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


def provenance(project: Path) -> str:
    return yaml.safe_load((project / "capability.yaml").read_text())["metadata"]["template_version"]


def upgrade_cli(project: Path, monkeypatch, *args: str):
    monkeypatch.chdir(project)
    return runner.invoke(app, ["upgrade", *args])


def edit(path: Path, old: str, new: str) -> None:
    text = path.read_text()
    assert old in text, old
    path.write_text(text.replace(old, new, 1))


def actions(plan) -> dict[str, tuple[str, str]]:
    return {a.path: (a.action, a.reason) for a in plan.actions}


def observe_writes(monkeypatch, project: Path, before_write=None) -> list[tuple[str, str, str]]:
    """Wrap BOTH write primitives (ADD: _create_new, UPDATE: _replace).

    Records (kind, path, provenance-before) for every write attempt, and calls
    before_write(n, kind, relative) first, which may raise or act on the tree.
    """
    seen: list[tuple[str, str, str]] = []
    real_create, real_replace = upgrades._create_new, upgrades._replace

    def record(kind, path):
        relative = Path(path).relative_to(project).as_posix()
        seen.append((kind, relative, provenance(project)))
        if before_write:
            before_write(len(seen), kind, relative)

    def create(path, content):
        record("add", path)
        real_create(path, content)

    def replace(temp, path):
        record("update", path)
        real_replace(temp, path)

    monkeypatch.setattr(upgrades, "_create_new", create)
    monkeypatch.setattr(upgrades, "_replace", replace)
    return seen


@pytest.fixture
def project(tmp_path) -> Path:
    return make_project(tmp_path)


# --- platform-authored compatibility, backed by evidence -------------------------------------------


def test_exactly_one_platform_authored_edge():
    assert list(upgrades.UPGRADE_EDGES) == [(SOURCE, TARGET)]
    edge = upgrades.UPGRADE_EDGES[(SOURCE, TARGET)]
    assert (edge.contract_compatibility, edge.template_compatibility) == ("compatible", "breaking")
    assert set(edge.rationale_codes) <= set(upgrades.RATIONALE)


def test_evidence_contract_compatible_source_manifest_validates_against_target_snapshot():
    source_manifest = yaml.safe_load(scaffold.render(NAME, SOURCE)["capability.yaml"])
    target = scaffold.render(NAME, TARGET)
    snapshot = json.loads(target["platform/capability.schema.json"])
    assert source_manifest["api_version"] == yaml.safe_load(target["capability.yaml"])["api_version"] == "ai.platform/v1"
    assert list(Draft202012Validator(snapshot).iter_errors(source_manifest)) == []


def test_evidence_template_breaking_old_manifest_fails_target_runtime(tmp_path, blocked_env):
    target = make_project(tmp_path, TARGET)
    ok = subprocess.run([sys.executable, "src/capability.py", "fixtures/sample_input.json"], cwd=target,
                        env=blocked_env, capture_output=True, text=True)
    assert ok.returncode == 0, ok.stderr
    (target / "capability.yaml").write_bytes(scaffold.render(NAME, SOURCE)["capability.yaml"])
    old = subprocess.run([sys.executable, "src/capability.py", "fixtures/sample_input.json"], cwd=target,
                         env=blocked_env, capture_output=True, text=True)
    assert old.returncode == 3
    assert "unknown adapter 'default'" in json.loads(old.stderr)["message"]


def test_generated_project_records_its_source_template_version(project):
    assert provenance(project) == SOURCE
    assert sorted(p.relative_to(project).as_posix() for p in project.rglob("*") if p.is_file()) == [
        "README.md", "capability.yaml", "schemas/input.schema.json", "schemas/output.schema.json",
    ]


# --- classifier ----------------------------------------------------------------------------------------

B, T, X = b"base", b"target", b"team"
A, N = upgrades.ABSENT, upgrades.NOT_REGULAR


@pytest.mark.parametrize(
    ("base", "current", "target", "expected"),
    [
        (B, B, T, ("update", "unmodified_upstream_changed")),
        (B, X, B, ("preserve", "product_modified")),
        (B, A, B, ("preserve", "product_deleted")),
        (B, T, T, ("already_target", "current_matches_target")),
        (B, B, B, ("already_target", "unchanged")),
        (None, A, T, ("add", "new_in_target")),
        (None, T, T, ("already_target", "current_matches_target")),
        (None, X, T, ("conflict", "target_path_collision")),
        (B, X, T, ("conflict", "modified_both")),
        (B, A, T, ("conflict", "product_deleted_upstream_changed")),
        (B, B, None, ("delete", "removed_in_target")),
        (B, A, None, ("already_target", "already_removed")),
        (B, X, None, ("conflict", "modified_removed_upstream")),
        (B, N, T, ("conflict", "not_regular_file")),
        (B, N, B, ("conflict", "not_regular_file")),
        (None, N, T, ("conflict", "not_regular_file")),
    ],
)
def test_classifier_truth_table(base, current, target, expected):
    assert upgrades.classify(base, current, target) == expected


# --- clean upgrade (the canonical automatic success case) ----------------------------------------------


def test_clean_dry_run_is_breaking_visible_and_writes_nothing(project, monkeypatch):
    before = tree_state(project)
    result = upgrade_cli(project, monkeypatch, "--to", TARGET)
    assert result.exit_code == 0, result.output
    out = result.stdout
    assert out.startswith(f"BREAKING upgrade {NAME}: capability@0.1.0 -> capability@0.2.0\n")
    for line in ("contract: compatible", "template: breaking", "conflicts: 0", "status: ready",
                 "files changed by apply: 10", "dry run: nothing was written"):
        assert line in out
    for path in ("src/capability.py", "src/contracts.py", "src/model_adapter.py", "tests/test_capability.py",
                 "fixtures/sample_input.json", "requirements.txt", "pyproject.toml", "platform/capability.schema.json"):
        assert f"ADD             {path}" in out
    assert "UPDATE          README.md" in out and "UPDATE          capability.yaml" in out
    assert "ALREADY_TARGET  schemas/output.schema.json" in out
    assert tree_state(project) == before
    assert provenance(project) == SOURCE


def test_clean_apply_matches_fresh_target_render_and_target_is_healthy(project, monkeypatch, blocked_env):
    result = upgrade_cli(project, monkeypatch, "--to", TARGET, "--apply")
    assert result.exit_code == 0, result.output
    assert "applied: 10 file(s); capability.yaml written last" in result.stdout
    assert provenance(project) == TARGET

    fresh = scaffold.render(NAME, TARGET)
    managed = set(fresh) | set(scaffold.render(NAME, SOURCE))
    assert {p: (project / p).read_bytes() for p in sorted(managed)} == fresh
    assert (project / "platform/capability.schema.json").read_bytes() == scaffold.CAPABILITY_SCHEMA_PATH.read_bytes()

    # Target health, using only checks that existed in capability@0.2.0 (no ai-capability verify).
    snapshot = json.loads((project / "platform/capability.schema.json").read_text())
    assert list(Draft202012Validator(snapshot).iter_errors(yaml.safe_load((project / "capability.yaml").read_text()))) == []
    run = subprocess.run([sys.executable, "src/capability.py", "fixtures/sample_input.json"], cwd=project,
                         env=blocked_env, capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    assert json.loads(run.stdout)["model"]["declared_adapter"] == "fake"
    tests = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"], cwd=project,
                           env=blocked_env, capture_output=True, text=True)
    assert tests.returncode == 0, tests.stdout + tests.stderr

    again = upgrade_cli(project, monkeypatch, "--to", TARGET)
    assert again.exit_code == 0 and "status: up_to_date" in again.stdout


def test_provenance_is_written_last(project, monkeypatch):
    seen = observe_writes(monkeypatch, project)
    upgrades.apply_plan(project, upgrades.plan_upgrade(project, TARGET))
    assert len(seen) == 10 and seen[-1][:2] == ("update", "capability.yaml")
    assert sum(kind == "add" for kind, _, _ in seen) == 8  # every ADD used exclusive creation
    assert all(version == SOURCE for _, _, version in seen)  # source until the very last write
    assert provenance(project) == TARGET


def test_replanning_after_partial_writes_converges(project):
    plan = upgrades.plan_upgrade(project, TARGET)
    for item in plan.writes[:3]:  # as if a crash happened after three writes
        path = project / item.path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(plan.target_files[item.path])
    assert provenance(project) == SOURCE
    replanned = upgrades.plan_upgrade(project, TARGET)
    assert replanned.status == "ready" and len(replanned.writes) == len(plan.writes) - 3
    upgrades.apply_plan(project, replanned)
    assert provenance(project) == TARGET


# --- product edits are never silently overwritten ---------------------------------------------------------


def _team_edits(project: Path) -> None:
    schema_path = project / "schemas/output.schema.json"
    schema = json.loads(schema_path.read_text())
    schema["properties"]["team_reviewer"] = {"type": "string"}  # valid, product-specific
    schema_path.write_text(json.dumps(schema, indent=2) + "\n")
    with (project / "README.md").open("a") as handle:
        handle.write("\n## Team notes\n\nTEAM-NOTE-MARKER: owned by the product team.\n")


def test_product_edits_preserve_and_conflict_and_apply_refuses(project, monkeypatch):
    _team_edits(project)
    before = tree_state(project)
    plan = upgrades.plan_upgrade(project, TARGET)
    assert actions(plan)["schemas/output.schema.json"] == ("preserve", "product_modified")
    assert actions(plan)["README.md"] == ("conflict", "modified_both")
    assert plan.status == "blocked"

    dry = upgrade_cli(project, monkeypatch, "--to", TARGET)
    assert dry.exit_code == 1
    assert "status: blocked (manual_resolution_required)" in dry.stdout
    assert tree_state(project) == before

    applied = upgrade_cli(project, monkeypatch, "--to", TARGET, "--apply")
    assert applied.exit_code == 1
    assert "refusing to apply: conflicts_present" in applied.stderr
    assert tree_state(project) == before  # every byte, every file, every directory
    assert provenance(project) == SOURCE


def test_capability_yaml_purpose_edit_is_a_conservative_file_level_conflict(project, monkeypatch):
    edit(project / "capability.yaml", "Starter capability from the golden-path", "Explains release notes for the payments team; starter")
    before = tree_state(project)
    plan = upgrades.plan_upgrade(project, TARGET)
    assert actions(plan)["capability.yaml"] == ("conflict", "modified_both")
    with pytest.raises(upgrades.ConflictsRefused):
        upgrades.apply_plan(project, plan)
    assert upgrade_cli(project, monkeypatch, "--to", TARGET, "--apply").exit_code == 1
    assert tree_state(project) == before
    assert provenance(project) == SOURCE


def test_target_path_collision_is_never_overwritten(project, monkeypatch):
    custom = b"# our own runtime, written before any upgrade\n"
    (project / "src").mkdir()
    (project / "src/capability.py").write_bytes(custom)
    plan = upgrades.plan_upgrade(project, TARGET)
    assert actions(plan)["src/capability.py"] == ("conflict", "target_path_collision")
    assert actions(plan)["src/contracts.py"] == ("add", "new_in_target")
    before = tree_state(project)
    assert upgrade_cli(project, monkeypatch, "--to", TARGET, "--apply").exit_code == 1
    assert (project / "src/capability.py").read_bytes() == custom
    assert tree_state(project) == before


def test_product_deletion_is_preserved_not_restored(project, monkeypatch):
    (project / "schemas/input.schema.json").unlink()
    plan = upgrades.plan_upgrade(project, TARGET)
    assert actions(plan)["schemas/input.schema.json"] == ("preserve", "product_deleted")
    assert plan.status == "ready"
    assert upgrade_cli(project, monkeypatch, "--to", TARGET, "--apply").exit_code == 0
    assert not (project / "schemas/input.schema.json").exists()
    assert provenance(project) == TARGET


def test_product_deletion_of_upstream_changed_file_conflicts(project):
    (project / "README.md").unlink()
    plan = upgrades.plan_upgrade(project, TARGET)
    assert actions(plan)["README.md"] == ("conflict", "product_deleted_upstream_changed")
    with pytest.raises(upgrades.ConflictsRefused):
        upgrades.apply_plan(project, plan)
    assert not (project / "README.md").exists()


def test_upstream_removal_is_planned_and_applied(project, monkeypatch):
    """No released edge removes a file, so the delete path uses a patched TARGET render."""
    real = scaffold.render

    def without_output_schema(name, version=None):
        files = real(name, version)
        if version == TARGET:
            del files["schemas/output.schema.json"]
        return files

    monkeypatch.setattr(upgrades.scaffold, "render", without_output_schema)
    plan = upgrades.plan_upgrade(project, TARGET)
    assert actions(plan)["schemas/output.schema.json"] == ("delete", "removed_in_target")
    upgrades.apply_plan(project, plan)
    assert not (project / "schemas/output.schema.json").exists()


# --- symlinks and unknown files ---------------------------------------------------------------------------------


def test_symlinks_are_never_followed(project, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (project / "src").symlink_to(outside, target_is_directory=True)
    readme_target = tmp_path / "outside-readme.md"
    readme_target.write_bytes((project / "README.md").read_bytes())
    (project / "README.md").unlink()
    (project / "README.md").symlink_to(readme_target)

    plan = upgrades.plan_upgrade(project, TARGET)
    for path in ("README.md", "src/capability.py", "src/contracts.py", "src/model_adapter.py"):
        assert actions(plan)[path] == ("conflict", "not_regular_file"), path
    with pytest.raises(upgrades.ConflictsRefused):
        upgrades.apply_plan(project, plan)
    assert list(outside.iterdir()) == []


def test_unknown_application_files_are_untouched_unread_and_unlisted(project, monkeypatch):
    secret = project / ".env"
    secret.write_text("API_TOKEN=do-not-read-me\n")
    (project / "notes").mkdir()
    (project / "notes/roadmap.md").write_text("private roadmap\n")
    secret.chmod(0o000)  # any attempt to read it would raise PermissionError
    read = []
    real = upgrades.read_current
    monkeypatch.setattr(upgrades, "read_current", lambda root, rel: read.append(rel) or real(root, rel))
    try:
        plan = upgrades.plan_upgrade(project, TARGET)
        dry = upgrade_cli(project, monkeypatch, "--to", TARGET, "--diff")
        applied = upgrade_cli(project, monkeypatch, "--to", TARGET, "--apply")
    finally:
        secret.chmod(0o600)
    assert set(read) <= set(scaffold.render(NAME, SOURCE)) | set(scaffold.render(NAME, TARGET))
    assert {a.path for a in plan.actions}.isdisjoint({".env", "notes/roadmap.md"})
    assert applied.exit_code == 0
    for output in (dry.output, applied.output):
        assert ".env" not in output and "roadmap" not in output and "do-not-read-me" not in output
    assert secret.read_text() == "API_TOKEN=do-not-read-me\n"
    assert (project / "notes/roadmap.md").read_text() == "private roadmap\n"


# --- apply safety: stale plan and injected failure ------------------------------------------------------------------


def test_stale_plan_aborts_and_rolls_back(project):
    before = tree_state(project)
    plan = upgrades.plan_upgrade(project, TARGET)
    late = project / "tests" / "test_capability.py"  # written after planning, applied late in path order
    late.parent.mkdir()
    late.write_text("# appeared after planning\n")
    with pytest.raises(upgrades.ApplyFailed) as failure:
        upgrades.apply_plan(project, plan)
    assert failure.value.code == "stale_plan" and failure.value.locations == ("tests/test_capability.py",)
    assert late.read_text() == "# appeared after planning\n"
    late.unlink()
    late.parent.rmdir()
    assert tree_state(project) == before  # earlier writes were rolled back
    assert provenance(project) == SOURCE


def test_late_add_collision_is_never_overwritten(project, monkeypatch):
    """TOCTOU: the destination appears AFTER planning and after the stale recheck,
    immediately before the upgrade's own ADD. Exclusive creation must refuse it."""
    before = tree_state(project)
    plan = upgrades.plan_upgrade(project, TARGET)
    assert actions(plan)["src/capability.py"] == ("add", "new_in_target")
    injected = b"# created by another process between recheck and ADD\n"
    replaced = []
    real_replace = os.replace
    monkeypatch.setattr(upgrades.os, "replace", lambda *a: replaced.append(a) or real_replace(*a))

    def other_process(n, kind, relative):
        if relative == "src/capability.py":
            (project / relative).write_bytes(injected)

    seen = observe_writes(monkeypatch, project, other_process)
    with pytest.raises(upgrades.ApplyFailed) as failure:
        upgrades.apply_plan(project, plan)
    # The apply created src/ for this ADD; it now holds the other process's file, so
    # rollback reports the directory it could not remove instead of deleting foreign content.
    assert (failure.value.code, failure.value.locations) == ("stale_plan", ("src/capability.py", "rollback incomplete: src"))
    assert [relative for _, relative, _ in seen][:6] == [
        "README.md", "fixtures/sample_input.json", "platform/capability.schema.json",
        "pyproject.toml", "requirements.txt", "src/capability.py",
    ]  # five earlier writes happened, then the refused ADD
    assert (project / "src/capability.py").read_bytes() == injected  # exactly unchanged
    assert not any(str(dst).endswith("src/capability.py") for _, dst in replaced)  # never replaced
    assert provenance(project) == SOURCE
    (project / "src/capability.py").unlink()
    (project / "src").rmdir()
    assert tree_state(project) == before  # all earlier upgrade writes rolled back


def test_injected_write_failure_rolls_back_completely(project, monkeypatch):
    before = tree_state(project)

    def fail_fifth(n, kind, relative):
        if n == 5:
            raise OSError(28, "No space left on device (injected)")

    observe_writes(monkeypatch, project, fail_fifth)
    result = upgrade_cli(project, monkeypatch, "--to", TARGET, "--apply")
    assert result.exit_code == 1
    assert "apply_failed: OSError during apply; rolled back" in result.stderr
    assert "rollback incomplete" not in result.stderr
    assert tree_state(project) == before  # no added files, no temp files, no new dirs, README restored
    assert provenance(project) == SOURCE


# --- supported edges and preflight --------------------------------------------------------------------------------


@pytest.mark.parametrize(("source", "target", "code"), [
    (SOURCE, "0.3.0", "unsupported_upgrade_edge"),
    (SOURCE, "0.6.0", "unsupported_upgrade_edge"),  # no automatic chaining
    ("0.2.0", "0.3.0", "unsupported_upgrade_edge"),
    (TARGET, SOURCE, "unsupported_upgrade_edge"),  # downgrade
    (SOURCE, "9.9.9", "unknown_target_version"),
])
def test_unsupported_edges_exit_2_and_write_nothing(tmp_path, monkeypatch, source, target, code):
    project = make_project(tmp_path, source)
    before = tree_state(project)
    result = upgrade_cli(project, monkeypatch, "--to", target)
    assert result.exit_code == 2
    assert f"error: {code}" in result.stderr
    assert tree_state(project) == before


def test_missing_to_is_a_usage_error(project, monkeypatch):
    assert upgrade_cli(project, monkeypatch).exit_code == 2


@pytest.mark.parametrize("version", [SOURCE, TARGET])
def test_source_equal_to_target_is_up_to_date(tmp_path, monkeypatch, version):
    project = make_project(tmp_path, version)
    before = tree_state(project)
    for args in (("--to", version), ("--to", version, "--apply")):
        result = upgrade_cli(project, monkeypatch, *args)
        assert result.exit_code == 0 and "status: up_to_date" in result.stdout
    assert tree_state(project) == before


def _manifest_edit(old, new):
    return lambda p: edit(p / "capability.yaml", old, new)


@pytest.mark.parametrize(("mutate", "code", "hidden"), [
    (lambda p: (p / "capability.yaml").unlink(), "manifest_missing", None),
    (_manifest_edit("api_version: ai.platform/v1", "api_version: ai.platform/v2"), "incompatible_contract", "ai.platform/v2"),
    (_manifest_edit("kind: Capability", "kind: Workflow"), "incompatible_contract", "Workflow"),
    (_manifest_edit("kind: Capability", "kind: Capability\nkind: Capability"), "manifest_unparseable", None),
    (_manifest_edit("api_version: ai.platform/v1", "api_version: [unclosed"), "manifest_unparseable", None),
    (_manifest_edit('template_version: "0.1.0"', 'template_version: "0.9.0"'), "unknown_source_version", "0.9.0"),
    (_manifest_edit('template_version: "0.1.0"', "template_version: 0.1"), "invalid_provenance", None),
    (_manifest_edit("profile: balanced", "profile: turbo-secret-tier"), "manifest_contract_violation", "turbo-secret-tier"),
    (_manifest_edit(f'name: "{NAME}"', 'name: "Bad Name"'), "manifest_contract_violation", "Bad Name"),
])
def test_preflight_failures_exit_3_write_nothing_and_echo_no_values(project, monkeypatch, mutate, code, hidden):
    mutate(project)
    before = tree_state(project)
    for args in (("--to", TARGET), ("--to", TARGET, "--apply")):
        result = upgrade_cli(project, monkeypatch, *args)
        assert result.exit_code == 3, result.output
        assert f"error: {code}" in result.stderr
        assert result.stdout == ""
        if hidden:
            assert hidden not in result.output
    assert tree_state(project) == before


@pytest.mark.parametrize(("mutate", "code"), [
    (lambda p: edit(p / "platform/capability.schema.json", '"maximum": 10', '"maximum": 1000'), "platform_snapshot_modified"),
    (lambda p: (p / "platform/capability.schema.json").unlink(), "platform_snapshot_missing"),
])
def test_source_platform_snapshot_must_match_released_contract(tmp_path, monkeypatch, mutate, code):
    project = make_project(tmp_path, TARGET)  # 0.2.0 is the first version with a local snapshot
    mutate(project)
    result = upgrade_cli(project, monkeypatch, "--to", TARGET)
    assert result.exit_code == 3 and f"error: {code}" in result.stderr


def test_source_0_1_0_is_validated_against_the_released_canonical_contract():
    path, _ = upgrades._contract_for(SOURCE)
    assert scaffold.PLATFORM_FILES_BY_TEMPLATE_VERSION[SOURCE] == {}
    assert path == scaffold.CAPABILITY_SCHEMA_PATH


def test_target_render_must_carry_the_released_snapshot(project, monkeypatch):
    real = scaffold.render

    def tampered(name, version=None):
        files = real(name, version)
        if version == TARGET:
            files["platform/capability.schema.json"] = files["platform/capability.schema.json"].replace(b'"maximum": 10', b'"maximum": 11')
        return files

    monkeypatch.setattr(upgrades.scaffold, "render", tampered)
    before = tree_state(project)
    result = upgrade_cli(project, monkeypatch, "--to", TARGET, "--apply")
    assert result.exit_code == 3 and "platform_template_invalid" in result.stderr
    assert tree_state(project) == before


# --- presentation --------------------------------------------------------------------------------------------------


def test_diff_shows_bounded_platform_changes_never_product_content(project, monkeypatch):
    _team_edits(project)
    result = upgrade_cli(project, monkeypatch, "--to", TARGET, "--diff")
    out = result.stdout
    assert "-    adapter: default" in out and "+    adapter: fake" in out
    assert "--- capability.yaml (capability@0.1.0)" in out
    assert "TEAM-NOTE-MARKER" not in out and "team_reviewer" not in out
    assert "your working-tree file is not shown" in out
    assert "... diff truncated:" not in out.split("README.md")[0]
    target = scaffold.render(NAME, TARGET)["src/capability.py"]
    assert f"target: {len(target)} bytes, sha256 {hashlib.sha256(target).hexdigest()}" in out


def test_diffs_are_deterministically_capped(project, monkeypatch):
    monkeypatch.setattr(upgrades, "DIFF_MAX_LINES", 5)
    out = upgrade_cli(project, monkeypatch, "--to", TARGET, "--diff").stdout
    readme = out.split("UPDATE          README.md")[1].split("UPDATE          capability.yaml")[0]
    shown = readme.splitlines()[1:]  # [0] is the rest of the action row
    assert len(shown) == 6 and shown[-1].startswith("    ... diff truncated: ")


@pytest.mark.parametrize("args", [(), ("--diff",)])
def test_plan_bytes_are_identical_across_runs_and_hash_seeds(project, args, tmp_path):
    env = {k: v for k, v in os.environ.items() if k != "PYTHONHASHSEED"}
    command = [sys.executable, "-m", "golden_path", "upgrade", "--to", TARGET, *args]
    runs = [subprocess.run(command, cwd=project, env={**env, "PYTHONHASHSEED": seed}, capture_output=True)
            for seed in ("0", "1", "2")]
    assert all(r.returncode == 0 for r in runs), runs[0].stderr
    assert runs[0].stdout == runs[1].stdout == runs[2].stdout
    assert str(tmp_path).encode() not in runs[0].stdout
