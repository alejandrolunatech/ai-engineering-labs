# Lab 04 — Learning Notes

Fill this from actual evidence. Do not manufacture a successful platform story.

## Before the lab

### What do I think an AI engineering golden path is?

_Write here._

### What repeated work should a platform remove?

_Write here._

### What must remain visible to product engineers?

_Write here._

---

## Capability contract

Evidence: `schemas/capability.schema.json` (Draft 2020-12, `ai.platform/v1`),
`examples/change-explainer/capability.yaml`, and
`tests/test_capability_schema.py`. That test file has 138 deterministic tests
(108 rejected single-field mutations, 4 rejected non-mapping documents, 16
accepted boundary values, plus YAML-parsing and filesystem checks). All pass offline with no model call.

### Which fields became hard invariants?

The schema rejects a manifest when any of these fail:

- `api_version` is exactly `ai.platform/v1` and `kind` is exactly `Capability`.
- Unknown fields fail closed: every object sets `additionalProperties: false`.
  There is no place for `api_key`, `endpoint`, `model_id`, `temperature`,
  `exceptions`, `evaluation.skip` or `observability.record_prompts`, and
  tests confirm each of these is rejected.
- `metadata.name` matches `^[a-z][a-z0-9]*(-[a-z0-9]+)*$` and is 3–40
  characters. That makes it safe for directory names and the CLI. Uppercase,
  `_`, leading digits, leading, trailing or double hyphens, spaces and `../`
  are all rejected.
- `metadata.version` (the capability's version) and
  `metadata.template_version` (golden-path provenance) are both required. Both
  must be strict `MAJOR.MINOR.PATCH` strings.
- `spec.inputs.schema` and `spec.outputs.schema` are relative `.json` paths.
  `spec.evaluation.suite` is a relative `.yaml`/`.yml` path. Absolute paths,
  `~`, `.` and `..` segments, `//`, backslashes and URLs are rejected.
- `spec.model` allows only `profile` (`fast | balanced | deep`) and
  `adapter` (a lowercase slug). The earlier `provider` key is rejected.
- `spec.authority.tools` must always be present, even when empty. Entries must
  be unique slugs, at most 32. A `*` wildcard, `null`, a bare string and
  object entries are rejected.
- Budgets must be integers within these bounds: `max_model_requests` 1–10,
  `max_output_tokens` 1–16384, `max_latency_ms` 1–120000. Zero, negatives,
  bools, strings, `null`, `1.5` and infinity are rejected. **The ceilings
  are lab/platform policy choices, not industry standards.**
- `required_pass_rate` must satisfy `0 < x ≤ 1` (`exclusiveMinimum: 0`). A
  value of 0 would make evaluation present but meaningless, so it is
  rejected. Percent-style values such as `95` are also rejected.
- `observability.tracing` and `observability.usage` are `const: true` in v1.
  Disabling either later must go through an explicit exception mechanism,
  which does not exist yet. `observability.cost` is a required boolean.
  `false` means cost is not estimated and must be reported as unknown, not
  zero.

### Which fields remained advisory?

The schema checks the shape of these fields but cannot check their meaning:

- `spec.purpose`: it must be 10–500 characters and not all whitespace.
  Whether it is accurate is not checked.
- `spec.model.profile`: what "balanced" maps to is adapter configuration.
- `spec.model.adapter`: only the slug format is checked. Whether the adapter
  exists is not.
- `spec.data.sensitivity`: a declared label. Nothing in v1 changes behavior
  based on it.
- The *choice* of `required_pass_rate`: 0.01 is valid but weak.
- Whether `template_version` is true: the format is checked, but not whether
  that template exists.

### What does the schema prove?

For a given parsed document, the schema deterministically proves:

- the required keys are present;
- types, enums, regex patterns and numeric bounds hold;
- tool names are unique;
- no unknown keys appear;
- path strings are well formed and relative.

### What does the schema NOT prove?

- That referenced files exist or stay inside the capability folder after
  following symlinks. Phase 1 tests check this separately, for the example
  only, using the filesystem.
- That the referenced input/output files are valid JSON Schemas. This is also
  a separate filesystem test for the example only.
- That the eval suite exists, parses, or meets the threshold. This is
  deliberately **not** checked in Phase 1, because Phase 4 creates the eval
  kit. After that it becomes a verifier rule.
- That `metadata.name` matches the folder name. A separate test checks this
  for the example; it is not a schema rule.
- That the declared tools exist or are authorized.
- That the adapter exists.
- That the manifest contains no secrets inside allowed free-text fields such
  as `purpose`.
- That the capability is safe, correct or production-ready.

### Schema versus runtime

A valid manifest is a **declaration**, not enforcement. `max_model_requests: 2`
limits nothing until a runtime counts requests. `tools: []` blocks nothing
until a runtime rejects undeclared tool calls. `tracing: true` produces no
trace until telemetry exists. Phase 1 made the *contract* deterministic. It
did not make any *behavior* deterministic or safe.

### Deferred gaps (accepted, intentionally not fixed in Phase 1)

1. **Integral floats pass as integers.** `max_model_requests: 2.0` is
   accepted, because JSON Schema treats any integer-valued number as an
   integer. This is standard JSON Schema behavior, not a schema bug. Requiring
   the YAML value itself to be written as an integer belongs in the strict
   manifest loader/verifier, not in the schema.
2. **An adapter slug can look like a model ID.** `adapter: claude-opus-5-5` is
   accepted. The schema can stop provider *parameters* from appearing, but it
   cannot tell whether a well-formed slug is really a model ID. Whether an
   adapter exists is a later verifier/runtime concern. No adapter registry
   has been added.
3. **Duplicate YAML keys are resolved before validation.** `yaml.safe_load`
   silently keeps the last value, so `tools: []` followed later by
   `tools: [shell]` validates as `[shell]`. A test
   (`test_plain_safe_load_hides_duplicate_keys`) documents this. Schema
   validation happens *after* parsing, so a strict loader that rejects
   duplicate keys must become part of the verifier. The Phase 1 tests
   already load the example with one.

A related YAML gotcha is already caught: an unquoted `template_version: 0.1`
parses as a float, and the schema rejects it because the field must be a
string.

### What was difficult to express in one manifest?

- **Fields with different owners in one file.** `template_version`, the enum
  catalogs, the budget ceilings and the tracing/usage requirements belong to
  the platform. Name, purpose, budget values, tools and eval settings belong
  to the product team. `tools` and `sensitivity` are shared. The file lives
  in the product repo, but some of its keys are not the team's to edit.
- **Rejecting unknown fields versus evolving the schema.** Likely additions
  are per-tool impact metadata (Phase 6), a cost budget (Phase 5) and
  `exceptions`. The v1 schema rejects every one of them. Changing `tools`
  from strings to objects is a breaking change, so it needs a new
  `api_version` and a migration, not an in-place edit.
- **Three independent version numbers:** `api_version` (the contract),
  `template_version` (provenance) and `metadata.version` (the capability).
  How they relate across upgrades is not yet defined.
- **Provider neutrality is structural, not semantic.** The schema can forbid
  provider fields but cannot understand what a value means (see gap 2).

---

## Scaffold CLI

Evidence:
- **Platform code:** `src/golden_path/{cli.py,scaffold.py}`, the template
  `templates/capability/0.1.0/`, and `pyproject.toml`, which provides the
  `ai-golden-path = "golden_path.cli:app"` command.
- **Tests:** `tests/test_scaffold.py` has 67 tests. The full Lab 04 suite is
  205 tests, and all pass.
- **Manual run:** `pip install -e .` succeeded, followed by
  `ai-golden-path new demo-capability`.

### Generated tree

```
demo-capability/
├── capability.yaml
├── README.md
└── schemas/
    ├── input.schema.json
    └── output.schema.json
```

That's four files, with no dotfile, lockfile or hidden state. Only
`README.md.j2` and `capability.yaml.j2` are rendered. The two I/O schemas are
copied byte-for-byte. The only user input is the name. The display title is
derived from it (`demo-capability` → `Demo Capability`). `template_version`
comes from a platform constant, never from user input.

Provenance is recorded in `metadata.template_version` in `capability.yaml`.
The header comment and one README line mention it too, but only as notes for
readers. There is no `template_id` field in the v1 schema, which is fine
while there is a single template. A second template family would need a
schema change.

The template produces the Change Explainer reference capability on purpose.
It is not yet a catalog of capability types.

### Time to scaffold

Measured on a MacBook with an editable install:
- `ai-golden-path new <name>` took 0.23–0.26 s wall time over 5 runs, mostly
  Python and Typer start-up.
- In-memory rendering plus contract validation averaged 5.8 ms over 50 runs.

Generation needs no network. A test disables `socket` and generation still
succeeds. `pip install -e .` did fetch the setuptools build backend once into
pip's temporary build environment. setuptools is not a runtime dependency and
is not installed in the venv.

### What does the product team own after generation?

All four generated files. Nothing in them imports or depends on
`golden_path`, so the project stays intact if the platform tooling
disappears.

Exception: in `capability.yaml`, the keys `api_version`, `kind` and
`metadata.template_version` are marked as platform-managed, to be changed
only by a future upgrade tool. That is only a comment today. Nothing stops a
team from editing them. Detecting that is a verifier/upgrade concern
(Phases 7–8).

The starter defaults are flagged in the manifest comments and in a README
"Review before use" checklist, and a test locks that wording in:
- `spec.purpose` describes the reference template, not the new capability.
- `spec.data.sensitivity: synthetic` exists only because the reference
  template uses synthetic data. The README states that this is **not** a safe
  default for real capabilities, and that data must be classified before any
  real data is used.

### What does the scaffold prove, and what not?

Proven by tests:
- **Contract conformance:**
  - The generated `capability.yaml` validates against the canonical Phase 1
    schema, loaded with the strict duplicate-key loader.
  - It has exactly the same set of key paths as the Phase 1 example.
  - The CLI checks the rendered manifest against the schema before writing
    anything. A deliberately broken template (`max_model_requests: 0`) makes
    the command exit 3 and create nothing.
- **Determinism:**
  - Two generations are byte-for-byte identical.
  - Generations in two separate processes with `PYTHONHASHSEED=0` and `=1`
    produce identical SHA-256 trees.
  - Generated content contains no temp path, home folder, lab path,
    username, hostname, date-like string, UUID-like string or `\r`.
- **Overwrite refusal:**
  - An existing empty folder, a folder with edits, a file, a symlink to a
    folder and a broken symlink all cause exit 1, with a before/after
    snapshot that is identical.
  - Running the command a second time on `demo-capability` (after appending a
    team note to its README) exited 1. SHA-256 hashes, the file tree and
    modification times were unchanged.
  - There is no `--force` option; passing it is a usage error.
- **Transactional writes:** if a write fails after the folder was created,
  only that new folder is removed and sibling folders survive. A missing
  parent folder is not created.
- **Name validation:**
  - The rule is read from the schema, not copied.
  - A parity test shows the CLI and the schema agree on every Phase 1 valid
    and invalid name.
  - Invalid names create nothing and exit 2. Tests pass names after `--`.
    Without it, `-change` was rejected by Click's option parser before the
    validator ran: the right exit code for the wrong reason. The test now
    also checks the validator's message.
- **YAML coercion:** names like `yes`, `null`, `off` and `true` match the
  name pattern, but YAML 1.1 would turn them into a bool or null. The
  template quotes `metadata.name`, and tests confirm these names produce
  string values.

Not proven, or not done:
- That the starter purpose, sensitivity or schemas suit any real capability.
- That any runtime, eval, telemetry or policy behavior exists. None does yet.
- That files have deterministic permissions. Content is deterministic, but
  modes follow the local umask.
- That templates can be found from a built wheel. `scaffold.py` finds
  `templates/` and `schemas/` relative to the source checkout. This works for
  `pip install -e .` and `python -m golden_path`, not for a non-editable
  wheel. Shipping them as package data is deferred.

### Schema regex edge case found while building the CLI

Python's `re.search`, which `jsonschema` uses for `pattern`, lets `$` match
*before a trailing newline*. As a result, the committed `ai.platform/v1`
schema accepts `metadata.name: "change-explainer\n"`. A test confirms this.
The same edge case likely affects the schema's other `$`-anchored patterns
(semver, slugs, paths). That has not been fixed or tested field by field.

Because a capability name becomes a directory name, the CLI adds a
**filesystem-safety check on top of schema validation**: `re.fullmatch` on
the same pattern, plus explicit CR/LF rejection. On this one input the CLI is
deliberately stricter than the schema, and a test documents that. Running
`ai-golden-path new -- $'demo-capability\n'` exited 2 with "contains line
breaks". The released v1 schema was **not** modified. A portable fix would be
a deliberate contract change.

### Where did generation feel like useful automation versus framework magic?

Useful automation:
- One command produces a contract-valid project in well under a second.
- Name validation, provenance and overwrite safety come for free.
- The template is four plain files whose output can be read directly.

Places where magic could creep in, kept visible for now:
- The only template rule is "`.j2` is rendered, everything else is copied,
  dotfiles are skipped".
- The template location depends on the source checkout.
- The "platform-managed keys" boundary exists only as a comment.

---

## Reference capability

### Model adapter boundary

_Write here._

### What can run without a real model?

_Write here._

### Input/output validation failures observed

_Write here._

---

## Evaluation

### Cases

_Write here._

### Metrics that are genuinely deterministic

_Write here._

### Metrics I should not overclaim

_Write here._

---

## Observability and cost

### What is recorded?

_Write here._

### What remains unknown?

_Write here._

### Sensitive data intentionally excluded

_Write here._

---

## Authority and guardrails

### Declared tools

_Write here._

### What happens when the model requests an undeclared tool?

_Write here._

### Deterministic versus probabilistic boundary

_Write here._

---

## Verification and CI

### What does a green verify actually prove?

_Write here._

### What does it not prove?

_Write here._

### Failure cases caught

_Write here._

---

## Template lifecycle

### Upgrade attempted

_Write here._

### Product-team edits preserved?

_Write here._

### Compatibility problems discovered

_Write here._

---

## Developer self-service experiment

| Metric | Capability 1 | Capability 2 |
|---|---:|---:|
| Scaffold seconds | | |
| Manual setup steps | | |
| Time to first green | | |
| Verify seconds | | |
| Overrides | | |
| Platform changes needed | | |

### Biggest friction

_Write here._

### What I would improve as the platform owner

_Write here._

---

## Enterprise gap analysis

Consider:

- authenticated developer/workload identity;
- approved model/provider catalog;
- secrets distribution;
- centralized policy;
- data classification;
- artifact signing/provenance;
- centralized telemetry;
- chargeback/budgets;
- multi-language templates;
- ownership/support model;
- platform SLOs;
- migration policy.

_Write here._

---

## Codex platform review

### Blockers

_Write here._

### Important findings

_Write here._

### Nice-to-have improvements

_Write here._

### Recommendations accepted

_Write here._

### Recommendations deferred

_Write here._

---

## Interview story

Explain the lab in 60–90 seconds in my own words:

_Write here._

---

## Lessons I want to remember

1.
2.
3.
4.
5.
