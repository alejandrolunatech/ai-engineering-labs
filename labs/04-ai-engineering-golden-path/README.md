# Lab 04 — AI Engineering Golden Path

> Build a **reusable, opinionated-but-inspectable golden path** that lets an engineer create a production-minded AI capability with evaluation, observability, budgets, governance hooks, and CI verification built in by default.

**Difficulty:** Senior / Principal AI Platform Engineering  
**Primary gaps:** reusable AI platform primitives, developer self-service, capability contracts, evals, observability, cost controls, governance, template versioning, adoption measurement  
**Stack:** Python 3.11+, Typer, Pydantic, Jinja2, YAML/JSON Schema, pytest, OpenTelemetry  
**Target time:** multi-session; implement phase-by-phase

---

## Why this lab exists

Labs 01 and 02 proved two things:

1. useful AI behavior must be evaluated and observed rather than assumed;
2. model intelligence must not be confused with authority.

This lab moves from **one capability** to **a reusable engineering system**.

The question is:

> **How do we make the safe, observable, evaluated way the easiest way for product teams to build AI capabilities?**

A golden path is not just a starter repository. It is a product for engineers.

It should reduce repeated platform decisions while keeping important behavior visible:

- capability purpose and scope;
- model/provider selection;
- structured input/output contracts;
- tool authority;
- evaluation expectations;
- latency/token/cost budgets;
- telemetry;
- sensitive-data handling;
- policy hooks;
- CI verification;
- template/version provenance.

The central principle is:

> **The golden path turns engineering policy into executable defaults without hiding the architecture.**

---

## Learning objectives

By the end of the lab, I should be able to explain from hands-on experience:

- what belongs in a reusable AI platform primitive versus application code;
- how to define an explicit AI capability contract;
- how to scaffold a new capability with one command;
- how to make evals, tracing, budgets, and governance part of the default developer workflow;
- why generated code should remain inspectable and ownable by the product team;
- how to separate vendor-neutral platform contracts from model-provider adapters;
- how to verify generated projects deterministically before any model call;
- how to version and upgrade templates without silently changing behavior;
- how to expose escape hatches without turning them into invisible bypasses;
- how to measure developer experience, not just model quality;
- how to distinguish a paved road from a mandatory framework;
- what would be required before an internal golden path could serve many enterprise teams.

---

## Product hypothesis

The lab tests this hypothesis:

> An engineer should be able to create a new AI capability in minutes and receive a working project that already contains the engineering controls teams otherwise rediscover independently.

The initial developer journey should eventually look like:

```bash
ai-golden-path new change-explainer
cd change-explainer
ai-capability verify
pytest
```

The generated capability should visibly contain its contract, runtime adapter, evals, telemetry setup, policy hooks, tests, and documentation.

No hidden magic should be required to understand why it works.

---

## What the golden path should generate

A capability should eventually resemble:

```text
change-explainer/
├── capability.yaml
├── README.md
├── pyproject.toml
├── src/
│   ├── capability.py
│   ├── contracts.py
│   ├── model_adapter.py
│   └── telemetry.py
├── evals/
│   ├── cases.yaml
│   └── evaluator.py
├── tests/
│   ├── test_contract.py
│   └── test_evals.py
└── .github/
    └── workflows/
        └── verify.yml
```

The generated repository belongs to the product team. The golden path should not require the team to understand an opaque internal framework to make a small change.

---

## Capability contract

Each generated AI capability should declare, in machine-readable form:

```yaml
api_version: ai.platform/v1
kind: Capability

metadata:
  name: change-explainer
  template_version: "0.1.0"

spec:
  purpose: Explain a synthetic software change in structured language.
  inputs:
    schema: schemas/input.json
  outputs:
    schema: schemas/output.json

  model:
    profile: balanced
    provider: adapter

  authority:
    tools: []

  budgets:
    max_model_requests: 2
    max_output_tokens: 800
    max_latency_ms: 5000

  data:
    sensitivity: synthetic

  evaluation:
    suite: evals/cases.yaml
    required_pass_rate: 1.0

  observability:
    tracing: true
    usage: true
    cost: true
```

The exact schema will be implemented later. The important idea is that the contract is **declared first** and runtime behavior must be checked against it.

---

## Architecture

Read [ARCHITECTURE.md](ARCHITECTURE.md) before implementation.

At a high level:

```text
                          DEVELOPER
                              |
                              v
                   +----------------------+
                   | Golden Path CLI      |
                   | template + contract  |
                   +----------+-----------+
                              |
                         generates
                              |
                              v
+------------------------------------------------------------------+
| Product-team-owned AI capability                                 |
|                                                                  |
| capability.yaml                                                  |
|       |                                                          |
|       +--> contract validation                                   |
|       +--> model adapter                                         |
|       +--> tool/policy boundary                                  |
|       +--> eval harness                                          |
|       +--> observability + usage                                 |
|       +--> budgets                                                |
|       +--> CI verification                                       |
+------------------------------------------------------------------+
                              |
                              v
                   deterministic verifier
                              |
                    PASS / FAIL + evidence
```

---

## Design principles

### 1. Paved road, not prison

The golden path should make the recommended approach cheap and obvious.

Teams may need exceptions. Exceptions should be explicit, reviewable, and measurable rather than hidden.

### 2. Contracts before convenience

Generated capabilities declare their intended behavior and authority.

The CLI is convenience. The contract is the engineering boundary.

### 3. Vendor-neutral core

The platform contract should not depend on one LLM provider.

Provider-specific SDKs belong behind small adapters.

### 4. Evaluation by default

A new AI capability without an eval suite is incomplete.

The scaffold should make the missing eval obvious rather than optional.

### 5. Observability by default

A generated capability should expose enough evidence to answer:

- what model/profile ran?
- how long did it take?
- how many requests/tokens were used?
- what did the evaluation say?
- which capability/template version produced the behavior?

### 6. Authority remains explicit

Tool access must be declared.

A generated capability must not gain a new action because a model requested it.

### 7. Developer experience is measurable

Track at least:

- time-to-first-green;
- number of manual setup steps;
- verification time;
- override/escape-hatch frequency;
- template upgrade effort;
- number of generated files the engineer must understand.

---

## Reference capability

The first generated example will be **Change Explainer**.

It receives synthetic change metadata and produces a structured explanation for a non-specialist stakeholder.

Why this example:

- small enough to understand completely;
- no privileged tools initially;
- useful structured-output contract;
- easy to create positive/negative eval cases;
- later phases can add tracing, cost, model adapters, and policy hooks without business-system dependencies.

Do not use real company data.

---

# Phase plan

## Phase 0 — Environment and baseline

Create the virtual environment and install dependencies.

```bash
cd labs/04-ai-engineering-golden-path
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

No cloud account should be required for the deterministic phases.

---

## Phase 1 — Define the golden-path contract

Do not implement the CLI yet.

Finalize:

- capability manifest fields;
- what is platform-owned versus application-owned;
- deterministic invariants;
- allowed extension points;
- template/version semantics;
- what "verify" must prove;
- what the platform deliberately does not solve.

Create the initial JSON Schema for `capability.yaml` and deterministic schema tests.

**Checkpoint:** if the contract cannot be explained without the CLI, the abstraction is too implicit.

---

## Phase 2 — Scaffold CLI

Implement a small CLI:

```bash
ai-golden-path new <capability-name>
```

It should:

- validate the capability name;
- render a versioned template;
- create inspectable files;
- refuse destructive overwrite by default;
- record template version/provenance;
- produce deterministic output for the same inputs.

No LLM required.

---

## Phase 3 — Reference capability runtime

Make the generated Change Explainer runnable.

Start with a fake/deterministic model adapter for tests.

Then optionally add one real provider adapter behind the same interface.

The generated application must not depend on provider-specific behavior outside the adapter.

---

## Phase 4 — Evaluation kit

Generate an eval suite with every capability.

Include:

- fixtures;
- expected behavioral properties;
- structured-output validation;
- positive and negative cases;
- deterministic evaluator output;
- machine-readable report.

The evaluator should say what was proven, not "the AI is good."

---

## Phase 5 — Observability, usage, and cost

Instrument the reference capability.

Capture:

- capability version;
- template version;
- model/profile;
- latency;
- request count;
- input/output tokens when available;
- estimated cost when pricing metadata is available;
- eval result;
- trace/correlation ID.

Do not record raw sensitive prompts by default.

---

## Phase 6 — Guardrails and policy hooks

Add explicit capability authority.

The generated runtime should:

- declare allowed tools in the contract;
- reject undeclared tools;
- expose a policy hook for privileged actions;
- distinguish proposed, authorized, executed actions.

Do not rebuild Lab 02 inside Lab 04. Reuse the architectural lesson: deterministic authorization belongs outside model judgment.

---

## Phase 7 — One-command verification and CI gate

Implement:

```bash
ai-capability verify
```

It should deterministically check at least:

- capability manifest schema;
- template provenance;
- required files;
- input/output schemas;
- test suite;
- eval threshold;
- declared tools;
- budgets;
- observability configuration.

Exit nonzero on failure.

Generate a CI workflow using the same verifier.

---

## Phase 8 — Template versioning and upgrades

The second template version already exists. Phase 3 added executable runtime
code by creating `capability@0.2.0` instead of editing the released
`capability@0.1.0`, which stays frozen and SHA-256-pinned by tests. Phase 8
should therefore exercise the **real 0.1.0 → 0.2.0 upgrade path**, a
substantial tree change that adds runtime code, tests and a contract snapshot,
rather than inventing a synthetic second version.

Prove that:

- generated projects record which template created them;
- a template change can be classified as compatible or breaking;
- upgrades produce an inspectable diff;
- application-owned changes are not silently overwritten;
- verification detects stale/incompatible contracts.

The lesson:

> **A golden path is a product with lifecycle management, not a one-time code generator.**

---

## Phase 9 — Developer self-service experiment

Generate a second capability from the same platform.

Do not manually copy the first example.

Measure:

- time to scaffold;
- time to first passing verify;
- number of manual edits;
- platform code changes required;
- duplicated application code;
- override count;
- friction encountered.

This is the key proof that the golden path is reusable.

---

## Phase 10 — Independent Codex platform review

Use the prompt in [PROMPTS.md](PROMPTS.md).

Challenge:

- hidden coupling;
- provider lock-in;
- misleading governance claims;
- missing verifier invariants;
- template upgrade hazards;
- excessive abstraction;
- developer friction;
- unbounded tool authority;
- incomplete eval/telemetry defaults;
- security bypasses;
- what blocks enterprise adoption.

---

## Phase 11 — Debrief

Be able to explain:

> "I built a small AI engineering golden path where a developer can scaffold a capability with an explicit contract, evals, observability, budgets, authority declarations, and CI verification already present. I treated developer experience and lifecycle management as part of the platform product, not just the runtime library."

Do not claim the lab is an enterprise internal developer platform.

---

## Definition of Done

```text
[ ] Capability contract is machine validated
[ ] One command scaffolds a capability
[ ] Generated files are inspectable and product-team-owned
[ ] Core contract is provider-neutral
[ ] Fake deterministic model supports offline tests
[ ] Reference capability runs
[ ] Eval suite is generated by default
[ ] Observability/usage is generated by default
[ ] Tool authority is explicit
[ ] Verification exits nonzero on broken invariants
[ ] CI uses the same verifier as local development
[ ] Template version/provenance is recorded
[ ] Upgrade behavior is tested
[ ] Second capability proves reuse
[ ] Developer-experience metrics are recorded
[ ] Independent platform review is complete
[ ] Enterprise gaps are documented
```

---

## Senior-level questions

**Why a golden path rather than a shared AI helper library?**  
Because teams need an end-to-end engineering workflow: contracts, evals, observability, budgets, policy hooks, CI, documentation, and lifecycle management. A helper library solves only runtime reuse.

**Why generate code instead of hiding everything in a framework?**  
Generated code is inspectable, debuggable, and ownable by the product team. The platform should reduce decisions without making behavior mysterious.

**What makes this self-service?**  
A product engineer can create and verify a capability without waiting for a platform engineer to handcraft the project.

**What makes it governed?**  
Important expectations are machine-readable and verified. Governance is implemented as explicit contracts and deterministic checks rather than a document people may ignore.

**Does a golden path guarantee safe AI?**  
No. It creates consistent engineering defaults and evidence. Security, data governance, business authorization, and production operations still require system-specific controls.

**How do you know the platform is useful?**  
Measure adoption and developer friction: time-to-first-green, number of manual setup steps, verification time, override frequency, and upgrade effort.

---

## Final principle

> **The best platform control is one developers receive automatically, can understand locally, and can verify before production.**
