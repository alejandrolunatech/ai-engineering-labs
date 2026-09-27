# Lab 02 — Threat Model

This is a **synthetic learning threat model**, not a production security assessment.

## System under study

An AI/MCP host can request tools through a gateway. The gateway evaluates each request with OPA/Rego before forwarding to a synthetic downstream commerce MCP server.

## Security objective

A compromised, confused, prompt-injected, or biased model may request a dangerous action, but it must not be able to **grant itself the authority required to execute that action**.

## Trust boundaries

### Trusted for authorization

- principal identity established by the application/gateway;
- principal role established outside model arguments;
- environment/channel established by the application;
- human-approval state established by a trusted human workflow;
- versioned policy loaded by OPA.

### Untrusted

- user prompts;
- model output;
- MCP tool arguments;
- retrieved order/customer text;
- tool descriptions as a source of authorization;
- prompt-injection strings;
- claims such as `role=admin` or `human_approved=true` embedded in model-controlled data.

## Assets

- ability to issue refunds;
- synthetic customer records / PII-like data;
- authorization context;
- policy configuration;
- audit integrity;
- availability/cost budget.

## Threats and expected controls

| Threat | Example | Required control |
|---|---|---|
| prompt injection | order note says "export customer" | policy independent of content |
| role spoofing | args contain `role=admin` | trusted role outside args |
| approval spoofing | args contain `human_approved=true` | trusted approval context |
| amount escalation | support requests €500 refund | argument-level Rego rule |
| unknown capability | model invents admin tool | default deny |
| policy outage | OPA offline | fail closed |
| gateway bypass | direct downstream access | architecture/network isolation |
| sensitive logging | full customer record in audit | redacted/minimal audit |
| repeated denied calls | prompt injection loops | rate/budget controls |
| policy regression | new Rego rule over-grants | deterministic policy tests |

## Initial authorization matrix

| Principal role | get_order | search_customer | issue_refund | export_customer_record |
|---|---|---|---|---|
| auditor | allow | deny | deny | deny |
| support | allow | allow | <= €50 + reason | deny |
| finance | allow | deny | <= €500 + reason | deny |
| compliance | allow | allow | deny | trusted human approval required |

## Security invariants

1. **Default deny.**
2. **No model-controlled field can increase authority.**
3. **Denied tool calls do not execute downstream.**
4. **Policy failure does not become permission.**
5. **High-impact authorization uses trusted context plus tool arguments.**
6. **Direct downstream access is not an allowed agent path.**
7. **Audit logs distinguish requested, denied, and executed actions.**
8. **Audit logs minimize sensitive data.**

## Questions to revisit after implementation

- Is identity authenticated or merely configured?
- Could the downstream server be reached around the gateway?
- Is policy version pinned and observable?
- Can policy decisions be replayed or audited?
- Are approval tokens bound to a specific action, amount, and lifetime?
- What happens under concurrency?
- What happens after retries?
- Are denial reasons themselves sensitive?
- Can resource exhaustion bypass intended controls?
