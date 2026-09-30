"""Template upgrades (Lab 04, Phase 8).

Three trees, compared path by path over union(BASE, TARGET) only:

  BASE     fresh render of the project's recorded template version
           (capability.yaml -> metadata.template_version) for its metadata.name
  CURRENT  the product team's working tree
  TARGET   fresh render of the requested target version for the same name

Without BASE a planner cannot tell a product-team edit from old template
content. BASE is reconstructable because rendering is deterministic and
released templates and contracts are SHA-pinned.

Flow: preflight -> render BASE -> render TARGET -> classify the whole union ->
complete plan -> refuse if any conflict -> apply. Dry-run is the default and
writes nothing. Everything here is deterministic: no model, no network, no
product code is executed, and files outside union(BASE, TARGET) are never read.

A conflict is a safe terminal outcome: the platform changed a path AND the
product team changed (or occupies) it, so automatic ownership ends there.
Phase 8 detects conflicts; it deliberately does not resolve them.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import os
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml
from jsonschema import Draft202012Validator

from golden_path import scaffold

MANIFEST = "capability.yaml"
DIFF_MAX_LINES = 200


# --------------------------------------------------------------------------
# Platform-authored upgrade metadata. Compatibility is DECLARED here by the
# platform, with evidence in tests; it is never inferred from a diff.
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class UpgradeEdge:
    source: str
    target: str
    contract_compatibility: Literal["compatible", "incompatible"]
    template_compatibility: Literal["compatible", "breaking"]
    rationale_codes: tuple[str, ...]


RATIONALE = {
    "api_version_unchanged": "both versions use the same ai.platform/v1 capability contract",
    "runtime_added": "the target adds executable runtime code, tests and dependencies",
    "contract_snapshot_added": "the target adds platform/capability.schema.json and validates against it at runtime",
    "default_adapter_unresolvable_in_target": "the source default adapter 'default' is not registered by the target runtime (it fails closed)",
    "declarations_become_enforced": "inert declarations become runtime behaviour (request budget enforced, non-empty tools refused)",
}

# Exactly one supported edge. No graph, no chaining, no downgrade.
UPGRADE_EDGES: dict[tuple[str, str], UpgradeEdge] = {
    ("0.1.0", "0.2.0"): UpgradeEdge(
        source="0.1.0",
        target="0.2.0",
        contract_compatibility="compatible",
        template_compatibility="breaking",
        rationale_codes=(
            "api_version_unchanged",
            "runtime_added",
            "contract_snapshot_added",
            "default_adapter_unresolvable_in_target",
            "declarations_become_enforced",
        ),
    ),
}


# --------------------------------------------------------------------------
# Errors. Each carries a constrained code and never echoes offending values.
# --------------------------------------------------------------------------


class UpgradeError(Exception):
    exit_code = 1

    def __init__(self, code: str, detail: str = "", locations: tuple[str, ...] = ()):
        self.code, self.detail, self.locations = code, detail, tuple(locations)
        super().__init__(code)

    def describe(self) -> str:
        text = self.code + (f": {self.detail}" if self.detail else "")
        return text + ("".join(f"\n  at {location}" for location in self.locations))


class UnsupportedUpgrade(UpgradeError):
    """Unknown target version or no supported edge (exit 2)."""

    exit_code = 2


class PreflightError(UpgradeError):
    """Source provenance or contract state cannot be trusted (exit 3)."""

    exit_code = 3


class ConflictsRefused(UpgradeError):
    """--apply on a plan containing conflicts. Nothing was written (exit 1)."""


class ApplyFailed(UpgradeError):
    """A write failed or the tree changed after planning; rolled back (exit 1)."""


# --------------------------------------------------------------------------
# Reading CURRENT without following symlinks.
# --------------------------------------------------------------------------

ABSENT = "absent"
NOT_REGULAR = "not_regular_file"


def read_current(root: Path, relative: str) -> bytes | str:
    """Bytes of a regular file at `relative`, ABSENT, or NOT_REGULAR.

    Every ancestor is lstat'ed: a symlinked or non-directory ancestor makes the
    path NOT_REGULAR, so a link can never redirect a read or a write outside
    the project. The file itself is opened with O_NOFOLLOW.
    """
    parts = relative.split("/")
    path = root
    for part in parts[:-1]:
        path = path / part
        try:
            mode = os.lstat(path).st_mode
        except FileNotFoundError:
            return ABSENT
        if not stat.S_ISDIR(mode):
            return NOT_REGULAR
    path = path / parts[-1]
    try:
        mode = os.lstat(path).st_mode
    except FileNotFoundError:
        return ABSENT
    if not stat.S_ISREG(mode):
        return NOT_REGULAR
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(fd, "rb") as handle:
        return handle.read()


def _fingerprint(state: bytes | str) -> str:
    return state if isinstance(state, str) else "sha256:" + hashlib.sha256(state).hexdigest()


# --------------------------------------------------------------------------
# Classification: a pure function of (BASE, CURRENT, TARGET) for one path.
# --------------------------------------------------------------------------

Action = Literal["add", "update", "preserve", "already_target", "delete", "conflict"]


def classify(base: bytes | None, current: bytes | str, target: bytes | None) -> tuple[Action, str]:
    if base is None and target is None:
        raise ValueError("path must exist in BASE or TARGET")
    if current == NOT_REGULAR:
        return "conflict", "not_regular_file"
    absent = current == ABSENT

    if target is None:  # upstream removed the path
        if absent:
            return "already_target", "already_removed"
        if current == base:
            return "delete", "removed_in_target"
        return "conflict", "modified_removed_upstream"

    if current == target:
        return "already_target", "unchanged" if base == target else "current_matches_target"

    if base is None:  # upstream adds the path
        return ("add", "new_in_target") if absent else ("conflict", "target_path_collision")

    if base == target:  # upstream unchanged: whatever the team did is theirs
        return "preserve", "product_deleted" if absent else "product_modified"

    # upstream changed the path
    if current == base:
        return "update", "unmodified_upstream_changed"
    if absent:
        return "conflict", "product_deleted_upstream_changed"
    return "conflict", "modified_both"


# --------------------------------------------------------------------------
# Preflight: trustworthy source state before anything is rendered or planned.
# --------------------------------------------------------------------------


class _UniqueKeyLoader(yaml.SafeLoader):
    pass


def _construct_unique_mapping(loader, node, deep=False):
    seen = set()
    for key_node, _ in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in seen:
            raise yaml.constructor.ConstructorError(None, None, "duplicate key", key_node.start_mark)
        seen.add(key)
    return yaml.SafeLoader.construct_mapping(loader, node, deep=deep)


_UniqueKeyLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_unique_mapping)


def _contract_for(version: str) -> tuple[Path, dict]:
    """The released canonical capability contract for a template version.

    0.1.0 generated no local snapshot, so the platform's pinned canonical v1
    contract is used directly. Later versions name theirs in
    PLATFORM_FILES_BY_TEMPLATE_VERSION (the same pinned canonical file).
    """
    path = scaffold.PLATFORM_FILES_BY_TEMPLATE_VERSION[version].get(
        "platform/capability.schema.json", scaffold.CAPABILITY_SCHEMA_PATH
    )
    return path, json.loads(path.read_text(encoding="utf-8"))


def _contract_errors(schema: dict, instance) -> tuple[str, ...]:
    return tuple(sorted({
        f"{'/'.join(map(str, e.absolute_path)) or '<root>'}: {e.validator}"
        for e in Draft202012Validator(schema).iter_errors(instance)
    }))


def read_manifest(root: Path) -> dict:
    """Parse CURRENT capability.yaml strictly and check contract identity and provenance."""
    raw = read_current(root, MANIFEST)
    if raw == ABSENT:
        raise PreflightError("manifest_missing", "no capability.yaml in this directory")
    if raw == NOT_REGULAR:
        raise PreflightError("manifest_not_regular_file")
    try:
        manifest = yaml.load(raw.decode("utf-8"), Loader=_UniqueKeyLoader)  # noqa: S506 - safe loader subclass
    except (UnicodeDecodeError, yaml.YAMLError):
        raise PreflightError("manifest_unparseable", "strict YAML parse failed (duplicate keys are rejected)") from None
    if not isinstance(manifest, dict):
        raise PreflightError("manifest_unparseable", "top level is not a mapping")

    canonical = scaffold.load_capability_schema()
    expected_api = canonical["properties"]["api_version"]["const"]
    expected_kind = canonical["properties"]["kind"]["const"]
    if manifest.get("api_version") != expected_api:
        raise PreflightError("incompatible_contract", f"api_version is not {expected_api}", ("api_version",))
    if manifest.get("kind") != expected_kind:
        raise PreflightError("incompatible_contract", f"kind is not {expected_kind}", ("kind",))

    metadata = manifest.get("metadata")
    version = metadata.get("template_version") if isinstance(metadata, dict) else None
    if not isinstance(version, str):
        raise PreflightError("invalid_provenance", "metadata.template_version is missing or not a string",
                             ("metadata/template_version",))
    if version not in scaffold.RELEASED_TEMPLATE_VERSIONS:
        raise PreflightError("unknown_source_version", "metadata.template_version is not a released template version",
                             ("metadata/template_version",))
    return manifest


def _check_source(root: Path, manifest: dict, source: str) -> str:
    """Contract validation, name and source platform snapshot integrity."""
    _, contract = _contract_for(source)
    errors = _contract_errors(contract, manifest)
    if errors:
        raise PreflightError("manifest_contract_violation", f"capability.yaml violates the capability@{source} contract",
                             errors)
    name = manifest["metadata"]["name"]
    try:
        scaffold.validate_name(name)
    except scaffold.InvalidNameError:
        raise PreflightError("invalid_name", "metadata.name is not a valid capability name", ("metadata/name",)) from None

    # A modified local snapshot is never trusted just because it exists.
    for relative, canonical in sorted(scaffold.PLATFORM_FILES_BY_TEMPLATE_VERSION[source].items()):
        current = read_current(root, relative)
        if current == ABSENT:
            raise PreflightError("platform_snapshot_missing", "a released platform snapshot is missing", (relative,))
        if current != canonical.read_bytes():
            raise PreflightError("platform_snapshot_modified",
                                 "a platform snapshot differs from the released canonical contract", (relative,))
    return name


def _check_target_render(files: dict[str, bytes], target: str) -> None:
    """The TARGET render must carry the released canonical snapshots and satisfy them."""
    for relative, canonical in scaffold.PLATFORM_FILES_BY_TEMPLATE_VERSION[target].items():
        if files.get(relative) != canonical.read_bytes():
            raise scaffold.TemplateContractError(f"target render lacks the released snapshot {relative}")
    manifest = yaml.safe_load(files[MANIFEST])
    _, contract = _contract_for(target)
    if _contract_errors(contract, manifest) or manifest["metadata"]["template_version"] != target:
        raise scaffold.TemplateContractError("target render does not satisfy its own contract")


# --------------------------------------------------------------------------
# Planning
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class FileAction:
    path: str
    action: Action
    reason: str
    planned_current: str  # fingerprint of CURRENT at planning time (never content)


@dataclass(frozen=True)
class Plan:
    name: str
    source: str
    target: str
    edge: UpgradeEdge | None
    actions: tuple[FileAction, ...]
    base: dict[str, bytes]
    target_files: dict[str, bytes]

    @property
    def conflicts(self) -> tuple[FileAction, ...]:
        return tuple(a for a in self.actions if a.action == "conflict")

    @property
    def writes(self) -> tuple[FileAction, ...]:
        """Operations in apply order: path order, capability.yaml (provenance) LAST."""
        ops = [a for a in self.actions if a.action in ("add", "update", "delete")]
        return tuple(sorted(ops, key=lambda a: (a.path == MANIFEST, a.path)))

    @property
    def status(self) -> str:
        if self.source == self.target:
            return "up_to_date"
        return "blocked" if self.conflicts else "ready"


def plan_upgrade(root: Path, target: str) -> Plan:
    if target not in scaffold.RELEASED_TEMPLATE_VERSIONS:
        raise UnsupportedUpgrade("unknown_target_version", "--to is not a released template version")
    manifest = read_manifest(root)
    source = manifest["metadata"]["template_version"]
    edge = None
    if source != target:
        edge = UPGRADE_EDGES.get((source, target))
        if edge is None:
            supported = ", ".join(f"{s} -> {t}" for s, t in sorted(UPGRADE_EDGES))
            raise UnsupportedUpgrade("unsupported_upgrade_edge",
                                     f"capability@{source} -> capability@{target}; supported: {supported}")
    name = _check_source(root, manifest, source)
    if edge is None:  # source == target: nothing to plan, nothing to write
        return Plan(name, source, target, None, (), {}, {})

    base = scaffold.render(name, source)
    target_files = scaffold.render(name, target)
    _check_target_render(target_files, target)

    actions = []
    for relative in sorted(set(base) | set(target_files)):
        current = read_current(root, relative)
        action, reason = classify(base.get(relative), current, target_files.get(relative))
        actions.append(FileAction(relative, action, reason, _fingerprint(current)))
    return Plan(name, source, target, edge, tuple(actions), base, target_files)


# --------------------------------------------------------------------------
# Presentation (deterministic: no timestamps, IDs or absolute paths)
# --------------------------------------------------------------------------


def _describe_bytes(content: bytes) -> str:
    return f"{len(content)} bytes, sha256 {hashlib.sha256(content).hexdigest()}"


def _bounded_diff(plan: Plan, relative: str) -> list[str]:
    """BASE -> TARGET only: both sides are platform renders, never product content."""
    old, new = plan.base[relative], plan.target_files[relative]
    try:
        old_text, new_text = old.decode("utf-8"), new.decode("utf-8")
    except UnicodeDecodeError:
        return [f"    (binary) {_describe_bytes(old)} -> {_describe_bytes(new)}"]
    lines = list(difflib.unified_diff(
        old_text.splitlines(), new_text.splitlines(),
        f"{relative} (capability@{plan.source})", f"{relative} (capability@{plan.target})", lineterm="",
    ))
    shown = ["    " + line for line in lines[:DIFF_MAX_LINES]]
    if len(lines) > DIFF_MAX_LINES:
        shown.append(f"    ... diff truncated: {len(lines) - DIFF_MAX_LINES} more lines")
    return shown


def format_plan(plan: Plan, diff: bool = False) -> str:
    if plan.status == "up_to_date":
        return (f"capability {plan.name} is already at {scaffold.TEMPLATE_ID}@{plan.target}\n"
                "status: up_to_date\n")
    edge = plan.edge
    width = max(len(a.action) for a in plan.actions) + 2
    path_width = max(len(a.path) for a in plan.actions) + 2
    lines = [
        f"{edge.template_compatibility.upper()} upgrade {plan.name}: "
        f"{scaffold.TEMPLATE_ID}@{plan.source} -> {scaffold.TEMPLATE_ID}@{plan.target}",
        "",
        f"contract: {edge.contract_compatibility}",
        f"template: {edge.template_compatibility}",
        "rationale:",
        *(f"  - {code}: {RATIONALE[code]}" for code in edge.rationale_codes),
        "",
    ]
    for item in plan.actions:
        lines.append(f"{item.action.upper():<{width}}{item.path:<{path_width}}{item.reason}")
        if not diff:
            continue
        if item.action in ("update", "conflict") and item.path in plan.base and item.path in plan.target_files:
            lines.extend(_bounded_diff(plan, item.path))
        elif item.action in ("add", "conflict") and item.path in plan.target_files:
            lines.append(f"    target: {_describe_bytes(plan.target_files[item.path])}")
        if item.action == "conflict":
            lines.append("    your working-tree file is not shown; inspect it yourself (e.g. git diff)")
    lines += [
        "",
        f"conflicts: {len(plan.conflicts)}",
        f"files changed by apply: {len(plan.writes)}",
        f"status: {plan.status}" + (" (manual_resolution_required)" if plan.conflicts else ""),
    ]
    if plan.conflicts:
        lines += [
            "",
            "A conflict is a safe outcome, not a failure: the platform changed these paths AND",
            "this project changed (or occupies) them, so automatic ownership ends there.",
            "Reconcile them yourself. --apply refuses any plan that contains a conflict.",
        ]
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------
# Apply: all-or-nothing by construction, best-effort rollback on failure.
# --------------------------------------------------------------------------

_replace = os.replace  # indirection so tests can inject a filesystem failure


class DestinationAppeared(Exception):
    """An ADD destination existed at the moment of exclusive creation."""


def _create_new(path: Path, content: bytes) -> None:
    """ADD: exclusive creation (O_CREAT | O_EXCL). Never replaces an existing file.

    If anything (even a dangling symlink) occupies `path` at the moment of
    creation, the OS refuses atomically and nothing is written. Permissions
    follow the umask, exactly like `new`. Content is written after creation:
    a failed write removes the file this call created; a crash mid-write can
    leave a partial file, but provenance is written last and re-planning then
    reports that file as a target_path_collision (never overwritten).
    """
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags, 0o666)
    except FileExistsError:
        raise DestinationAppeared from None
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
    except BaseException:
        os.unlink(path)
        raise


def _atomic_write(path: Path, content: bytes, mode: int, replace=None) -> None:
    """Same-directory temp file + os.replace: a reader sees old or new bytes, never half."""
    fd, temp = tempfile.mkstemp(dir=path.parent, prefix=".golden-path-upgrade-")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
        os.chmod(temp, mode)
        (replace or _replace)(temp, path)
    except BaseException:
        if os.path.lexists(temp):
            os.unlink(temp)
        raise


def apply_plan(root: Path, plan: Plan) -> list[str]:
    """Perform a conflict-free plan. Returns the paths written, in order.

    Conflicts are refused before any write. Before EACH operation the path is
    re-read and must still match its planning-time fingerprint (stale_plan
    otherwise). capability.yaml, which carries the provenance claim, is written
    last, so metadata.template_version only names the target after every other
    operation succeeded.

    Race guarantees (no cross-process locking is provided):
      ADD     exclusive creation: no silent overwrite, even if the destination
              appears after planning or after the recheck (stale_plan).
      UPDATE  recheck immediately before a same-directory temp file + os.replace.
      DELETE  recheck immediately before unlink.
              For UPDATE and DELETE the recheck is best effort: a concurrent
              writer between recheck and replace/unlink is not detected.

    Rollback is best-effort and in-process. It is NOT crash-safe and NOT a
    filesystem transaction. A crash mid-apply leaves the source provenance in
    place, and re-planning classifies already-written files as already_target.
    """
    if plan.conflicts:
        raise ConflictsRefused("conflicts_present", f"{len(plan.conflicts)} conflict(s); nothing was written",
                               tuple(a.path for a in plan.conflicts))
    journal: list[tuple[str, Path, bytes | None, int]] = []  # (undo kind, path, original bytes, mode)
    written = []
    try:
        for item in plan.writes:
            path = root / item.path
            current = read_current(root, item.path)
            if _fingerprint(current) != item.planned_current:
                raise ApplyFailed("stale_plan", "a path changed after planning; nothing was overwritten", (item.path,))
            if item.action == "delete":
                journal.append(("restore", path, current, os.lstat(path).st_mode & 0o777))
                os.unlink(path)
            else:
                missing = []
                parent = path.parent
                while not os.path.lexists(parent):
                    missing.append(parent)
                    parent = parent.parent
                for directory in reversed(missing):
                    os.mkdir(directory)
                    journal.append(("rmdir", directory, None, 0))
                if item.action == "update":
                    mode = os.lstat(path).st_mode & 0o777
                    journal.append(("restore", path, current, mode))
                    _atomic_write(path, plan.target_files[item.path], mode)
                else:
                    try:
                        _create_new(path, plan.target_files[item.path])
                    except DestinationAppeared:
                        raise ApplyFailed("stale_plan", "an ADD destination appeared after planning; it was not replaced",
                                          (item.path,)) from None
                    # Journaled only once THIS apply created the file, so rollback can
                    # never delete a file another process created.
                    journal.append(("unlink", path, None, 0))
            written.append(item.path)
    except BaseException as exc:
        failed = _rollback(root, journal)
        if isinstance(exc, ApplyFailed):
            exc.locations += tuple(f"rollback incomplete: {p}" for p in failed)
            raise
        raise ApplyFailed("apply_failed", f"{type(exc).__name__} during apply; rolled back",
                          tuple(f"rollback incomplete: {p}" for p in failed)) from exc
    return written


def _rollback(root: Path, journal: list) -> list[str]:
    failed = []
    for kind, path, original, mode in reversed(journal):
        try:
            if kind == "restore":  # real os.replace, even when a test injected a failing _replace
                _atomic_write(path, original, mode, replace=os.replace)
            elif kind == "unlink" and os.path.lexists(path):
                os.unlink(path)
            elif kind == "rmdir" and os.path.lexists(path):
                os.rmdir(path)
        except OSError:
            failed.append(path.relative_to(root).as_posix())
    return failed
