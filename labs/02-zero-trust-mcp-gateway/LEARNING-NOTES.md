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

_Write here._

---

## Codex security review

### Blockers

_Write here._

### Important findings

_Write here._

### Nice-to-have improvements

_Write here._

### Recommendations accepted

_Write here._

### Recommendations intentionally deferred

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
