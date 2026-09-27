# Phase 7 — Controlled Policy Regression

**Date:** 2026-09-27  
**Outcome:** regression detected by existing tests (1 Rego + 2 Python); unauthorized export **did execute** under the bad policy; secure policy restored from git and verified byte-identical; all suites green again.

No LLM was involved. All data is synthetic. This report contains no customer record content.

---

## 1. Baseline state

| Item | Value |
|---|---|
| Commit | `e1ff451` (phase 6), working tree clean |
| `policies/gateway.rego` SHA-256 | `2876eae013a4d5c967440290df6869d62c1e78d20c84bc2ec5d253d6db157ec8` |
| `policies/gateway.rego` git blob | `f63f418ae99d7e0b475f8d2023bcd00576c7ab6e` |
| `opa test policies` | 59/59 pass |
| `pytest tests/test_gateway_security.py` | 41/41 pass |
| `pytest` (full) | 84/84 pass |

## 2. Exact intentional defect

One added Rego rule. Because Rego rules with the same name are OR-ed, this adds a second, model-controlled source of approval:

```diff
 trusted_human_approval if input.human_approved == true

+trusted_human_approval if input.arguments.human_approved == true # PHASE 7 INTENTIONAL REGRESSION - DO NOT COMMIT
```

Regressed file SHA-256: `7ea9e15c37eb8209c7f5f714481880d685f833f0a191da41ba8ac54c10ddcfc7`. The file still compiled under `opa check --strict`: this is a silent logic defect, not a syntax error.

**Why this is one defect:** `trusted_human_approval` is consulted only for `export_customer_record`, and only after the role/tool check. Refund limits, other roles, unknown role/tool handling, and principal sourcing are untouched. The only exploitable path is: role `compliance` + `arguments.human_approved: true`.

## 3. Expected secure behavior

| Trusted context | Untrusted arguments | Expected |
|---|---|---|
| role `compliance`, `human_approved: false` | `customer_id`, `human_approved: true` | DENY `deny.export.approval_required`; no downstream call; no export |

Approval must come only from trusted gateway context (`input.human_approved`), never from tool arguments.

## 4. Actual insecure behavior

OPA decision for the defect input:

```json
{"allow": true, "rule_id": "allow.export.human_approved",
 "reason": "role 'compliance' is permitted to call 'export_customer_record'"}
```

End-to-end probe (real Gateway, real OPA with the regressed policy, real downstream MCP server and store):

| Case | rule_id | Audit sequence | Downstream calls | `store.exports` count |
|---|---|---|---|---|
| spoofed `arguments.human_approved=true` | `allow.export.human_approved` | requested → allowed → executed | 1 (`export_customer_record`, forwarded keys: `customer_id`) | **1** |
| control: no spoof | `deny.export.approval_required` | requested → denied | 0 | 0 |

**Notable:** the gateway's argument allowlist stripped `human_approved` before forwarding, so the downstream server received a clean `{customer_id}` request. The downstream server had no way to detect the spoof; the only evidence of the breach is the executor ledger and the gateway audit trail (`allowed` with the approval rule_id, while trusted `human_approved` was false). The failing Python test's assertion output also showed the caller receiving a full synthetic customer record from `synthetic-commerce-UNSAFE`.

## 5. Tests that caught it

**Rego — `opa test policies -v`: 58/59 (exit 2)**

- FAIL `test_arguments_human_approved_does_not_approve_export`

**Python — `pytest -v tests/test_gateway_security.py`: 39/41 (exit 1)**

- FAIL `test_16_approval_spoofing_in_arguments_does_not_escalate[human_approved-compliance-export]`
- FAIL `test_16_approval_spoofing_in_arguments_does_not_escalate[everything-compliance-export]`

Both failed on the first assertion (`out.denied`): the caller received a successful export instead of a structured denial.

**Correctly still passing (shows the defect's narrow blast radius):**

- `test_08_compliance_export_without_trusted_approval_denied`: no spoofed field, so still denied. An honest caller would never notice the regression.
- `test_16b_spoofing_via_request_meta_is_ignored`: `_meta` never reaches `arguments`.
- All support/auditor/refund spoof variants: blocked earlier by role or amount rules.

All failures matched the prediction made before running.

## 6. Did an unauthorized side effect execute?

**Yes.** Under the regressed policy, one PII export executed downstream (`store.exports` count 1, audit `downstream_executed: true`) for a principal without trusted approval. This is stronger evidence than the incorrect OPA `allow` alone: it proves the complete PEP → downstream chain carried the bad decision through to a real side effect, and that no later layer (allowlist, downstream contract) compensates for a policy that trusts model-controlled input.

## 7. Recovery verification

Restored with `git restore -- policies/gateway.rego` (not reconstructed by hand).

| Check | Result |
|---|---|
| `git diff -- policies/gateway.rego` | empty (exit 0) |
| SHA-256 after restore | `2876eae013a4d5c967440290df6869d62c1e78d20c84bc2ec5d253d6db157ec8`, matches baseline (`shasum -c`: OK) |
| git blob after restore | `f63f418…` equals index |
| `opa test policies -v` | 59/59 pass |
| `pytest -v tests/test_gateway_security.py` | 41/41 pass |
| `pytest -v` | 84/84 pass |
| Probe, spoofed case | `deny.export.approval_required`, requested → denied, 0 downstream calls, 0 exports |

## Lesson

A one-line, syntactically valid, reasonable-looking policy change turned a model-controlled argument into authority and caused real PII egress. It passed compilation and would pass any test that only exercises honest callers. Only tests that deliberately send spoofed fields **and** check the executor's state caught it. Policy changes are production security changes.
