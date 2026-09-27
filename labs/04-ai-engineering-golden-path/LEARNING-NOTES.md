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

Evidence:
- **Template:** `templates/capability/0.2.0/`. Its generated runtime is
  `src/{contracts,model_adapter,capability}.py` plus
  `tests/test_capability.py`.
- **Platform tests:** `tests/test_template_runtime.py` (15 tests) and the
  updated `tests/test_scaffold.py` (68 tests). The full Lab 04 suite is 221
  tests, all passing.
- **Manual run outside the repo:** `ai-golden-path new runtime-demo`, then
  `python src/capability.py fixtures/sample_input.json` and the generated
  `pytest`, which passed 32 tests.

### Why 0.1.0 was frozen instead of silently changed

`capability@0.1.0` was already released: committed, and recorded as
`template_version: "0.1.0"` in generated projects. Phase 3 grows the
generated tree from 4 files to 12, and adds runtime code, tests and a
contract snapshot.

Editing 0.1.0 in place would have made two different trees claim the same
provenance. "0.1.0" would stop meaning one thing, and no upgrade path out of
it could ever be computed. Instead:
- Phase 3 created `capability@0.2.0`.
- The CLI generates only the current version.
- `test_released_template_is_frozen` pins the SHA-256 of every 0.1.0 file as
  committed in Phase 2.
- The Phase 2 tests that describe "the current template" were updated to
  0.2.0 (tree, source list, version).

As a result, Phase 8 will exercise the **real 0.1.0 → 0.2.0 upgrade** rather
than inventing a synthetic second version. README.md and PROMPTS.md were
updated to say so.

### Model adapter boundary

- **The protocol is async:** `ModelAdapter.name` plus
  `async def generate(ModelRequest) -> ModelResponse`, matching
  ARCHITECTURE.md. Real adapters are I/O-bound, and choosing async now avoids
  breaking the protocol later. The runtime is async inside; the command line
  uses `asyncio.run`.
- **Request and response types** are provider-neutral frozen dataclasses:
  - `ModelRequest`: capability, profile, instructions, validated input,
    output schema, `max_output_tokens`.
  - `ModelResponse`: `content: str` plus `ModelInfo(adapter, model)`.
- **Content is always text.** The runtime parses it itself, so an adapter
  cannot pass through Python objects or SDK types. A response that isn't a
  `ModelResponse`, or whose content isn't a `str`, counts as invalid output.
- **Adapters come from an explicit registry,** `ADAPTERS = {"fake":
  FakeModelAdapter}`. Nothing named in the manifest is imported. An unknown
  slug fails closed (exit 3). An injected adapter whose `name` differs from
  the declared adapter is refused. Template 0.2.0 sets `adapter: fake`
  because `default` would name an adapter that doesn't exist. This is where
  the Phase 1 gap "the schema can't tell whether an adapter exists" is
  handled: at runtime, not in the schema.
- **The result keeps three things separate:**
  - declared values from `capability.yaml`: `capability.*`,
    `model.declared_adapter`, `model.declared_profile`;
  - adapter-reported, **untrusted** labels: `model.adapter_reported`;
  - the enforced budget: `model_requests.used` / `limit`.
- **The generated project is independent of the platform:**
  - A static AST test allows only stdlib, `jsonschema`, `yaml`, `pytest` and
    the project's own modules.
  - Generated `src/` must not import `os`, network modules or provider SDKs,
    and must not read `environ` or `getenv`.
  - The generated suite and command line were run in a subprocess with a stub
    `golden_path` package that raises on import. They passed, proving
    independence even though the platform is installed in the same venv.
- **Contract snapshot:** `platform/capability.schema.json` is copied
  byte-for-byte from the canonical schema at scaffold time. It comes from the
  canonical file, not from a copy under `templates/`, and a test asserts the
  bytes are identical. A template that tries to provide that file itself
  fails generation. Teams *can* edit the snapshot today and nothing detects
  it. Phase 7 verification is meant to detect contract and provenance drift.
  A released `ai.platform/v1` schema remains immutable.

### Which manifest declarations became runtime enforcement in Phase 3?

| Declaration | Phase 3 status |
|---|---|
| Whole manifest vs contract snapshot | **Enforced**: invalid manifest → exit 3 before any adapter call (zero budget and an injected `api_key` both tested) |
| `spec.inputs.schema` | **Enforced before the model**: invalid input → exit 2, `adapter.calls == []`, `model_requests_used == 0` |
| `spec.outputs.schema` | **Enforced after the model**: strict JSON parse + schema; invalid output is never returned |
| `spec.budgets.max_model_requests` | **Enforced**: `RequestBudget.consume()` runs immediately before every adapter call |
| `spec.model.adapter` | **Enforced**: explicit registry, unknown slug fails closed |
| `spec.authority.tools` | **Fail closed**: a non-empty list refuses to run before any model call (no tool runtime exists) |

### Which remain declarations only?

- `max_output_tokens` is passed to the adapter as declared intent. No token
  usage is measured or enforced.
- `max_latency_ms` has no timeout.
- `observability.*` produces no telemetry.
- `evaluation.*` has no eval suite or runner.
- `data.sensitivity` is a label only.
- `model.profile` is passed through; nothing maps it to a real model.

### Budget and retry policy (as built)

- One unit of budget is consumed immediately **before** each adapter call.
  Every attempt counts, including attempts that raise.
- Schema-invalid output is retried while budget remains. With a limit of 2,
  "invalid, invalid, valid" is scripted, but the third response is **never
  requested**. The run fails with `OutputValidationError` and
  `model_requests_used == 2`.
- Adapter exceptions are **not** retried: `ModelInvocationError`, 1 call.
- A budget of 1 means no retry.
- `RequestBudget.consume()` also raises on its own past the limit, as defense
  in depth.

This retry behavior is **the Phase 3 runtime policy of this template**, not a
universal recommendation for every AI capability.

### What can run without a real model?

Everything in Phase 3. `FakeModelAdapter` is deterministic and offline, needs
no keys and does no I/O:
- `headline` = `"{change_id}: {title}"`;
- `explanation` = file count plus summary;
- `risk_level` comes from a documented **toy** rule on file paths, not a risk
  assessment;
- `open_questions` is empty unless no files are listed.

Scripted mode returns listed responses or exceptions in order and records
every call. That makes invalid output, retries, adapter failures and budget
exhaustion reproducible.

**Why the fake adapter is useful:** it tests the *boundaries*, not the
model. The boundaries are input-before-model, output-after-model, budget
counting, fail-closed configuration and error hygiene. Running without keys,
network, cost or randomness makes them reproducible in CI. The output was
byte-identical across two command-line runs. The fake says nothing about
explanation quality, and that was never its job.

**Mutation evidence:** each boundary was broken in a generated copy, and the
generated suite caught every one:

| Mutation | Result |
|---|---|
| none (baseline) | 32 passed |
| input validated after the model call | 9 failed |
| budget loop allows one extra call | 13 failed |
| unvalidated output accepted | 14 failed |
| adapter exceptions retried | 1 failed |
| declared tools ignored | 1 failed |

The last two are each caught by a single test, so that coverage is thin.

### Input/output validation failures observed

Manual invalid input: `{"change_id": "1042", …, "files_changed":
"src/payments.py"}` gave exit 2, empty stdout, and this on stderr:

```
{"error": "InputValidationError", "message": "input violates schemas/input.schema.json: change_id failed 'pattern'; files_changed failed 'type'", "model_requests_used": 0}
```

The error names the field and rule but not the values `1042` or
`src/payments.py`. Both the generated and platform tests use a marker value
to prove the input and output are not echoed.

**Invalid inputs tested**, none of which invokes the adapter:
- a missing field;
- an extra field;
- a bad `change_id` pattern;
- `files_changed` that isn't a list;
- an empty title;
- a list, a string or `null` instead of an object;
- malformed JSON on the command line.

**Invalid outputs tested**, all rejected:
- non-JSON text;
- a JSON array;
- a missing `risk_level`;
- an extra key;
- an unknown enum value;
- a headline of 121 characters;
- a duplicate JSON key;
- a `NaN` constant;
- non-text `content`;
- a response that isn't a `ModelResponse`.

Duplicate keys and `NaN` are rejected by a strict JSON parser. This is the
Phase 1 duplicate-key lesson applied to model output and input files, not
only to YAML.

### Why schema-valid does not mean runtime-correct

- A manifest can be schema-valid and still unrunnable: an unknown adapter,
  or declared tools with no tool runtime. Both pass the Phase 1 schema, and
  both fail closed only because the runtime checks them.
- A schema-valid manifest *declares* `max_output_tokens: 800` and
  `max_latency_ms: 5000`. Neither is enforced.
- Model output can be schema-valid and still wrong. The fake's
  `risk_level: "low"` for a refactor is valid by construction, and a real
  model could return a valid but misleading explanation. Output validation
  proves shape, not truth. Judging behavior is the job of evaluation
  (Phase 4).
- Passing tests show the runtime enforced these boundaries with a
  deterministic fake. They do not show that any real model or this
  capability is safe or production-ready.

---

## Evaluation

Evidence:
- **Template:** `templates/capability/0.3.0/`, which adds `evals/cases.yaml`,
  `evals/evaluator.py`, `tests/test_evals.py`, and platform snapshots of the
  new canonical `schemas/eval-suite.schema.json` and
  `schemas/eval-report.schema.json`.
- **Platform tests:** `tests/test_template_evals.py` (13 tests). The full
  Lab 04 suite is 235 tests, all passing.
- **Manual run outside the repo:** `ai-golden-path new eval-demo` recorded
  `template_version: "0.3.0"`. `python evals/evaluator.py` exited 0 with the
  gate passed at 8/8. The generated `pytest` passed 58 tests: 32 runtime-
  boundary and 26 eval-kit tests.

### Template versioning

`capability@0.2.0` was frozen as committed. All 11 of its file digests were
added to `FROZEN_TEMPLATES`, next to 0.1.0. The eval kit went into
`capability@0.3.0`. Compared with 0.2.0, the change is:
- **Added:** `evals/cases.yaml`, `evals/evaluator.py`, `tests/test_evals.py`,
  and two platform schema snapshots.
- **Changed:** `contracts.py` (the `Manifest` gains `eval_suite_path` and
  `required_pass_rate`; `load_yaml_strict` becomes public),
  `model_adapter.py` (see below), and a one-line label assertion in
  `test_capability.py`, plus the manifest comment, README and pytest path.
- **Unchanged:** `src/capability.py`. There is no "eval mode".

Phase 8 will work with the real chain: 0.1.0 (contract), 0.2.0 (runtime),
0.3.0 (runtime plus eval kit).

### Cases

Eight synthetic cases. Each has a `property` stating the behavioral promise
it checks.

| Case | Kind | Checks |
|---|---|---|
| `clear-change` | success | `risk_level_in [low]`, no open questions, headline has `CHG-2001`, explanation has `3 file` |
| `ambiguous-change` | success | risk **not** `low`, at least one open question, headline has `CHG-2002` |
| `insufficient-context` | success | risk `unknown`, at least one open question |
| `risky-payment-change` | success | risk `high`, headline has `CHG-2004` |
| `benign-refactor` | success | risk `low`, no open questions |
| `reject-input-missing-summary` | input rejected | `InputValidationError`, 0 model requests |
| `reject-input-bad-change-id` | input rejected | `InputValidationError`, 0 model requests |
| `reject-malformed-model-output` | output rejected | scripted prose, then partial JSON; `OutputValidationError`; 2 of 2 requests used, never 3 |

**The ambiguous case came from an intentional capability behavior change,
not from evaluator calibration.** The sequence was:
1. Define the product expectation: a vaguely described change must not get a
   confident low-risk claim, and should ask what it's meant to do.
2. Change the capability's behavior on purpose: in 0.3.0, a summary of four
   words or fewer gets `risk_level: unknown` plus the open question "What
   behavior is this change meant to alter?". The label becomes
   `fake-deterministic-v2` because the behavior changed.
3. Write the eval that shows the behavior holds.

**Scripted output case.** The evaluator injects
`FakeModelAdapter(scripted=model_script)` through the Phase 3 seam and
reports it as `adapter.source: "scripted"`, never as the configured adapter.
The script is replayed **exactly as written**: the case declares two
malformed responses because `max_model_requests` is 2, and a platform test
asserts that the script length equals the budget. A regression test shortens
the script to one response. The run then fails visibly
(`ModelInvocationError` from the exhausted script) instead of being padded to
pass. Eval case data is evidence; the evaluator interprets it and doesn't
rewrite it.

### Metrics that are genuinely deterministic

Every check is a named, pure function of the case, the manifest and the
real `run()` outcome:
- `outcome` (expected result class);
- `within_request_budget`;
- `output_schema_valid`;
- `risk_level_in` (enum membership);
- `open_questions` (count is 0 or greater than 0);
- `headline_contains` (exact substring);
- `explanation_contains` (case-insensitive substring);
- `no_model_request`;
- `budget_exhausted_not_exceeded`.

There's no model judge, no embeddings, no similarity and no scoring.
**Substring checks are lexical only**: an explanation can contain `CHG-2004`
and still be wrong.

**The gate.** `evaluation.required_pass_rate` moved from **declared** to
**enforced by the eval runner**. The comparison uses exact arithmetic:
`Fraction(passed, total) >= Fraction(str(required))`.
- My first docstring example of the float problem was wrong: `0.7 * 10` is
  exactly `7.0` in floating point.
- A mutation that replaced the gate with `passed >= ceil(rate * total)`
  **survived** the first version of the tests.
- The real example is `0.07 * 100 == 7.000000000000001`. The naive gate
  wrongly fails 7/100 at a required rate of 0.07.
- A test case for that was added, and the mutation is now caught.

The evaluator's exit code is the gate:

| Exit | Meaning |
|---|---|
| 0 | Gate met |
| 1 | Gate not met |
| 2 | Usage error |
| 3 | Malformed manifest, suite or configuration, with no report |

This is not `ai-capability verify`. Phase 7 will combine this gate with other
checks.

**Determinism evidence:**
- Two command-line runs gave byte-identical stdout (10,120 bytes, same
  SHA-256).
- Platform tests show:
  - identical output under `PYTHONHASHSEED=0` and `=1`;
  - identical output for projects generated in different folders;
  - keys are sorted;
  - `suite.sha256` equals the `cases.yaml` bytes;
  - no temp paths, home path, username, dates, UUIDs, or `timestamp`,
    `duration`, `latency`, `tokens`, `cost` or `message` keys;
  - no raw model text: neither the fake's explanation prefix nor the scripted
    prose appears in the report.

**Mutation evidence** (each mutation applied to a generated evaluator, then
its `tests/test_evals.py` run):

| Mutation | Result |
|---|---|
| Pad `model_script` | caught (1 failed) |
| Ignore the outcome check | caught (1 failed) |
| Scripted case reported as the configured adapter | caught (1 failed) |
| Wall-clock time added to the report | caught (11 failed) |
| Suite schema check skipped | caught (5 failed) |
| Float gate | initially **survived**, caught after the fix |

Several mutations are caught by a single test, so that coverage is thin.

### Why negative expected failures count as passing eval cases

A rejection case states a product promise, for example "input without a
summary is refused before any model request". When the expected boundary
rejects the case with the expected error class, and the budget checks hold,
the promise was kept, so the case **passes**.

A regression test shows the reverse: making the bad `change_id` valid causes
the case to *succeed* at runtime, and the eval case then **fails**. Being
rejected by the wrong boundary would also fail.

### The AUTHORS.md false positive (recorded, not fixed)

The fake's toy rule treats any path containing `auth` as high risk. I added a
case to a copy of `eval-demo` without touching `model_adapter.py`:
`docs-only-authors-update`, a documentation-only change to `AUTHORS.md`
expected to be `low`.

- **Result:** evaluator exit **1**, and `eval gate FAILED: 8/9`.
- **The case:** `passed: false`, with failing check `risk_level_in` expected
  `["low"]` but observed `"high"`.
- **Summary:** `observed_pass_rate` dropped to 0.8888888888888888 and
  `gate_passed` is `false`.

A platform regression test keeps this exact evidence. The case is
deliberately **not** in the default suite, and the heuristic was deliberately
**not** fixed to make it pass. It shows that deterministic behavior can be
reproducible and still wrong.

### Malformed suite

With every rejection case removed, the evaluator exited **3** with **0
bytes** on stdout and this on stderr:

```
{"error": "EvalSuiteError", "message": "evals/cases.yaml violates platform/eval-suite.schema.json: cases failed 'contains'"}
```

No partial report is ever printed. Regression tests also cover:
- duplicate IDs;
- a missing `property`;
- an unknown expectation;
- a `model_script` on a success case;
- a success case without expectations;
- duplicate YAML keys;
- a missing suite file;
- declared tools.

### Metrics I should not overclaim

- **`observed_pass_rate` is not accuracy.** It's the fraction of *these
  eight hand-written, declared cases* that met *their own declared
  expectations*. The cases aren't a sample of any real distribution, the
  expectations are chosen by the same people, and negative cases count as
  passes by design.
- **The fake and the suite were developed together.** The fake's rules and
  these expectations were written by the same author in the same phase, so
  cases 1–5 largely confirm that the capability does what it was built to
  do. **A green suite is not independent evidence of model quality.** It
  shows the eval kit works end to end, and gives a regression baseline that
  becomes meaningful when a real adapter is plugged in.
- **The eval format is tied to Change Explainer.** The platform
  `eval-suite.schema.json` hard-codes `risk_level_in` and `headline_contains`,
  which belong to Change Explainer's output. A second capability type
  (Phase 9) will likely need a new or more general expectation vocabulary.
  Recorded, not fixed.

**What a green Phase 4 eval means:** the declared behavioral expectations in
this finite synthetic suite were satisfied by this configured deterministic
adapter.

**What it does NOT mean:**
- model accuracy or general intelligence;
- production correctness or production readiness;
- robustness on unseen inputs;
- safety, fairness or lack of bias;
- real-provider quality;
- semantic truthfulness.

It also says nothing about tokens, latency or cost, which are still only
declared.

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
