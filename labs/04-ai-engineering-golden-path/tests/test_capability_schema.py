"""Phase 1 — deterministic tests for the capability manifest contract.

Two kinds of checks live here and are kept deliberately separate:

1. Schema validation: structure, types, bounds, naming, unknown fields.
   Proven by JSON Schema alone.
2. Reference validation: whether paths named in the example manifest resolve
   to real, well-formed files. JSON Schema cannot prove this; it needs the
   filesystem.

No network, no model, no clock. A passing run means the declared structural
contract holds for these inputs. It does not mean any capability is safe,
correct, or production-ready.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
import yaml
from jsonschema import Draft202012Validator

LAB_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = LAB_ROOT / "schemas" / "capability.schema.json"
EXAMPLE_DIR = LAB_ROOT / "examples" / "change-explainer"
EXAMPLE_MANIFEST = EXAMPLE_DIR / "capability.yaml"

DELETE = object()  # sentinel: remove the key instead of setting a value


class StrictSafeLoader(yaml.SafeLoader):
    """SafeLoader that rejects duplicate mapping keys.

    yaml.safe_load silently keeps the last duplicate, so a manifest could say
    `tools: []` and later `tools: [shell]` and the schema would only ever see
    the second value. The future verifier must load manifests this strictly.
    """


def _construct_mapping_no_duplicates(loader, node, deep=False):
    seen = set()
    for key_node, _ in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in seen:
            raise yaml.constructor.ConstructorError(
                None, None, f"duplicate key {key!r}", key_node.start_mark
            )
        seen.add(key)
    return yaml.SafeLoader.construct_mapping(loader, node, deep=deep)


StrictSafeLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_mapping_no_duplicates
)


def load_yaml_strict(text: str) -> Any:
    return yaml.load(text, Loader=StrictSafeLoader)


@pytest.fixture(scope="module")
def validator() -> Draft202012Validator:
    schema = json.loads(SCHEMA_PATH.read_text())
    return Draft202012Validator(schema)


@pytest.fixture(scope="module")
def example() -> dict:
    return load_yaml_strict(EXAMPLE_MANIFEST.read_text())


@pytest.fixture
def manifest(example) -> dict:
    """A fresh, mutable copy of the valid example manifest."""
    return copy.deepcopy(example)


def mutate(doc: dict, dotted: str, value: Any) -> dict:
    *parents, leaf = dotted.split(".")
    node = doc
    for key in parents:
        node = node[key]
    if value is DELETE:
        del node[leaf]
    else:
        node[leaf] = value
    return doc


def error_messages(validator: Draft202012Validator, doc: Any) -> list[str]:
    return [e.message for e in validator.iter_errors(doc)]


# --------------------------------------------------------------------------
# 1. The contract itself
# --------------------------------------------------------------------------


def test_schema_is_valid_draft_2020_12():
    Draft202012Validator.check_schema(json.loads(SCHEMA_PATH.read_text()))


def test_example_manifest_is_valid(validator, example):
    assert error_messages(validator, example) == []


# --------------------------------------------------------------------------
# 2. Invalid manifests must be rejected
# --------------------------------------------------------------------------

INVALID_CASES = [
    # --- envelope ---
    ("api_version-missing", "api_version", DELETE),
    ("api_version-v2", "api_version", "ai.platform/v2"),
    ("kind-wrong", "kind", "Service"),
    ("unknown-top-level-field", "exceptions", [{"id": "x"}]),
    ("unknown-top-level-credentials", "credentials", {"token": "redacted"}),
    # --- metadata ---
    ("metadata-unknown-field", "metadata.owner", "team-x"),
    ("name-missing", "metadata.name", DELETE),
    ("name-empty", "metadata.name", ""),
    ("name-too-short", "metadata.name", "ab"),
    ("name-too-long", "metadata.name", "a" * 41),
    ("name-uppercase", "metadata.name", "Change-Explainer"),
    ("name-underscore", "metadata.name", "change_explainer"),
    ("name-leading-digit", "metadata.name", "1change"),
    ("name-leading-hyphen", "metadata.name", "-change"),
    ("name-trailing-hyphen", "metadata.name", "change-"),
    ("name-double-hyphen", "metadata.name", "change--explainer"),
    ("name-path-traversal", "metadata.name", "../evil"),
    ("name-space", "metadata.name", "change explainer"),
    ("name-not-string", "metadata.name", False),
    ("version-missing", "metadata.version", DELETE),
    ("version-two-parts", "metadata.version", "0.1"),
    ("version-v-prefix", "metadata.version", "v0.1.0"),
    ("version-prerelease", "metadata.version", "0.1.0-beta"),
    ("version-leading-zero", "metadata.version", "01.0.0"),
    ("version-float", "metadata.version", 0.1),
    ("template_version-missing", "metadata.template_version", DELETE),
    ("template_version-garbage", "metadata.template_version", "latest"),
    # --- spec envelope ---
    ("spec-unknown-field", "spec.secrets", {"api_key": "redacted"}),
    ("purpose-missing", "spec.purpose", DELETE),
    ("purpose-too-short", "spec.purpose", "short"),
    ("purpose-whitespace", "spec.purpose", " " * 20),
    ("purpose-too-long", "spec.purpose", "x" * 501),
    # --- input/output schema references ---
    ("inputs-missing", "spec.inputs", DELETE),
    ("outputs-missing", "spec.outputs", DELETE),
    ("inputs-schema-missing", "spec.inputs.schema", DELETE),
    ("inputs-absolute-path", "spec.inputs.schema", "/etc/input.schema.json"),
    ("inputs-home-path", "spec.inputs.schema", "~/input.schema.json"),
    ("inputs-traversal", "spec.inputs.schema", "../shared/input.schema.json"),
    ("inputs-inner-traversal", "spec.inputs.schema", "schemas/../../x.json"),
    ("inputs-dot-segment", "spec.inputs.schema", "./schemas/input.schema.json"),
    ("inputs-backslash", "spec.inputs.schema", "schemas\\input.schema.json"),
    ("inputs-double-slash", "spec.inputs.schema", "schemas//input.schema.json"),
    ("inputs-url", "spec.inputs.schema", "https://example.com/input.json"),
    ("inputs-wrong-extension", "spec.inputs.schema", "schemas/input.yaml"),
    ("outputs-empty", "spec.outputs.schema", ""),
    ("outputs-extra-field", "spec.outputs.inline", {"type": "object"}),
    # --- model: provider-neutral only ---
    ("model-missing", "spec.model", DELETE),
    ("model-profile-unknown", "spec.model.profile", "turbo"),
    ("model-adapter-missing", "spec.model.adapter", DELETE),
    ("model-adapter-uppercase", "spec.model.adapter", "OpenAI"),
    ("model-adapter-model-id", "spec.model.adapter", "claude-opus-5.5"),
    ("model-legacy-provider-key", "spec.model.provider", "adapter"),
    ("model-provider-model-id", "spec.model.model_id", "gpt-x"),
    ("model-endpoint", "spec.model.endpoint", "https://api.example.com"),
    ("model-api-key", "spec.model.api_key", "redacted"),
    ("model-temperature", "spec.model.temperature", 0.2),
    ("model-sdk-config", "spec.model.sdk", {"timeout": 30}),
    # --- authority ---
    ("authority-missing", "spec.authority", DELETE),
    ("tools-missing", "spec.authority.tools", DELETE),
    ("tools-null", "spec.authority.tools", None),
    ("tools-string", "spec.authority.tools", "search_docs"),
    ("tools-wildcard", "spec.authority.tools", ["*"]),
    ("tools-duplicate", "spec.authority.tools", ["search_docs", "search_docs"]),
    ("tools-uppercase", "spec.authority.tools", ["SearchDocs"]),
    ("tools-empty-name", "spec.authority.tools", [""]),
    ("tools-object-item", "spec.authority.tools", [{"name": "search_docs"}]),
    ("tools-too-many", "spec.authority.tools", [f"tool_{i}" for i in range(33)]),
    ("authority-unknown-field", "spec.authority.allow_all", True),
    # --- budgets ---
    ("budgets-missing", "spec.budgets", DELETE),
    ("requests-missing", "spec.budgets.max_model_requests", DELETE),
    ("requests-zero", "spec.budgets.max_model_requests", 0),
    ("requests-negative", "spec.budgets.max_model_requests", -1),
    ("requests-over-ceiling", "spec.budgets.max_model_requests", 11),
    ("requests-fraction", "spec.budgets.max_model_requests", 1.5),
    ("requests-bool", "spec.budgets.max_model_requests", True),
    ("requests-string", "spec.budgets.max_model_requests", "2"),
    ("requests-null", "spec.budgets.max_model_requests", None),
    ("tokens-zero", "spec.budgets.max_output_tokens", 0),
    ("tokens-over-ceiling", "spec.budgets.max_output_tokens", 16385),
    ("latency-zero", "spec.budgets.max_latency_ms", 0),
    ("latency-over-ceiling", "spec.budgets.max_latency_ms", 120001),
    ("latency-infinite", "spec.budgets.max_latency_ms", float("inf")),
    ("budgets-unknown-field", "spec.budgets.max_cost_usd", 1),
    # --- data ---
    ("data-missing", "spec.data", DELETE),
    ("sensitivity-missing", "spec.data.sensitivity", DELETE),
    ("sensitivity-unknown", "spec.data.sensitivity", "secret"),
    # --- evaluation ---
    ("evaluation-missing", "spec.evaluation", DELETE),
    ("suite-missing", "spec.evaluation.suite", DELETE),
    ("suite-absolute", "spec.evaluation.suite", "/tmp/cases.yaml"),
    ("suite-traversal", "spec.evaluation.suite", "../evals/cases.yaml"),
    ("suite-wrong-extension", "spec.evaluation.suite", "evals/cases.json"),
    ("pass_rate-missing", "spec.evaluation.required_pass_rate", DELETE),
    ("pass_rate-zero", "spec.evaluation.required_pass_rate", 0),
    ("pass_rate-negative", "spec.evaluation.required_pass_rate", -0.01),
    ("pass_rate-over-one", "spec.evaluation.required_pass_rate", 1.01),
    ("pass_rate-percent", "spec.evaluation.required_pass_rate", 95),
    ("pass_rate-string", "spec.evaluation.required_pass_rate", "1.0"),
    ("evaluation-skip-flag", "spec.evaluation.skip", True),
    # --- observability ---
    ("observability-missing", "spec.observability", DELETE),
    ("tracing-missing", "spec.observability.tracing", DELETE),
    ("tracing-disabled", "spec.observability.tracing", False),
    ("tracing-string", "spec.observability.tracing", "true"),
    ("usage-missing", "spec.observability.usage", DELETE),
    ("usage-disabled", "spec.observability.usage", False),
    ("cost-missing", "spec.observability.cost", DELETE),
    ("cost-string", "spec.observability.cost", "false"),
    ("cost-null", "spec.observability.cost", None),
    ("observability-unknown-field", "spec.observability.record_prompts", True),
]


@pytest.mark.parametrize(
    ("dotted", "value"),
    [(path, value) for _, path, value in INVALID_CASES],
    ids=[case_id for case_id, _, _ in INVALID_CASES],
)
def test_invalid_manifest_is_rejected(validator, manifest, dotted, value):
    mutate(manifest, dotted, value)
    assert error_messages(validator, manifest), f"schema accepted {dotted}={value!r}"


def test_invalid_case_ids_are_unique():
    ids = [case_id for case_id, _, _ in INVALID_CASES]
    assert len(ids) == len(set(ids))


@pytest.mark.parametrize("top_level", [None, [], "capability", 1])
def test_non_mapping_document_is_rejected(validator, top_level):
    assert error_messages(validator, top_level)


# --------------------------------------------------------------------------
# 3. Boundary values that must remain valid
# --------------------------------------------------------------------------

VALID_BOUNDARY_CASES = [
    ("name-min-length", "metadata.name", "abc"),
    ("name-max-length", "metadata.name", "a" * 40),
    ("name-with-digits", "metadata.name", "explainer-v2"),
    ("tools-declared", "spec.authority.tools", ["search_docs", "read-ticket"]),
    ("tools-at-limit", "spec.authority.tools", [f"tool_{i}" for i in range(32)]),
    ("requests-min", "spec.budgets.max_model_requests", 1),
    ("requests-ceiling", "spec.budgets.max_model_requests", 10),
    ("tokens-ceiling", "spec.budgets.max_output_tokens", 16384),
    ("latency-ceiling", "spec.budgets.max_latency_ms", 120000),
    ("pass_rate-one", "spec.evaluation.required_pass_rate", 1),
    ("pass_rate-small-positive", "spec.evaluation.required_pass_rate", 0.01),
    ("suite-yml", "spec.evaluation.suite", "evals/cases.yml"),
    ("cost-disabled", "spec.observability.cost", False),
    ("sensitivity-confidential", "spec.data.sensitivity", "confidential"),
    ("profile-deep", "spec.model.profile", "deep"),
    ("adapter-fake", "spec.model.adapter", "fake"),
]


@pytest.mark.parametrize(
    ("dotted", "value"),
    [(path, value) for _, path, value in VALID_BOUNDARY_CASES],
    ids=[case_id for case_id, _, _ in VALID_BOUNDARY_CASES],
)
def test_boundary_manifest_is_accepted(validator, manifest, dotted, value):
    mutate(manifest, dotted, value)
    assert error_messages(validator, manifest) == []


# --------------------------------------------------------------------------
# 4. YAML parsing happens before schema validation
# --------------------------------------------------------------------------

DUPLICATE_TOOLS_YAML = """\
authority:
  tools: []
  tools: [shell]
"""


def test_plain_safe_load_hides_duplicate_keys():
    # Documents the gap: the schema would only ever see the last value.
    assert yaml.safe_load(DUPLICATE_TOOLS_YAML) == {"authority": {"tools": ["shell"]}}


def test_strict_loader_rejects_duplicate_keys():
    with pytest.raises(yaml.constructor.ConstructorError, match="duplicate key"):
        load_yaml_strict(DUPLICATE_TOOLS_YAML)


def test_unquoted_yaml_version_becomes_float_and_is_rejected(validator, manifest):
    parsed = load_yaml_strict("template_version: 0.1\n")["template_version"]
    assert isinstance(parsed, float)
    mutate(manifest, "metadata.template_version", parsed)
    assert error_messages(validator, manifest)


# --------------------------------------------------------------------------
# 5. Reference validation (filesystem) — NOT something JSON Schema can prove
# --------------------------------------------------------------------------


def _resolve_inside_example(relative: str) -> Path:
    resolved = (EXAMPLE_DIR / relative).resolve()
    assert resolved.is_relative_to(EXAMPLE_DIR.resolve()), f"{relative} escapes capability root"
    return resolved


def test_example_name_matches_directory(example):
    assert example["metadata"]["name"] == EXAMPLE_DIR.name


@pytest.mark.parametrize("section", ["inputs", "outputs"])
def test_example_referenced_io_schema_exists_and_is_valid(example, section):
    path = _resolve_inside_example(example["spec"][section]["schema"])
    assert path.is_file(), f"{section} schema not found: {path}"
    Draft202012Validator.check_schema(json.loads(path.read_text()))


def test_example_eval_suite_path_is_structural_only_in_phase_1(example):
    # Phase 1 validates evaluation.suite structurally (schema test above) and
    # confirms it stays inside the capability root. Whether the file exists is
    # deliberately NOT checked yet: Phase 4 creates the eval kit, and
    # "eval suite exists and meets threshold" becomes a verifier invariant then.
    _resolve_inside_example(example["spec"]["evaluation"]["suite"])
