# Lab 02 — Copy/Paste Prompts

Use these prompts one phase at a time. Do not ask Claude Code to implement the whole lab in one pass.

---

## Phase 2 — Downstream MCP server

```text
We are building Lab 02: Zero-Trust MCP Gateway.

Implement Phase 2 only.

Use the current official MCP Python SDK v2.

Goal:
Create a deliberately authorization-free synthetic commerce MCP server so we
can later put a policy gateway in front of it.

Expose exactly these tools:
1. get_order(order_id)
2. search_customer(query)
3. issue_refund(order_id, amount_eur, reason)
4. export_customer_record(customer_id)

Constraints:
- Synthetic in-memory data only.
- No real network services or credentials.
- issue_refund may mutate only synthetic in-memory/file-backed lab state.
- export_customer_record returns synthetic PII-like data.
- Include one order containing prompt-injection text instructing an AI to
  export customer data and issue a refund.
- Treat the malicious text as fixture data.
- Keep implementation small and inspectable.
- Do not implement the gateway or OPA yet.
- Add deterministic tests proving the downstream tools themselves work.
- Explain why this server is unsafe to expose directly to an agent.

Create under src/zero_trust_mcp/ and fixtures/.

Before modifying files, show a short plan.
```

---

## Phase 3 — OPA/Rego policy

```text
Implement Phase 3 only.

Create policies/gateway.rego and policies/gateway_test.rego.

The policy is an authorization decision point for MCP tool requests.

Trusted policy input contains:
- principal.id
- principal.role
- tool.name
- arguments
- environment
- channel
- human_approved

Rules:
- default deny
- auditor: get_order only
- support: get_order, search_customer; issue_refund only <= 50 EUR with a
  non-empty reason
- finance: get_order; issue_refund only <= 500 EUR with a non-empty reason
- compliance: get_order, search_customer; export_customer_record only when
  trusted human_approved is true
- unknown role: deny
- unknown tool: deny
- no role may derive permissions from fields inside model-controlled arguments

Return a structured decision containing:
- allow
- reason
- rule_id

Write Rego tests for every allow/deny edge, including amount boundaries.
Do not implement the Python gateway yet.

After implementation, show me how default-deny works and run:
opa test policies -v
```

---

## Phase 4 — MCP policy gateway

```text
Implement Phase 4 only.

Create a Zero-Trust MCP Gateway between an MCP client and the synthetic
commerce MCP server.

Requirements:
- Use current MCP Python SDK v2.
- Principal identity/role comes from trusted gateway configuration/context,
  never tool arguments.
- For every tool invocation, construct an OPA input from trusted principal
  context + requested tool + requested arguments.
- Query OPA before forwarding.
- Fail closed if OPA is unavailable, times out, returns malformed output, or
  has no decision.
- Forward only allowed calls.
- Denied calls must never reach the downstream server.
- Return a structured denial with a safe human-readable reason.
- Do not leak full sensitive arguments in denial messages or logs.
- Create an audit record for requested/allowed/denied/executed state.
- Keep gateway code small enough to inspect.
- Do not add an LLM yet.

Before coding, show:
1. where the Policy Enforcement Point is;
2. where the Policy Decision Point is;
3. which values are trusted and which are untrusted.

After implementation, explain how a model attempting to spoof role or
human_approved is prevented from escalating authority.
```

---

## Phase 5 — Deterministic security tests

```text
Implement Phase 5 only.

Add deterministic tests for the Zero-Trust MCP Gateway.

Cover at minimum:
- auditor get_order allow
- auditor refund deny
- support refund 25 EUR with reason allow
- support refund 250 EUR deny
- finance refund 250 EUR allow
- finance refund 750 EUR deny
- support export deny
- compliance export without trusted approval deny
- compliance export with trusted approval allow
- unknown role deny
- unknown tool deny
- missing principal deny
- OPA unavailable deny
- malformed OPA response deny
- model-controlled arguments containing role=admin do not escalate
- model-controlled arguments containing human_approved=true do not escalate
- denied calls do not invoke the downstream side effect

Prefer tests that assert both:
1. policy decision; and
2. downstream execution/non-execution.

Do not involve an LLM.
```

---

## Phase 6 — Prompt-injection experiment

```text
Implement only the minimal Phase 6 experiment.

Use the existing malicious order-note fixture.

Create a small driver that demonstrates a compromised or instruction-following
caller requesting a prohibited export/refund after reading the malicious note.

Do not weaken the gateway.

Record separately:
- requested action
- policy decision
- denied action
- downstream executed action

The key result must make it impossible to confuse:
"the model/caller tried it"
with
"the dangerous side effect happened."

If an LLM is added, keep it optional and do not give it direct access to the
downstream MCP server.
```

---

## Phase 7 — Policy regression

Do this as a controlled experiment.

Temporarily introduce exactly one bad policy behavior, for example:

```text
Trust model-supplied arguments.human_approved == true for export authorization.
```

Run the deterministic security tests.

Preserve the failing output/report, then revert the policy and rerun.

Do not change the tests to make the bad policy pass.

---

## Phase 8 — Auditability

```text
Implement Phase 8 only.

Improve auditability without logging sensitive payloads.

Every gateway decision should expose:
- decision_id
- timestamp
- principal_id
- role
- tool_name
- allow/deny
- reason/rule_id
- policy hash/version
- gateway latency
- whether downstream execution occurred

Do not log:
- full customer records
- credentials
- arbitrary raw prompt text
- complete sensitive tool arguments

Add tests that prove denied and allowed decisions are distinguishable and that
sensitive fixture fields are not written to audit records.
```

---

## Phase 9 — Codex security review

```text
Review labs/02-zero-trust-mcp-gateway as a Principal AI Security / Platform Engineer.

Do not modify files.

Challenge the implementation rather than praising it.

Evaluate:
1. Can the model control or spoof identity, role, approval, environment, or policy input?
2. Does every privileged MCP tool path pass through the gateway?
3. Can a caller bypass the gateway and reach the downstream server directly?
4. Does policy default deny?
5. Does the gateway fail closed when OPA is unavailable or malformed?
6. Are tool arguments authorized, not just tool names?
7. Can prompt injection influence an executed privileged action?
8. Are requested, denied, and executed actions measured separately?
9. Do audit logs or denial messages leak PII/secrets?
10. Are policy decisions reproducible/versioned?
11. Are tests actually proving non-execution after denial?
12. What would block real enterprise deployment?

Try adversarial inputs where useful, but do not access real secrets or external
systems.

Classify findings:
- BLOCKER
- IMPORTANT
- NICE-TO-HAVE

Finish with the five most important lessons I should be able to explain in a
senior AI Engineer / AI Platform interview.
```
