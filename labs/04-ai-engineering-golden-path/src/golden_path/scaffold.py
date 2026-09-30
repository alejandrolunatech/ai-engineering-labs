"""Deterministic capability scaffolding (Lab 04, Phase 2).

Flow: validate name -> render every file in memory -> validate the rendered
capability.yaml against the canonical Phase 1 schema -> create the destination
atomically -> write files. Nothing touches disk until all validation passes.

Generated content depends only on the capability name and the template files.
No clock, randomness, network or environment values are used. File
permissions still follow the local umask; only content is deterministic.
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import yaml
from jinja2 import Environment, FileSystemLoader, StrictUndefined
from jsonschema import Draft202012Validator

# Known limitation (deferred): these paths are resolved relative to the lab
# source checkout. That works for `pip install -e .` and `python -m golden_path`,
# but not for a built wheel. Shipping templates/schema as package data is out of
# scope for Phase 2.
LAB_ROOT = Path(__file__).resolve().parents[2]
TEMPLATES_ROOT = LAB_ROOT / "templates"
CAPABILITY_SCHEMA_PATH = LAB_ROOT / "schemas" / "capability.schema.json"
EVAL_SUITE_SCHEMA_PATH = LAB_ROOT / "schemas" / "eval-suite.schema.json"
EVAL_REPORT_SCHEMA_PATH = LAB_ROOT / "schemas" / "eval-report.schema.json"
PRICING_SCHEMA_PATH = LAB_ROOT / "schemas" / "pricing.schema.json"
TELEMETRY_RECORD_SCHEMA_PATH = LAB_ROOT / "schemas" / "telemetry-record.schema.json"  # v1, frozen
TELEMETRY_RECORD_V2_SCHEMA_PATH = LAB_ROOT / "schemas" / "telemetry-record.v2.schema.json"
VERIFICATION_REPORT_SCHEMA_PATH = LAB_ROOT / "schemas" / "verification-report.schema.json"

TEMPLATE_ID = "capability"
# The current template. Released template versions are immutable: a change to
# generated output means a new version directory, never an edit to an old one.
TEMPLATE_VERSION = "0.6.0"
RENDER_SUFFIX = ".j2"

# Platform-managed files copied byte-for-byte from canonical platform sources
# rather than from the template, so a template cannot drift from the contract.
#
# The mapping is PER TEMPLATE VERSION. Freezing template files is not enough:
# if a released template's platform snapshots came from a single global
# mapping, editing or replacing a canonical contract would silently change what
# that historical template generates. Each version therefore names exactly the
# canonical contracts it was released with, and those canonical files are
# pinned by SHA-256 in tests (FROZEN_CONTRACTS). Released contracts are never
# edited; a changed contract gets a new versioned file (e.g. telemetry v2).
_CAPABILITY_V1 = {"platform/capability.schema.json": CAPABILITY_SCHEMA_PATH}
_EVALS_V1 = {
    "platform/eval-report.schema.json": EVAL_REPORT_SCHEMA_PATH,
    "platform/eval-suite.schema.json": EVAL_SUITE_SCHEMA_PATH,
}
PLATFORM_FILES_BY_TEMPLATE_VERSION: dict[str, dict[str, Path]] = {
    "0.1.0": {},
    "0.2.0": {**_CAPABILITY_V1},
    "0.3.0": {**_CAPABILITY_V1, **_EVALS_V1},
    "0.4.0": {
        **_CAPABILITY_V1,
        **_EVALS_V1,
        "platform/pricing.schema.json": PRICING_SCHEMA_PATH,
        "platform/telemetry-record.schema.json": TELEMETRY_RECORD_SCHEMA_PATH,  # v1
    },
    "0.5.0": {
        **_CAPABILITY_V1,
        **_EVALS_V1,
        "platform/pricing.schema.json": PRICING_SCHEMA_PATH,
        "platform/telemetry-record.schema.json": TELEMETRY_RECORD_V2_SCHEMA_PATH,
    },
    "0.6.0": {
        **_CAPABILITY_V1,
        **_EVALS_V1,
        "platform/pricing.schema.json": PRICING_SCHEMA_PATH,
        "platform/telemetry-record.schema.json": TELEMETRY_RECORD_V2_SCHEMA_PATH,
        "platform/verification-report.schema.json": VERIFICATION_REPORT_SCHEMA_PATH,
    },
}
PLATFORM_FILES = PLATFORM_FILES_BY_TEMPLATE_VERSION[TEMPLATE_VERSION]
# Every released version. `new` renders only TEMPLATE_VERSION; historical
# versions are rendered only to reconstruct upgrade BASE/TARGET trees (Phase 8).
RELEASED_TEMPLATE_VERSIONS = tuple(PLATFORM_FILES_BY_TEMPLATE_VERSION)


class ScaffoldError(Exception):
    """Base class for scaffold failures."""


class InvalidNameError(ScaffoldError):
    pass


class DestinationExistsError(ScaffoldError):
    pass


class TemplateContractError(ScaffoldError):
    """The rendered template does not satisfy the capability contract (platform bug)."""


class UnknownTemplateVersion(ScaffoldError):
    """The requested template version was never released. Fails closed."""


def load_capability_schema() -> dict:
    return json.loads(CAPABILITY_SCHEMA_PATH.read_text(encoding="utf-8"))


def validate_name(name: str) -> None:
    """Validate a capability name using the canonical Phase 1 schema rule.

    The regex is not duplicated here: it is read from the schema's
    metadata.name subschema.
    """
    name_schema = load_capability_schema()["properties"]["metadata"]["properties"]["name"]
    errors = sorted(e.message for e in Draft202012Validator(name_schema).iter_errors(name))
    if errors:
        raise InvalidNameError(f"invalid capability name {name!r}: {errors[0]}")

    # Filesystem-safety check, in addition to schema validation. Python's
    # re.search (used by jsonschema) lets `$` match before a trailing newline,
    # so the v1 schema pattern accepts "name\n". A capability name becomes a
    # directory name, so require a full match and reject CR/LF explicitly.
    if "\n" in name or "\r" in name or not re.fullmatch(name_schema["pattern"], name):
        raise InvalidNameError(
            f"invalid capability name {name!r}: contains line breaks or does not fully match "
            f"{name_schema['pattern']}"
        )


def display_title(name: str) -> str:
    return " ".join(part.capitalize() for part in name.split("-"))


def _released(version: str | None) -> str:
    version = TEMPLATE_VERSION if version is None else version
    if version not in PLATFORM_FILES_BY_TEMPLATE_VERSION:
        raise UnknownTemplateVersion(f"unknown template version for {TEMPLATE_ID}")
    return version


def template_dir(version: str | None = None) -> Path:
    """Directory of a released template version (default: the current one)."""
    return TEMPLATES_ROOT / TEMPLATE_ID / _released(version)


# Hidden paths a template may intentionally generate. Everything else that
# starts with "." is either ignorable local metadata or a template error.
ALLOWED_DOT_PATHS = frozenset({".github", ".gitignore"})
# Accidental local/generated metadata that must never leak into output.
IGNORED_NAMES = frozenset({".DS_Store", "__pycache__", ".pytest_cache"})
IGNORED_SUFFIXES = (".pyc",)


def template_sources(root: Path | None = None) -> list[Path]:
    """Files a template version generates.

    Only explicitly allowed dot paths (.github/, .gitignore) are generated.
    OS/bytecode metadata is ignored. Any other dot path is rejected loudly
    rather than silently copied or silently dropped.
    """
    root = root or template_dir()
    sources = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        parts = path.relative_to(root).parts
        if any(part in IGNORED_NAMES for part in parts) or path.name.endswith(IGNORED_SUFFIXES):
            continue
        unexpected = [part for part in parts if part.startswith(".") and part not in ALLOWED_DOT_PATHS]
        if unexpected:
            raise TemplateContractError(f"template contains an unsupported hidden path: {unexpected[0]}")
        sources.append(path)
    return sorted(sources)


def render(name: str, version: str | None = None) -> dict[str, bytes]:
    """Render a released template version (default: the current one) for `name`
    in memory. Returns {relative posix path: bytes}.

    The pipeline is the one every version was released with, so rendering a
    historical version reproduces what that release generated (pinned in tests).
    """
    validate_name(name)
    version = _released(version)
    root = template_dir(version)
    env = Environment(
        loader=FileSystemLoader(root),
        undefined=StrictUndefined,
        keep_trailing_newline=True,
        autoescape=False,
    )
    context = {
        "name": name,
        "title": display_title(name),
        "template_id": TEMPLATE_ID,
        "template_version": version,
    }

    files: dict[str, bytes] = {}
    for source in template_sources(root):
        relative = source.relative_to(root).as_posix()
        if relative.endswith(RENDER_SUFFIX):
            output = relative.removesuffix(RENDER_SUFFIX)
            files[output] = env.get_template(relative).render(context).encode("utf-8")
        else:
            files[relative] = source.read_bytes()

    for output, canonical in PLATFORM_FILES_BY_TEMPLATE_VERSION[version].items():
        if output in files:
            raise TemplateContractError(f"template must not provide platform-managed file {output}")
        files[output] = canonical.read_bytes()

    check_rendered_manifest(name, files)
    return dict(sorted(files.items()))


def check_rendered_manifest(name: str, files: dict[str, bytes]) -> None:
    """Fail closed if the template produced a manifest that violates the contract."""
    if "capability.yaml" not in files:
        raise TemplateContractError("template did not produce capability.yaml")
    manifest = yaml.safe_load(files["capability.yaml"])
    errors = sorted(
        f"{'/'.join(map(str, e.absolute_path)) or '<root>'}: {e.message}"
        for e in Draft202012Validator(load_capability_schema()).iter_errors(manifest)
    )
    if errors:
        raise TemplateContractError("rendered capability.yaml violates the contract: " + "; ".join(errors))
    if manifest["metadata"]["name"] != name:
        raise TemplateContractError("rendered metadata.name does not match the requested name")


def write(destination: Path, files: dict[str, bytes]) -> None:
    """Create `destination` and write `files` into it. Never touches an existing path."""
    try:
        # Atomic check-and-create. Fails on any existing entry, including a file,
        # an empty directory or a (dangling) symlink. Parents are not created.
        destination.mkdir()
    except FileExistsError:
        raise DestinationExistsError(f"destination already exists: {destination}") from None

    try:
        for relative, content in files.items():
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            with open(target, "xb") as handle:
                handle.write(content)
    except BaseException:
        # Only this run created `destination`, so only it is removed.
        shutil.rmtree(destination)
        raise


def new_capability(name: str, parent: Path) -> tuple[Path, list[str]]:
    files = render(name)
    destination = parent / name
    write(destination, files)
    return destination, list(files)
