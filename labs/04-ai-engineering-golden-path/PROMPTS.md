# Lab 04 — Copy/Paste Prompts

Use one phase at a time. Do not ask an implementation agent to build the entire golden path in one pass.

---

## Phase 1 — Capability contract

```text
Implement Phase 1 only for Lab 04: AI Engineering Golden Path.

Read README.md and ARCHITECTURE.md first.

Do not implement the scaffold CLI or model runtime yet.

Goal:
Define the machine-readable capability contract and the deterministic invariants
the future verifier will enforce.

Create:
- schemas/capability.schema.json
- examples/change-explainer/capability.yaml
- tests/test_capability_schema.py

The manifest must cover at minimum:
- api_version / kind
- metadata.name
- metadata.template_version
- purpose
- input schema path
- output schema path
- model profile/provider abstraction
- declared tools
- request/token/latency budgets
- data sensitivity
- eval suite + required threshold
- observability requirements

Constraints:
- vendor-neutral core;
- no LLM call;
- deterministic tests only;
- unknown fields should be handled intentionally, not accidentally;
- malformed budgets, undeclared authority, missing schemas and invalid names must fail validation;
- do not invent enterprise claims.

Before coding, show:
1. proposed schema shape;
2. hard invariants versus advisory metadata;
3. platform-owned versus application-owned fields;
4. likely future migration/versioning problem.

After coding run the focused tests and do not commit.
```

---

## Phase 2 — Scaffold CLI

```text
Implement Phase 2 only.

Create a small Typer CLI:
    ai-golden-path new <capability-name>

Render a versioned Change Explainer template using Jinja2.

Requirements:
- validate names;
- deterministic output for same inputs;
- refuse overwrite unless an explicit future-safe mechanism is used;
- write capability/template provenance;
- generated files remain readable and editable;
- no hidden framework state;
- no LLM;
- no network;
- no secrets.

Add tests for happy path, invalid names, existing destination, deterministic
generation and provenance.

Before coding show the generated file tree and ownership boundary.
Do not implement runtime/evals beyond placeholders required by the template.
Do not commit.
```

---

## Phase 3 — Reference capability runtime

```text
Implement Phase 3 only.

Make the generated Change Explainer executable.

Start with a deterministic FakeModelAdapter used by all tests.

Define a small provider-neutral ModelAdapter protocol and structured request/
response models.

The capability must:
- load/validate capability.yaml;
- validate input before model invocation;
- validate structured output after invocation;
- enforce max model request count;
- expose provider/model metadata without leaking provider SDK types;
- fail explicitly on invalid output.

Do not add a real model provider unless the deterministic implementation and
tests pass first.

Do not implement later eval/telemetry phases yet.
Do not commit.
```

---

## Phase 4 — Evaluation kit

```text
Implement Phase 4 only.

Every scaffolded capability must include an eval suite and deterministic runner.

For Change Explainer create synthetic cases covering:
- clear change;
- ambiguous change;
- missing/insufficient context;
- risky change;
- benign refactor;
- malformed input/output negative cases.

Produce a machine-readable eval report.

Keep deterministic structural checks separate from any optional model-based judge.

A pass means the declared eval contract passed; do not call it "accuracy" unless
the metric actually measures accuracy.

Add regression tests.
Do not commit.
```

---

## Phase 5 — Observability, usage, and cost

```text
Implement Phase 5 only.

Add OpenTelemetry-style tracing/structured telemetry to the reference capability.

Capture:
- capability name/version;
- template version;
- adapter/model profile;
- request count;
- latency;
- input/output tokens when known;
- estimated cost only when pricing metadata is explicitly configured;
- eval/verification correlation id.

Do not log raw sensitive prompts by default.

Represent unknown token/cost data as unknown, not zero.

Add deterministic tests for success and failure telemetry.
Do not commit.
```

---

## Phase 6 — Guardrails and policy hooks

```text
Implement Phase 6 only.

Add explicit tool authority to the generated runtime.

Requirements:
- tool names come from capability.yaml;
- undeclared tool requests are rejected deterministically;
- a policy hook can authorize high-impact tools;
- model output cannot expand the allowlist;
- record proposed / authorized / executed separately;
- do not copy Lab 02 wholesale;
- no direct privileged side effect in tests: use synthetic tools.

Add adversarial tests for model-supplied tool names/authority claims.
Do not commit.
```

---

## Phase 7 — Verification + CI

```text
Implement Phase 7 only.

Create:
    ai-capability verify

It must run deterministic checks for:
- capability schema;
- referenced schemas/files;
- template provenance;
- tests;
- eval threshold;
- declared tools;
- budget fields;
- observability configuration.

Return nonzero on failure.

Generate a GitHub Actions workflow that invokes the same verifier rather than
reimplementing checks in YAML.

Produce a machine-readable verification report.
Do not commit.
```

---

## Phase 8 — Template upgrade

```text
Implement Phase 8 only.

A second template version already exists: capability@0.2.0 (Phase 3) added
runtime code while capability@0.1.0 stayed frozen. Use the real
0.1.0 -> 0.2.0 upgrade as the primary case. Classify it as compatible or
breaking, and only add a further version if the lab needs another change type.

Build an inspectable upgrade workflow.

Prove:
- generated project records old template version;
- upgrade identifies proposed changes;
- application-owned edits are not silently overwritten;
- incompatible contract versions fail verification;
- dry-run produces an understandable diff/plan.

Do not build a complex package manager.
Do not commit.
```

---

## Phase 9 — Developer self-service experiment

```text
Implement Phase 9 only.

Generate a second synthetic capability using the existing golden path.

Do not manually copy Change Explainer.

Measure:
- scaffold time;
- manual setup steps;
- time to first green verification;
- verification duration;
- overrides;
- platform code changes required;
- duplicated application code.

Record findings in reports/developer-self-service.md.

If a second capability requires platform changes, treat that as product evidence,
not something to hide.
Do not commit.
```

---

## Phase 10 — Independent Codex review

```text
Review labs/04-ai-engineering-golden-path as a Principal AI Platform Engineer.

Do not modify files.

Challenge:
1. Is the capability contract actually useful or ceremonial?
2. Can generated applications bypass declared contracts?
3. Is provider neutrality real or cosmetic?
4. Are evals and telemetry present by default and meaningful?
5. Can teams silently disable budgets/guardrails?
6. Does verify prove what the README claims?
7. Are generated files understandable and product-team-owned?
8. Are template upgrades safe and inspectable?
9. Does the platform create more cognitive load than it removes?
10. What evidence shows developer self-service improved?
11. What would block enterprise-wide adoption?
12. Which abstractions are premature?

Try adversarial generated projects and broken manifests where useful.

Classify findings:
- BLOCKER
- IMPORTANT
- NICE-TO-HAVE

Finish with five senior/principal AI platform interview lessons.
```
