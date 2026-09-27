# Lab 04 — Architecture Contract

This document defines the intended architecture before implementation.

## Platform product

The golden path has five product surfaces:

1. **Capability contract** — machine-readable intent, authority, budgets, eval and observability expectations.
2. **Scaffold CLI** — creates an inspectable product-team-owned capability from a versioned template.
3. **Runtime primitives** — small adapters/contracts shared where reuse is genuinely valuable.
4. **Verifier** — deterministic local/CI checks that turn platform expectations into executable evidence.
5. **Template lifecycle** — provenance, compatibility, and upgrade mechanics.

The platform is not successful merely because code can be generated.

It is successful when another engineer can create, understand, verify, and evolve a capability with less friction and fewer missing engineering controls.

---

## Ownership boundary

### Platform-owned

- capability schema;
- template catalog;
- scaffold CLI;
- verifier rules;
- provider adapter protocol;
- telemetry contract;
- eval report format;
- template version metadata.

### Product-team-owned after generation

- capability purpose;
- prompts/instructions;
- domain schemas;
- fixtures/evals;
- application logic;
- approved tool list;
- provider configuration;
- business policy integration;
- deployment configuration.

The platform must not silently rewrite product-owned code during upgrades.

---

## Components

```text
+--------------------+
| Developer          |
+---------+----------+
          |
          | ai-golden-path new
          v
+-----------------------------+
| Scaffold CLI                |
| - validate inputs           |
| - select template/version   |
| - render inspectable files  |
+--------------+--------------+
               |
               v
+--------------------------------------------------+
| Generated capability                             |
|                                                  |
| capability.yaml --> contract validator           |
|        |                                         |
|        +--> runtime --> provider adapter          |
|        +--> tool registry / policy hook           |
|        +--> eval runner                           |
|        +--> telemetry                             |
|        +--> budgets                               |
|        +--> docs/tests                            |
+-------------------------+------------------------+
                          |
                          | ai-capability verify
                          v
+--------------------------------------------------+
| Deterministic verifier                           |
| schema | tests | eval | authority | budgets | DX |
+-------------------------+------------------------+
                          |
                     pass / fail
                          |
                       local + CI
```

---

## Deterministic invariants

The verifier should eventually enforce:

- manifest matches the supported schema;
- capability name/version are valid;
- template version/provenance are present;
- declared schema files exist;
- outputs validate against declared schema;
- eval suite exists and meets configured threshold;
- requested tools are a subset of declared tools;
- numeric budgets are positive and bounded;
- telemetry cannot be silently disabled when contract says it is required;
- provider-specific settings remain behind the adapter boundary;
- generated project contains no secret values;
- verifier failure returns a nonzero process exit code.

These are engineering invariants, not LLM judgments.

---

## Probabilistic responsibilities

Model reasoning may determine:

- the generated natural-language explanation;
- which permitted context is relevant;
- which permitted tool it wants to request;
- how it expresses an answer within the output contract.

Model reasoning must not determine:

- its own identity/role;
- what tools are authorized;
- whether evals can be skipped;
- whether a failed verifier counts as success;
- whether a budget is exceeded;
- whether a schema-invalid output is accepted.

---

## Extension points

Allowed extension points should be explicit:

- provider adapter;
- evaluator plugin;
- telemetry exporter;
- policy hook;
- domain schemas;
- additional template.

An extension point must have a contract and tests.

Avoid generic "plugin systems" before a real extension need exists.

---

## Escape hatches

A golden path that cannot accommodate exceptions will be bypassed.

Escape hatches may be allowed, but they should be:

- explicit in the manifest;
- surfaced by `verify`;
- reviewable in code review;
- measurable in adoption reports;
- unable to silently disable hard security boundaries.

Example future shape:

```yaml
exceptions:
  - id: custom-provider
    reason: Required for an approved internal model endpoint.
    owner: team-example
```

The lab will not treat an exception as automatically safe.

---

## Provider neutrality

Core code should depend on a small internal protocol such as:

```python
class ModelAdapter(Protocol):
    async def generate(self, request: ModelRequest) -> ModelResponse: ...
```

Provider-specific SDK objects must not leak across the application boundary.

Tests should use a deterministic fake adapter first.

---

## Evidence model

A successful verification should produce machine-readable evidence including:

- capability name/version;
- template version;
- verifier version;
- schema result;
- test result;
- eval result;
- declared authority;
- budget configuration;
- telemetry configuration;
- warnings/exceptions.

A green result means the declared checks passed.

It does **not** mean the capability is universally correct, safe, unbiased, secure, or production-ready.

---

## Developer-experience evidence

The platform itself should be evaluated.

Record:

```text
scaffold_seconds
manual_setup_steps
time_to_first_green_seconds
verify_seconds
number_of_overrides
template_upgrade_conflicts
platform_changes_needed_for_second_capability
```

The golden path should earn adoption rather than relying on mandate.

---

## Enterprise gaps intentionally outside the initial lab

The lab will not initially provide:

- enterprise identity federation;
- production secrets distribution;
- production model gateway;
- organization-wide data classification;
- full policy administration;
- deployment orchestration;
- multi-tenant control plane;
- production artifact signing;
- centralized telemetry backend;
- organizational chargeback.

Those are valid platform concerns but would obscure the core learning objective if built first.
