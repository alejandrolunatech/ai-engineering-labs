# Lab 05 — Copyable Phase Prompts

Use these prompts with Claude Code (or another coding agent) **one phase at a time**.

Before each phase:

1. read README.md and ARCHITECTURE.md;
2. read THREAT-MODEL.md for security-sensitive work;
3. inspect the current implementation;
4. state the plan before editing;
5. implement only the requested phase;
6. run the relevant tests;
7. explain what the evidence proves and does not prove;
8. do not commit until the human reviews the result.

---

## Phase 0 — Product contract and production definition

```text
Implement Phase 0 only for Lab 05.

Read README.md, ARCHITECTURE.md, THREAT-MODEL.md,
RELEASE-CHECKLIST.md and PRODUCTION-EVIDENCE.md first.

Do not build the application yet.

Create an inspectable product contract that defines:

- target user;
- supported input: public GitHub PR URL only;
- structured output fields;
- explicit non-goals;
- initial input/request budgets;
- initial operational targets;
- production Definition of Done;
- what counts as production evidence;
- what must remain unknown until measured.

Make the contract distinguish:
- deterministic engineering boundaries;
- probabilistic model behavior;
- product targets;
- measured production facts.

Do not invent latency, cost, availability or model-quality numbers.

Add tests only if you introduce executable schemas/contracts.
Update only the Phase 0 section of LEARNING-NOTES.md with decisions actually made.

Show me the result and wait.
Do not start Phase 1.
Do not commit.
```

---

## Phase 1 — Web foundation and deterministic boundaries

```text
Implement Phase 1 only for Lab 05.

Build the smallest inspectable Next.js + TypeScript foundation for ChangeBrief.

Requirements:
- a simple page with a GitHub PR URL input;
- POST analysis API boundary, but NO GitHub network call and NO LLM call yet;
- exact parser for https://github.com/<owner>/<repo>/pull/<number>;
- reject lookalike hosts, ports, credentials, malformed paths and non-HTTPS inputs;
- request body size/shape validation;
- output/domain schemas for ChangeBrief;
- safe rendering: no raw HTML injection;
- server-only configuration module;
- health endpoint that proves app process/config health only, not LLM health;
- deterministic tests.

Do not add authentication, database, LLM SDK, GitHub SDK, rate-limit provider,
analytics framework or deployment yet.

Explain why parsing and constructing the GitHub API URL is safer than fetching
the user-provided URL.

Update LEARNING-NOTES Phase 1.
Do not start Phase 2.
Do not commit.
```

---

## Phase 2 — Public GitHub PR ingestion

```text
Implement Phase 2 only for Lab 05.

Add a small GitHub ingestion adapter using the public GitHub REST API.

Requirements:
- public repositories only;
- construct api.github.com endpoints from validated owner/repo/pull_number;
- do not fetch arbitrary URLs;
- fetch only PR metadata and changed-file metadata/patches needed by ChangeBrief;
- no repository clone;
- no arbitrary raw-file fetch;
- no private-repository credentials in V1;
- explicit GitHub request count/page/file ceilings;
- deterministic normalization into a provider-neutral NormalizedPullRequest;
- deterministic limits for PR body, file count, patch chars per file, total evidence;
- explicit truncated/limitations metadata;
- timeouts and constrained upstream errors;
- no LLM call yet.

Use mocked GitHub responses for automated tests.
Also give me ONE small manual exercise against a real public PR so I can see the
normalized evidence and truncation behavior myself.

Add adversarial URL/oversized-PR tests from THREAT-MODEL.md.

Update LEARNING-NOTES Phase 2 with actual observed GitHub behavior.
Do not start Phase 3.
Do not commit.
```

---

## Phase 3 — Real OpenAI Responses API integration

```text
Implement Phase 3 only for Lab 05.

This is the first real LLM API integration.

Before coding, use current official OpenAI documentation to verify:
- available models appropriate for this workload;
- Responses API usage;
- structured-output support;
- current pricing.

Propose the launch candidate model BEFORE changing code.
Prefer a cost-efficient model if it satisfies the product/eval needs.
Do not choose a model only because it is the largest.

After I approve the model choice:

- add the official OpenAI SDK;
- keep OPENAI_API_KEY server-side only;
- configure exact model ID with OPENAI_MODEL;
- implement a small provider adapter;
- send only the normalized bounded evidence from Phase 2;
- treat PR content as untrusted data, not instructions;
- no model tools;
- one bounded model request per normal analysis;
- explicit output-token limit;
- explicit provider timeout;
- no automatic semantic retry;
- capture provider-reported usage when available;
- keep provider SDK objects behind the adapter boundary;
- mocked tests must not spend API money.

Then guide me through:
1. creating/configuring an OpenAI API project/key;
2. setting the key locally without committing it;
3. setting a low provider spending/budget control;
4. making ONE deliberate paid local request;
5. inspecting the exact model, response shape, token usage and latency.

Record the exact model ID and pricing snapshot date/source in project configuration/docs,
but do not hard-code stale prices into explanatory prose.

Update LEARNING-NOTES Phase 3 with the real request evidence.
Do not start Phase 4.
Do not commit.
```

---

## Phase 4 — Structured output and behavioral evals

```text
Implement Phase 4 only for Lab 05.

Turn the ChangeBrief output into an enforced behavioral contract.

Requirements:
- provider structured-output facility where supported;
- independent runtime validation after the provider returns;
- invalid output never reaches the normal UI;
- version the output schema;
- create a deterministic eval runner;
- eval fixtures must be synthetic or safely licensed/created for this repository;
- include:
  * clear low-risk change;
  * risky/security-sensitive change;
  * missing context;
  * no patch available;
  * large/truncated PR;
  * misleading PR title;
  * prompt-injection-like text in a patch;
  * script/HTML-like content;
- named expectations that do not overfit exact prose;
- report pass/fail and the exact model/config used.

Keep engineering tests separate from model-quality evals.

Run the eval suite first with the selected model and preserve the honest baseline.
Do not rewrite expectations merely to manufacture 100%.

Update LEARNING-NOTES Phase 4.
Do not start Phase 5.
Do not commit.
```

---

## Phase 5 — Production cost and latency observability

```text
Implement Phase 5 only for Lab 05.

Add privacy-safe structured operational telemetry.

Measure separately:
- total_ms;
- github_ms;
- normalization_ms;
- llm_ms;
- validation_ms;
- number of GitHub requests;
- files considered;
- normalized evidence size;
- truncated;
- provider/model;
- provider-reported input/output/cached tokens when known;
- estimated cost only when an exact dated price exists for the exact model/config.

Rules:
- unknown != zero;
- estimated cost != billing truth;
- do not estimate from partial usage unless the formula explicitly supports it;
- no raw PR title/body/patch/code;
- no prompt;
- no raw model output;
- no API key;
- no full IP/cookies/arbitrary headers;
- constrained error categories only.

Add redaction/leakage tests using unmistakable fixture secret/source strings.

Expose a small user-facing engineering-transparency section after a successful
analysis:
- model;
- model latency;
- total latency;
- tokens when known;
- estimated model cost when known;
- truncation/limitations.

Label cost as an estimate.

Guide me through one real request and make me calculate/verify its estimated
cost manually from the recorded usage and dated pricing metadata.

Update LEARNING-NOTES Phase 5.
Do not start Phase 6.
Do not commit.
```

---

## Phase 6 — Abuse controls, privacy and production security

```text
Implement Phase 6 only for Lab 05.

Read THREAT-MODEL.md first.

Add the controls required for an anonymous paid production endpoint.

Requirements:
- choose a production-capable distributed rate-limit mechanism;
- explain the provider/design and its trust limitations before implementation;
- local development may use a deterministic fake/in-memory limiter, but production must not;
- configurable public rate limit;
- rate-limit decision happens before GitHub/OpenAI paid work;
- service kill switch that causes zero GitHub/model calls;
- maximum request/evidence/output budgets enforced;
- bounded provider/network retry policy if any;
- add CSP/security headers where appropriate;
- production errors remain redacted;
- no private GitHub support;
- no arbitrary URL fetch;
- no model tools.

Add adversarial tests for:
- prompt injection in PR content;
- lookalike/SSRF URLs;
- oversized PR;
- rate-limit exhaustion;
- kill switch;
- provider timeout/429/5xx;
- telemetry leakage;
- script-like content.

For every denied request, prove downstream paid calls did not occur.

Update THREAT-MODEL.md only when implementation evidence changes the model.
Update LEARNING-NOTES Phase 6.
Do not start Phase 7.
Do not commit.
```

---

## Phase 7 — Production UX and operability

```text
Implement Phase 7 only for Lab 05.

Make the product useful and operable without expanding product scope.

UX:
- clean public landing page;
- example URL format;
- loading state;
- structured brief;
- clear uncertainty/limitations;
- clear truncation indication;
- engineering transparency block;
- safe, actionable failure states;
- accessibility basics;
- no fake testimonials/usage numbers.

Operability:
- health/readiness behavior;
- consistent request correlation identifier safe for logs;
- constrained error taxonomy;
- RUNBOOK.md updated to match real implementation;
- kill-switch procedure verified locally;
- production smoke-test script/command that does not expose secrets;
- no deployment yet.

Do not add accounts, payments, private repos, autonomous agents or a database
unless the existing architecture demonstrably requires one.

Update LEARNING-NOTES Phase 7.
Do not start Phase 8.
Do not commit.
```

---

## Phase 8 — CI/CD and deployment plumbing

```text
Implement Phase 8 only for Lab 05.

Prepare the real production delivery path.

CI requirements:
- install from lockfile;
- lint/typecheck;
- deterministic unit/integration tests;
- eval gate strategy appropriate for paid model calls:
  * normal PR CI must not unexpectedly spend money;
  * deterministic/mock checks always run;
  * define when the real-provider eval gate runs before production promotion;
- build;
- no secret echo.

Vercel:
- production/preview configuration documented;
- server-side environment variables documented;
- no secret values committed;
- preview deployment works;
- production domain is NOT claimed live yet.

Deployment should come from repository state, not manual copying of build files.

Update RELEASE-CHECKLIST.md and RUNBOOK.md with actual commands/configuration.
Guide me through connecting GitHub/Vercel and configuring environment variables,
explaining every setting.

Do not perform the final public production release until I explicitly approve Phase 9.

Update LEARNING-NOTES Phase 8.
Do not start Phase 9.
Do not commit.
```

---

## Phase 9 — Public production release

```text
Implement/execute Phase 9 only for Lab 05.

Goal: the service becomes genuinely public.

Before release:
- walk through RELEASE-CHECKLIST.md;
- zero release blockers;
- exact model/pricing metadata current;
- rate limit active;
- provider spending controls active;
- kill switch tested;
- CI green;
- eval release gate satisfied;
- runbook current.

Then guide me through the real production deployment.

Target custom domain:
    changebrief.alejandrolunatech.com

Do not write "live" into README or PRODUCTION-EVIDENCE.md until an external
HTTPS request proves it.

After deployment:
- run external smoke test;
- run one known public PR analysis;
- inspect privacy-safe telemetry;
- verify model/tokens/latency/cost estimate;
- exercise one SAFE failure path (for example kill switch or rate limiting)
  without creating an outage for others;
- verify rollback procedure exists.

Update PRODUCTION-EVIDENCE.md with facts only.
Update LEARNING-NOTES Phase 9.

At the end, explicitly state what has now become truthful to call "production"
and what still must not be claimed.

Do not start Phase 10.
Do not commit until I review the evidence.
```

---

## Phase 10 — Real production measurements and model experiment

```text
Implement/execute Phase 10 only for Lab 05.

Do not manufacture traffic or metrics.

First review the real production sample available so far.

If sample size is too small for meaningful percentiles:
- say so;
- record raw/aggregate counts that are defensible;
- do not publish misleading p95 values.

Design a controlled comparison between:
- the current production model/config;
- one stronger or alternative current model.

Use:
- the same eval dataset;
- the same representative bounded request corpus;
- the same output contract.

Compare:
- behavioral eval result;
- token usage;
- LLM latency;
- estimated cost;
- failure/invalid-output rate.

Do not declare a universal winner.
Make an explicit product decision based on this workload and evidence.

Consider a cache experiment only after the uncached baseline exists. If tested,
key it on immutable PR/model/prompt/schema identity and do not persist raw patch
content merely for caching.

Update PRODUCTION-EVIDENCE.md and LEARNING-NOTES Phase 10.
Do not start Phase 11.
Do not commit until reviewed.
```

---

## Phase 11 — Post-launch review and portfolio case study

```text
Implement Phase 11 only for Lab 05.

Review the full repository and PRODUCTION-EVIDENCE.md.

Produce an evidence-based post-launch case study covering:

- product problem;
- architecture;
- exact production model/API;
- model-selection rationale;
- structured-output/eval approach;
- security and abuse controls;
- latency architecture;
- real measured latency with sample/window;
- token/cost evidence;
- operational incidents/failure exercises;
- model comparison;
- what changed after production evidence;
- current limitations;
- what would need to change for meaningful scale.

Update README with:
- verified live URL;
- concise architecture;
- evidence summary;
- link to detailed production evidence.

Draft:
1. a 60-second interview answer to:
   "Describe a production project where you integrated an LLM API — which model
   and what challenges did you face around cost or latency?"
2. a longer STAR-style interview narrative;
3. a LinkedIn/portfolio case-study paragraph.

Every claim must be directly supported by production evidence.

Use the wording:
    self-directed public production product

unless there is independent evidence of enterprise/client production.

Do not inflate traffic, scale, availability, savings or quality.
Do not start another lab.
Do not commit until I review.
```
