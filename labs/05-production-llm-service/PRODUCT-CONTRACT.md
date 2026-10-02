# ChangeBrief — Product Contract (V1)

- Contract version: `0.1` (Phase 0)
- Date: 2026-10-02
- Status: **design contract — nothing here is implemented or measured yet**

This document defines what ChangeBrief V1 is, what it is not, what it is allowed to consume, and what must be true before it may be called production. It is the reference later phases implement against. Executable schemas arrive in Phase 1; until then this file is the contract.

Related documents: [README.md](README.md) (canonical lab instructions and DoD), [ARCHITECTURE.md](ARCHITECTURE.md), [THREAT-MODEL.md](THREAT-MODEL.md), [RELEASE-CHECKLIST.md](RELEASE-CHECKLIST.md), [PRODUCTION-EVIDENCE.md](PRODUCTION-EVIDENCE.md).

## How to read this contract

Every statement carries exactly one label:

| Label | Meaning | Who/what enforces it |
|---|---|---|
| `[BOUNDARY]` | **Deterministic boundary.** Same input → same decision, every time. | Code, configuration, or platform policy — never prompt text. |
| `[MODEL]` | **Probabilistic behavior.** What the LLM is asked or expected to do. May fail on any given request. | Prompt + output schema + evals reduce failure; nothing guarantees it. |
| `[TARGET]` | **Product target.** An intention we will measure against. Not a claim. | Evaluated later with evidence; may be revised. |
| `[MEASURED]` | **Measured production fact.** Observed in production with a recorded sample/time window. | Recorded in PRODUCTION-EVIDENCE.md. |

**Current count of `[MEASURED]` statements: 0.**

Rule `[BOUNDARY]`: a `[MODEL]` or `[TARGET]` statement can never be cited as if it were `[BOUNDARY]` or `[MEASURED]`.

---

## 1. Users

- `[TARGET]` **Primary user:** an engineering manager or delivery lead who needs to understand a public PR they did not write, quickly, without reading the diff.
- `[TARGET]` **Secondary users:** engineers onboarding to a repository, product managers, and other stakeholders.
- `[BOUNDARY]` Users are anonymous. There are no accounts, logins, or per-user state in V1.

### What "useful to a stranger" means

- `[TARGET]` Someone who did not write the PR can read the brief in **under two minutes** and correctly decide:
  1. whether the change needs their attention;
  2. what it affects;
  3. what is still unknown.
- `[TARGET]` This definition is the yardstick for later evals and UX work. The two-minute figure and "correctly decide" are not yet measured, and Phase 0 defines no method to measure them (see §9).

---

## 2. Supported input

- `[BOUNDARY]` Exactly one input: a URL with the exact shape `https://github.com/<owner>/<repo>/pull/<number>`.
- `[BOUNDARY]` Only **public** GitHub repositories are supported. A PR the anonymous GitHub API cannot read is reported as not found/unavailable, never retried with credentials.
- `[BOUNDARY]` The server parses the URL into `owner`, `repo`, and `number`, validates each part, and **builds the `api.github.com` endpoints itself**. A user-supplied URL is never fetched.
- `[BOUNDARY]` Rejected before any external call: non-HTTPS schemes, hosts other than exactly `github.com` (including lookalikes), explicit ports, embedded credentials, malformed paths, non-numeric or out-of-range PR numbers. (Exact parser rules and tests: Phase 1.)
- `[BOUNDARY]` Query strings, fragments, and trailing path segments (e.g. `/files`) are either rejected or explicitly normalized by the parser. Which of the two is a Phase 1 decision, and it must be tested either way.

---

## 3. Structured output

The response is a validated structured object. Field names below are **proposed**; the versioned schema is created in Phase 1 and hardened in Phase 4.

### 3a. Model-generated fields — content is `[MODEL]`

The model writes the content of these fields. Their **shape** is enforced by validation (`[BOUNDARY]`); their **truthfulness** is not.

| Field | Intent |
|---|---|
| `summary` | What changed, in plain language. |
| `why_it_matters` | Why a stakeholder might care. |
| `user_impact[]` | Effects on end users / business, **only where the PR evidence supports it**. |
| `technical_impact[]` | Systems, modules, interfaces, data affected. |
| `risk.level` | Change risk (blast radius × uncertainty). **Not** a code-quality score or verdict (see non-goal 3). |
| `risk.evidence[]` | PR evidence the risk level is based on. |
| `risk.uncertainty[]` | What the risk assessment cannot see. |
| `testing_signals[]` | Testing visible in the PR data (e.g. test files changed, testing notes in the description). Never claims tests passed. |
| `rollout_considerations[]` | Rollout notes supported by the evidence. |
| `rollback_considerations[]` | Rollback notes supported by the evidence. |
| `open_questions[]` | What a reader should still ask the author. |
| `limitations[]` | What the model could not assess. |

- `[MODEL]` The model is instructed to ground every statement in the supplied PR evidence and to say "unknown" (via `open_questions`/`limitations`/`risk.uncertainty`) rather than invent.
- `[MODEL]` The model is instructed to treat PR content as data to describe, never as instructions to follow.
- `[MODEL]` Any field may still be wrong, incomplete, or unsupported on a given request. Evals (Phase 4) measure how often; they do not eliminate it.

### 3b. Server-generated fields — `[BOUNDARY]`

These come from code, not from the model. The model is never trusted to report them.

| Field | Source |
|---|---|
| `pr` (`owner`, `repo`, `number`) | URL parser |
| `truncated` | Evidence builder (§5) |
| `truncation_limitations[]` | Evidence builder: which budget was hit, in deterministic wording |
| `files_considered` / `files_total` | Evidence builder |
| `schema_version`, `prompt_version` | Server configuration |
| `model` (exact ID) | Server configuration / provider response |
| `usage`, `estimated_cost` | Provider-reported usage + dated pricing; `null`/`unknown` when either is unavailable, **never zero** |
| `ai_generated: true` | Always set |

- `[BOUNDARY]` Model output that fails schema validation never reaches the UI. The user gets a controlled "model output invalid" failure.
- `[BOUNDARY]` All model and PR text is rendered as text, never as raw HTML.
- `[BOUNDARY]` If evidence was truncated, the user-visible output shows `truncated=true` plus a server-written limitation, whatever the model says.

---

## 4. Non-goals (V1)

All are `[BOUNDARY]`. They are enforced by not building the capability, not by asking the model to refrain.

1. `[BOUNDARY]` No private repositories and no GitHub authentication for users.
2. `[BOUNDARY]` No writing to GitHub: no comments, labels, reviews, or approvals. No GitHub credential with write scope exists in the system.
3. `[BOUNDARY]` No code-review verdicts. ChangeBrief explains a change. It does not approve, reject, or score code quality. The output schema has no approve/reject/quality-score field. (`risk.level` describes change risk, not code quality.)
4. `[BOUNDARY]` No whole-repository analysis, cloning, or fetching files outside the PR. Only the PR metadata and PR changed-files endpoints are called.
5. `[BOUNDARY]` No user accounts, saved history, or stored briefs.
6. `[BOUNDARY]` No model tool calling or agentic behavior. The model gets one request with no tools and returns one structured response.
7. No claims about tests passing, deployment status, or business intent unless they appear in the PR evidence.
   - `[BOUNDARY]` The server supplies no CI status, deployment status, or business data to the model, so it has no authoritative source for such claims.
   - `[MODEL]` Not inventing them anyway is model behavior, mitigated by instructions and measured by missing-context evals (Phase 4).
8. No guarantee of correctness.
   - `[BOUNDARY]` Output is always labelled as AI-generated, and uncertainty fields are always rendered.
   - `[MODEL]` The explanation itself may be wrong.

---

## 5. Initial budgets

Every value below is **initial, calibrate in Phase 2** against representative public PR fixtures. Each is a `[BOUNDARY]`: once implemented, code enforces it, and it is not a measured fact about real PRs.

| Budget | Initial value | Over-budget behavior | Label |
|---|---|---|---|
| Max request body | 2 KB | **Rejected** (request too large). No external call. | `[BOUNDARY]` |
| Max changed files considered | 50 | Truncated: first 50 in GitHub API order; `truncated=true` + limitation | `[BOUNDARY]` |
| Max patch characters per file | 4,000 | Truncated per file; `truncated=true` + limitation | `[BOUNDARY]` |
| Max total normalized evidence | 60,000 characters | Truncated; `truncated=true` + limitation | `[BOUNDARY]` |
| Max PR body (description) | 4,000 characters | Truncated; `truncated=true` + limitation | `[BOUNDARY]` |
| Max GitHub API requests per analysis | 3 | No further requests; any unfetched data is reported as truncated | `[BOUNDARY]` |
| GitHub request timeout | 10 s | Controlled "upstream unavailable" failure | `[BOUNDARY]` |
| LLM calls per analysis | At most 1 (exactly 1 on any path that reaches the model) | No automatic retries | `[BOUNDARY]` |
| Max model output tokens | 1,500 | Provider stops generating; incomplete output fails validation → controlled failure | `[BOUNDARY]` |
| LLM provider timeout | 30 s | Controlled "provider unavailable" failure | `[BOUNDARY]` |

- `[BOUNDARY]` Truncation is deterministic. The same PR state and the same budgets always produce the same evidence envelope.
- `[BOUNDARY]` Truncation is never hidden. It is reported as `truncated=true` plus a limitation, to both the model input and the user-visible output.
- `[TARGET]` "60,000 characters ≈ 15k tokens" is a rough planning heuristic, not a measurement. Real token counts depend on the model's tokenizer and on content (code tokenizes differently from prose). Phase 5 records provider-reported tokens.
- `[BOUNDARY]` Worst-case work per analysis is bounded by construction: ≤ 3 GitHub requests, ≤ 1 model call, ≤ 60,000 evidence characters in, ≤ 1,500 tokens out, ≤ 10 s per GitHub request and ≤ 30 s for the model call.

---

## 6. Initial operational targets

All `[TARGET]` unless labelled otherwise. None is a claim or an SLO.

- `[TARGET]` One successful LLM call per successful analysis. (The *ceiling* of one call is `[BOUNDARY]`, §5.)
- `[TARGET]` Zero raw PR titles, bodies, patches, prompts, or model outputs in operational telemetry. (The allowlisted telemetry schema that enforces this is a `[BOUNDARY]` from Phase 5. Verifying it in production is a future `[MEASURED]` log review.)
- `[TARGET]` Every failure maps to one of the small user-facing categories in ARCHITECTURE.md (invalid URL, not found/unavailable, too large, rate limited, provider unavailable, output invalid, service disabled, internal error).
- `[TARGET]` Truncation and uncertainty are visible to the user on every brief where they apply.
- `[TARGET]` p95 total latency: **TBD**, chosen only after a baseline measurement on a representative request set.
- `[TARGET]` Maximum estimated model cost per request: **TBD**, chosen only after the Phase 3 model and pricing decision plus Phase 5 measurements.
- `[TARGET]` Availability target: **none set**. A self-directed V1 states no availability number until it has measured uptime.
- `[TARGET]` Public rate-limit value: **TBD**, chosen in Phase 6.

---

## 7. Production Definition of Done

The canonical checklist is in [README.md § Production Definition of Done](README.md#production-definition-of-done). This section classifies each item by the kind of evidence that closes it. A tick counts only when that evidence exists, and anything that changes the README list must change this table too.

| DoD item (README) | Requirement kind | Evidence that closes it |
|---|---|---|
| Real OpenAI integration deployed server-side | `[BOUNDARY]` | Deployed code + production request log |
| Production secret storage; no secret committed | `[BOUNDARY]` | Platform env config (names only) + repo history check |
| Public HTTPS responds from outside dev machine | `[MEASURED]` | External smoke request |
| Custom domain connected | `[MEASURED]` | DNS + HTTPS check from outside |
| Only public GitHub PRs accepted | `[BOUNDARY]` | Parser/ingestion tests + production failure-path request |
| Arbitrary outbound URL fetch impossible | `[BOUNDARY]` | Parser tests + code review that no `fetch(userInput)` exists |
| Input budgets/truncation enforced | `[BOUNDARY]` | Tests at each §5 budget + oversized fixture |
| Structured output validation enforced | `[BOUNDARY]` | Invalid-output tests |
| Public rate limiting active | `[BOUNDARY]` | Config + production 429 observed |
| Provider/account spend controls configured | `[BOUNDARY]` | Provider dashboard config (no secrets) |
| Kill switch documented and tested | `[BOUNDARY]` | RUNBOOK entry + recorded test |
| Telemetry records total/GitHub/LLM latency separately | `[BOUNDARY]` | Telemetry schema + sample production events |
| Provider-reported token usage captured when available | `[BOUNDARY]` | Sample production events; unknown stays `null` |
| Cost estimate from dated pricing snapshot | `[BOUNDARY]` | Pricing metadata with model ID, date, source URL |
| No raw content in operational logs | `[BOUNDARY]` | Redaction tests + manual production log review |
| Eval gate passes for selected model/config | `[MODEL]` | Recorded eval run (pass rate is model behavior, measured on a finite set) |
| CI passes | `[BOUNDARY]` | CI run link |
| Production smoke test passes | `[MEASURED]` | Smoke run record |
| ≥ 1 real external non-local request succeeds | `[MEASURED]` | PRODUCTION-EVIDENCE.md entry |
| ≥ 1 safe failure path exercised in production | `[MEASURED]` | PRODUCTION-EVIDENCE.md entry |
| Real production measurements recorded | `[MEASURED]` | PRODUCTION-EVIDENCE.md measurement window |
| README live link only after verification | `[BOUNDARY]` | Process rule; link added in Phase 9 |
| RUNBOOK reflects deployed system | `[BOUNDARY]` | RUNBOOK review against deployment |

Phase 0 additions to the DoD:

- `[BOUNDARY]` All §4 non-goals still hold in the deployed system.
- `[BOUNDARY]` The deployed budgets match this contract, or this contract has been updated with the calibrated values and the reason for each change.

---

## 8. What counts as production evidence

- `[BOUNDARY]` Production evidence comes from the **deployed public service**: production logs, provider usage records, deployment records, and external requests. It is recorded in PRODUCTION-EVIDENCE.md with a date/time window and sample size.
- `[BOUNDARY]` The following are **not** production evidence: local runs, unit/integration tests, eval runs, preview deployments, CI passing, config files existing, or this contract. They support release decisions but prove nothing about production behavior.
- `[BOUNDARY]` Percentiles (p50/p95) are reported only with their sample size and window, and only once that sample is meaningful.
- `[BOUNDARY]` Estimated cost is always labelled an estimate tied to an exact model ID and a dated pricing source. It is never presented as provider billing.
- `[BOUNDARY]` Evidence never includes raw PR patches/bodies, prompts, model outputs, secrets, cookies, or full client IPs.
- `[BOUNDARY]` Traffic, latency, cost savings, availability, quality, testimonials, and scale are never fabricated or extrapolated.

---

## 9. Must remain unknown until measured

Each item below is **unknown** today. It may be filled in only with recorded evidence, at or after the phase listed.

| Unknown | Earliest phase | Becomes |
|---|---|---|
| Exact model ID and pricing snapshot | 3 | Recorded decision (pricing is a dated external fact, not a measurement) |
| Tokens per request (input/output) | 3 (first), 5 (distribution) | `[MEASURED]` (eval/local), production in 10 |
| Estimated cost per request | 5 | Estimate derived from measured tokens + dated pricing |
| LLM latency, GitHub latency, total latency | 5 (local/eval), 10 (production) | `[MEASURED]` |
| p50/p95 latency | 10 | `[MEASURED]` with sample size + window |
| Eval pass rate / model quality | 4 | Measured on a finite eval set, never universal quality |
| How often real PRs exceed budgets (truncation rate) | 2 (fixtures), 10 (production) | `[MEASURED]` |
| Whether budget values are right | 2 | Calibrated `[BOUNDARY]` values + rationale |
| GitHub unauthenticated rate-limit pressure in practice | 2 / 10 | `[MEASURED]` |
| Failure / rate-limit rates | 10 | `[MEASURED]` |
| Availability | 10+ | `[MEASURED]` over a stated window, if at all |
| Whether briefs meet the "useful to a stranger" target (§1) | 4 / 10 | Needs a measurement method, not yet defined. Until one exists, usefulness is unproven. |
| Real external users / traffic volume | 10 | `[MEASURED]`, never inferred |

---

## 10. Open questions carried forward

These are known tensions Phase 0 does not resolve. They are written down so they are not lost.

- `[BOUNDARY]` THREAT-MODEL.md §5 says to *reject* beyond a hard upper boundary, while this contract *truncates* evidence over budget. With a 3-request GitHub cap the fetched data is bounded either way. Phase 2 decides whether an extreme PR (for example one whose file count makes a 50-file sample misleading) should be rejected rather than truncated.
- `[BOUNDARY]` Request budget arithmetic: PR metadata (1) + changed files (1 page at 50 files) = 2 requests, which leaves 1 spare. Phase 2 confirms against the real GitHub API how many requests are actually needed and what the spare one is for, if anything.
- `[TARGET]` How to measure the "under two minutes / correctly decide" usefulness target (§1). Candidate approaches belong in Phase 4 (eval rubric) or Phase 10 (real users). None is chosen yet.
