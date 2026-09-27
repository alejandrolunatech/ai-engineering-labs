# Lab 02 — Learning Notes

Complete this file from actual observations. Do not manufacture successful security evidence.

## Before the lab

### What do I currently think "zero trust" means for an AI agent?

_Write here._

### What is the difference between model intent and authorization?

_Write here._

### Which data must never be trusted when supplied by the model?

_Write here._

---

## Threat model

### Most important assets

_Write here._

### Highest-risk tools

_Write here._

### Trusted context

_Write here._

### Untrusted context

_Write here._

---

## Policy contract

### Default-deny behavior

_Write here._

### Argument-level authorization

_Write here._

### Why role and human approval must not be tool arguments

_Write here._

---

## Gateway implementation

### Policy Enforcement Point

_Write here._

### Policy Decision Point

_Write here._

### What happens when OPA is unavailable?

_Write here._

### Can denied calls reach the downstream server?

_Write evidence here._

---

## Deterministic security tests

| Scenario | Expected | Observed |
|---|---|---|
| auditor -> get_order | allow | |
| auditor -> refund | deny | |
| support -> refund €25 | allow | |
| support -> refund €250 | deny | |
| finance -> refund €250 | allow | |
| finance -> refund €750 | deny | |
| support -> export customer | deny | |
| compliance -> export, no approval | deny | |
| compliance -> export, trusted approval | allow | |
| unknown role/tool | deny | |
| OPA unavailable | deny | |
| model spoofs role/admin | deny escalation | |
| model spoofs human approval | deny escalation | |

---

## Prompt-injection experiment

Malicious fixture:

_Write the relevant synthetic text here._

### Requested

What dangerous action did the caller/model attempt?

_Write here._

### Denied

What did the policy deny?

_Write here._

### Executed

What side effect actually reached the downstream server?

_Write here._

### Lesson

> **Attempted prohibited behavior is not the same as successful privilege escalation.**

_Add my own explanation._

---

## Intentional policy regression

### Bad policy change

_Write here._

### Which tests failed?

_Write here._

### Did the policy suite detect the regression before a dangerous downstream action?

_Write here._

### Recovery

_Write here._

---

## Auditability

### Decision fields recorded

_Write here._

### Sensitive fields intentionally excluded

_Write here._

### Can I reconstruct why an action was denied without exposing private payloads?

_Write here._

---

## Deterministic vs probabilistic

### Deterministic controls

_Write here._

### Probabilistic behavior

_Write here._

### What should never be delegated to model judgment?

_Write here._

---

## Enterprise gap analysis

Before real enterprise deployment, what still needs to change?

Consider:

- authentication and workload identity;
- network segmentation and downstream bypass prevention;
- policy distribution/versioning;
- secrets/PII handling;
- approval provenance;
- immutable audit events;
- rate limits and budgets;
- policy decision latency/availability;
- incident response;
- human approval for high-impact actions.

The independent review identified these enterprise gaps:

- **Authenticated identity:** trusted context is outside model arguments, but environment configuration is not authentication.
- **Deployment boundary:** the downstream MCP server is authorization-free; production must make gateway bypass structurally impossible.
- **Approval scope:** the lab approval flag is session-wide. Real approval must bind to an exact action/resource, have provenance/expiry, and prevent replay.
- **Business/resource authorization:** per-call limits are not tenant, customer, case, entitlement, or cumulative-budget authorization.
- **Policy control plane:** OPA is itself an authority and needs protected administration and verified deployment.
- **Execution integrity:** financial actions need executor-side operation IDs, idempotency, durable outcomes, and reconciliation.
- **Audit/provenance:** a local policy hash identifies the expected artifact, not necessarily what remote OPA loaded; JSONL is not tamper-evident.

---

## Codex security review

### Blockers

1. Identity is configured rather than authenticated.
2. The gateway is the intended route but not a proven enterprise deployment boundary.
3. Human approval is reusable/session-wide rather than action-scoped and replay-resistant.
4. Argument authorization lacks resource/tenant/case scope and cumulative budgets.
5. The OPA policy control plane is not hardened as an enterprise authority.

### Important findings

- Prompt injection can cause an executed action without privilege escalation when the injected request stays inside existing authority. A €50 support refund is policy-allowed even if malicious text caused the request.
- Per-call limits do not cap cumulative damage; repetition is part of authorization design.
- Audit filtering minimizes obvious free text but character shape alone does not prove a value is non-sensitive.
- Gateway audit stages are useful evidence, but committed business effects require executor-side durable records and reconciliation.
- The local policy hash identifies the expected artifact, not an attested remote OPA state.
- Policy and execution must share money semantics; fractional euro input exposed a rounding mismatch.

### Nice-to-have improvements

Role-filtered tool discovery, generated boundary tests, additional policy mutation tests, and pinned dependencies.

### Recommendations accepted

- Refund amounts now use integer cents across the tool contract, OPA policy, audit summary, and downstream executor.
- A permanent regression test demonstrates that a prompt-injected but policy-permitted €50 refund can execute.
- Audit documentation now states that format validation is not a sensitivity classifier.
- Enterprise blockers are explicitly documented rather than hidden behind green test results.

### Recommendations intentionally deferred

Authenticated enterprise identity, network/service isolation, action-scoped approval tokens, cumulative transactional budgets, OPA control-plane hardening, deployed-policy attestation, tamper-evident audit storage, and durable transactional reconciliation are platform concerns beyond this synthetic learning lab.

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
