"""Contract loading and validation for this capability.

Everything in this module is deterministic.

capability.yaml is validated against platform/capability.schema.json: a
versioned, byte-identical snapshot of the golden-path ai.platform/v1 schema
taken when this project was generated. The runtime never imports the
golden-path platform package.

Error messages name the schema location and the rule that failed. They never
echo the offending input or output value, which may be sensitive.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_FILE = "capability.yaml"
CONTRACT_SNAPSHOT_FILE = "platform/capability.schema.json"


class CapabilityError(Exception):
    """Base error. `exit_code` is used by the command-line entry point."""

    exit_code = 1

    def __init__(self, message: str, *, model_requests_used: int = 0, failed_rules: tuple[str, ...] = ()):
        super().__init__(message)
        self.model_requests_used = model_requests_used
        # Names of the rules that failed (JSON Schema keywords or runtime rule
        # names). Safe for telemetry: never contains the rejected values.
        self.failed_rules = tuple(sorted(set(failed_rules)))


class InputValidationError(CapabilityError):
    exit_code = 2


class ManifestError(CapabilityError):
    """capability.yaml or its referenced contracts are invalid or unsupported."""

    exit_code = 3


class OutputValidationError(CapabilityError):
    exit_code = 4


class ModelInvocationError(CapabilityError):
    exit_code = 4


class ModelRequestBudgetExceeded(CapabilityError):
    exit_code = 4


class _StrictYamlLoader(yaml.SafeLoader):
    """SafeLoader that rejects duplicate keys instead of keeping the last one."""


def _construct_unique_mapping(loader, node, deep=False):
    seen = set()
    for key_node, _ in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in seen:
            raise yaml.constructor.ConstructorError(
                None, None, f"duplicate key {key!r}", key_node.start_mark
            )
        seen.add(key)
    return yaml.SafeLoader.construct_mapping(loader, node, deep=deep)


_StrictYamlLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_unique_mapping
)


def load_yaml_strict(text: str) -> Any:
    """yaml.safe_load equivalent that rejects duplicate mapping keys."""
    return yaml.load(text, Loader=_StrictYamlLoader)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key in JSON object")
        result[key] = value
    return result


def _reject_constant(name: str) -> Any:
    raise ValueError(f"non-standard JSON constant {name}")


def parse_json_strict(text: str) -> Any:
    """json.loads that rejects duplicate keys and NaN/Infinity."""
    return json.loads(text, object_pairs_hook=_unique_object, parse_constant=_reject_constant)


def describe_errors(schema: dict, instance: Any, limit: int = 5) -> str:
    """Summarize schema violations by location and rule, never by value."""
    errors = sorted(
        Draft202012Validator(schema).iter_errors(instance),
        key=lambda e: ([str(p) for p in e.absolute_path], str(e.validator)),
    )
    parts = [
        f"{'/'.join(str(p) for p in e.absolute_path) or '<root>'} failed '{e.validator}'"
        for e in errors[:limit]
    ]
    if len(errors) > limit:
        parts.append(f"... {len(errors) - limit} more")
    return "; ".join(parts)


def schema_failed_rules(schema: dict, instance: Any) -> tuple[str, ...]:
    """The JSON Schema keywords that failed, e.g. ("pattern", "required")."""
    return tuple(sorted({str(e.validator) for e in Draft202012Validator(schema).iter_errors(instance)}))


@dataclass(frozen=True)
class Manifest:
    """The subset of capability.yaml the runtime uses, after full validation."""

    name: str
    version: str
    template_version: str
    profile: str
    adapter: str
    tools: tuple[str, ...]
    max_model_requests: int
    max_output_tokens: int
    max_latency_ms: int
    input_schema_path: str
    output_schema_path: str
    input_schema: dict
    output_schema: dict
    eval_suite_path: str
    required_pass_rate: float
    data_sensitivity: str


def _load_json_file(path: Path, what: str) -> Any:
    try:
        return parse_json_strict(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise ManifestError(f"cannot load {what}: {type(exc).__name__}") from None


def _load_referenced_schema(root: Path, relative: str) -> dict:
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ManifestError(f"{relative} resolves outside the project root")
    schema = _load_json_file(path, relative)
    try:
        Draft202012Validator.check_schema(schema)
    except Exception:
        raise ManifestError(f"{relative} is not a valid JSON Schema") from None
    return schema


def load_manifest(root: Path = PROJECT_ROOT) -> Manifest:
    try:
        raw = load_yaml_strict((root / MANIFEST_FILE).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        mark = getattr(exc, "problem_mark", None)
        where = f" at line {mark.line + 1}" if mark is not None else ""
        raise ManifestError(f"cannot load {MANIFEST_FILE}{where}: {type(exc).__name__}") from None

    contract = _load_json_file(root / CONTRACT_SNAPSHOT_FILE, CONTRACT_SNAPSHOT_FILE)
    problems = describe_errors(contract, raw)
    if problems:
        raise ManifestError(f"{MANIFEST_FILE} violates {CONTRACT_SNAPSHOT_FILE}: {problems}")

    spec = raw["spec"]
    return Manifest(
        name=raw["metadata"]["name"],
        version=raw["metadata"]["version"],
        template_version=raw["metadata"]["template_version"],
        profile=spec["model"]["profile"],
        adapter=spec["model"]["adapter"],
        tools=tuple(spec["authority"]["tools"]),
        max_model_requests=spec["budgets"]["max_model_requests"],
        max_output_tokens=spec["budgets"]["max_output_tokens"],
        max_latency_ms=spec["budgets"]["max_latency_ms"],
        input_schema_path=spec["inputs"]["schema"],
        output_schema_path=spec["outputs"]["schema"],
        input_schema=_load_referenced_schema(root, spec["inputs"]["schema"]),
        output_schema=_load_referenced_schema(root, spec["outputs"]["schema"]),
        eval_suite_path=spec["evaluation"]["suite"],
        required_pass_rate=spec["evaluation"]["required_pass_rate"],
        data_sensitivity=spec["data"]["sensitivity"],
    )


def validate_input(manifest: Manifest, payload: Any) -> Any:
    problems = describe_errors(manifest.input_schema, payload)
    if problems:
        raise InputValidationError(
            f"input violates {manifest.input_schema_path}: {problems}",
            failed_rules=schema_failed_rules(manifest.input_schema, payload),
        )
    return payload


def validate_output(manifest: Manifest, content: Any, *, model_requests_used: int) -> Any:
    """Parse model text as strict JSON and validate it against the output schema."""
    if not isinstance(content, str):
        raise OutputValidationError(
            f"model content must be text, got {type(content).__name__}",
            model_requests_used=model_requests_used,
            failed_rules=("content_type",),
        )
    try:
        payload = parse_json_strict(content)
    except ValueError as exc:
        where = f" (line {exc.lineno}, column {exc.colno})" if isinstance(exc, json.JSONDecodeError) else ""
        raise OutputValidationError(
            f"model output is not strict JSON{where}",
            model_requests_used=model_requests_used,
            failed_rules=("strict_json",),
        ) from None
    problems = describe_errors(manifest.output_schema, payload)
    if problems:
        raise OutputValidationError(
            f"model output violates {manifest.output_schema_path}: {problems}",
            model_requests_used=model_requests_used,
            failed_rules=schema_failed_rules(manifest.output_schema, payload),
        )
    return payload
