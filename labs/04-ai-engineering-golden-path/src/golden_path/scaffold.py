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

TEMPLATE_ID = "capability"
# The current template. Released template versions are immutable: a change to
# generated output means a new version directory, never an edit to an old one.
TEMPLATE_VERSION = "0.2.0"
RENDER_SUFFIX = ".j2"

# Platform-managed files copied byte-for-byte from canonical platform sources
# rather than from the template, so a template cannot drift from the contract.
PLATFORM_FILES = {"platform/capability.schema.json": CAPABILITY_SCHEMA_PATH}


class ScaffoldError(Exception):
    """Base class for scaffold failures."""


class InvalidNameError(ScaffoldError):
    pass


class DestinationExistsError(ScaffoldError):
    pass


class TemplateContractError(ScaffoldError):
    """The rendered template does not satisfy the capability contract (platform bug)."""


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


def template_dir() -> Path:
    return TEMPLATES_ROOT / TEMPLATE_ID / TEMPLATE_VERSION


def template_sources() -> list[Path]:
    root = template_dir()
    # Dotfiles and bytecode caches are skipped so OS metadata (e.g. .DS_Store) or
    # __pycache__ from running template code never leaks into output.
    return sorted(
        path
        for path in root.rglob("*")
        if path.is_file()
        and not any(
            part.startswith(".") or part == "__pycache__" for part in path.relative_to(root).parts
        )
    )


def render(name: str) -> dict[str, bytes]:
    """Render the template for `name` in memory. Returns {relative posix path: bytes}."""
    validate_name(name)
    root = template_dir()
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
        "template_version": TEMPLATE_VERSION,
    }

    files: dict[str, bytes] = {}
    for source in template_sources():
        relative = source.relative_to(root).as_posix()
        if relative.endswith(RENDER_SUFFIX):
            output = relative.removesuffix(RENDER_SUFFIX)
            files[output] = env.get_template(relative).render(context).encode("utf-8")
        else:
            files[relative] = source.read_bytes()

    for output, canonical in PLATFORM_FILES.items():
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
