# Lab 05 — Production LLM Service: ChangeBrief

Build, release, and operate a **real public LLM-backed product**.

This lab is intentionally different from the earlier labs. It is not complete when the code works locally. It is complete only when a real user on the public internet can use the service and you have production evidence for latency, token usage, estimated model cost, failures, and operational controls.

The product is **ChangeBrief**: a small public web application that accepts the URL of a **public GitHub pull request** and returns a structured, stakeholder-friendly explanation of the change.

> **Production is an operating state, not a deployment file.**

## Evidence discipline

Until the release checklist is complete, describe this as a **production-oriented learning project**, not a production deployment.

After release, the accurate description is:

> "I designed, deployed, and operated a self-directed public LLM product."

Do not imply that it was an enterprise/client production system unless that later becomes true.

The canonical production evidence belongs in [PRODUCTION-EVIDENCE.md](PRODUCTION-EVIDENCE.md).

## Product problem

Pull requests contain useful context, but understanding them often requires reading technical descriptions, file changes, and patches. ChangeBrief turns a bounded public PR into a concise brief for engineers, engineering managers, product managers, delivery leaders, and stakeholders.

### Input

One URL matching:

```text
https://github.com/<owner>/<repo>/pull/<number>
```

V1 accepts **public GitHub pull requests only**.

The server must parse the user input and construct GitHub API requests itself. It must never fetch an arbitrary user-provided URL.

### Output

A validated structured brief with fields such as:

- what changed;
- why it may matter;
- user/business impact;
- technical impact;
- risk level with evidence and uncertainty;
- testing signals visible in the PR data;
- rollout/rollback considerations;
- open questions;
- limitations caused by missing/truncated evidence.

The UI should make uncertainty visible. The model must not invent test results, deployment status, or business intent that are absent from the supplied evidence.

## Why this lab exists

The project is designed to create credible hands-on experience with the questions production AI teams actually face:

- integrating a real LLM API;
- selecting a model based on quality, cost, and latency rather than prestige;
- handling untrusted external content;
- enforcing input/output contracts around probabilistic behavior;
- measuring provider-reported token usage;
- estimating per-request model cost;
- separating model latency from end-to-end latency;
- bounding retries and request size;
- protecting an anonymous public endpoint from denial-of-wallet abuse;
- keeping secrets server-side;
- designing privacy-safe production telemetry;
- deploying through CI/CD;
- running a public HTTPS service on a custom domain;
- collecting real production evidence after launch.

## Intended production shape

Initial target:

```text
https://changebrief.alejandrolunatech.com
```

That domain is an **intended target only** until Phase 9 proves it is live.

Technology direction:

- Next.js + TypeScript;
- server-side API route / server function;
- GitHub REST API for public PR metadata and changed-file patches;
- OpenAI Responses API behind a small adapter;
- JSON Schema / Zod-style runtime validation;
- distributed production rate limiting;
- structured JSON operational logs;
- Vercel deployment;
- GitHub Actions CI.

Do not treat those choices as authority to install every framework immediately. Each phase introduces only the infrastructure needed for its learning objective.

## Model selection

Do **not** permanently hard-code a model choice in this design document.

OpenAI model availability and pricing change over time. In Phase 3 you will:

1. check the current official OpenAI model catalog and pricing;
2. choose a cost-efficient general-purpose model suitable for this bounded summarization task;
3. record the exact model ID and pricing snapshot date;
4. configure the model through a server-side environment variable;
5. later compare it with a stronger model using the same eval set.

At design time the model catalog includes cost-sensitive Luna-class models, but the launch decision must use the official documentation available **when you execute the lab**.

## Non-negotiable production boundaries

- API keys never reach the browser.
- No private GitHub repositories in V1.
- Do not fetch arbitrary URLs.
- Do not persist raw PR bodies, patches, prompts, or model output in telemetry.
- No model tool calling in V1.
- GitHub/PR content is **untrusted data**, never instructions.
- Input size is bounded before the model call.
- Output is schema-validated before rendering.
- Model calls are bounded per user request.
- Anonymous usage is rate-limited in production.
- A provider/account spending limit and a service kill switch exist before launch.
- Unknown usage/cost is represented as unknown, never zero.
- Estimated cost is explicitly labelled as an estimate, not billing truth.
- Production logs distinguish total latency, GitHub latency, and LLM latency.
- No silent unbounded retries.
- Public launch requires CI, smoke testing, runbook, rollback path, and monitoring.

## Architecture principle

```text
USER
  |
  v
PUBLIC WEB APP
  |
  v
INPUT BOUNDARY
GitHub URL parser + request limits
  |
  v
GITHUB INGESTION
public PR metadata + bounded patches
  |
  v
NORMALIZATION / TRUNCATION
deterministic evidence envelope
  |
  v
LLM ADAPTER
OpenAI Responses API
  |
  v
STRUCTURED OUTPUT VALIDATION
  |
  +--------------------+
  |                    |
  v                    v
USER RESPONSE       OPERATIONAL EVIDENCE
                    latency / usage / cost
                    no raw source content
```

The model is not the ingestion layer, authority layer, rate limiter, schema validator, or telemetry authority.

## Initial operating targets

These are **starting product targets**, not claims or contractual SLOs. Revisit them with evidence.

- one successful LLM call per analysis request;
- hard maximum on PR files and normalized input characters/tokens;
- hard maximum output tokens;
- provider timeout;
- explicit public rate limit;
- target p95 total latency to be selected after baseline measurement;
- target maximum estimated model cost per request to be selected after the launch model/pricing decision;
- zero raw PR patch/body content in operational telemetry.

Do not invent a p95 or cost target before measuring a representative request set.

## Phases

| Phase | Focus | Evidence before moving on |
|---|---|---|
| 0 | Product contract and production definition | Scope, users, output contract, explicit non-goals and production DoD |
| 1 | Web foundation and deterministic boundaries | Local app, URL parser, contracts, no LLM yet |
| 2 | Public GitHub PR ingestion | Real public PR can be normalized within hard limits |
| 3 | Real OpenAI Responses API integration | One real server-side model call, exact model/pricing decision recorded |
| 4 | Structured output and behavioral evals | Invalid model output cannot reach UI; eval baseline recorded |
| 5 | Cost and latency observability | Real token, latency and cost-estimate evidence with redacted logs |
| 6 | Abuse, privacy and production security | Rate limiting, spend controls, prompt-injection/adversarial tests |
| 7 | Production UX and operability | Useful UI, health checks, failure states, runbook |
| 8 | CI/CD and deployment plumbing | CI green; production environment configured; preview deploy works |
| 9 | Public production release | Public HTTPS URL + custom domain + production smoke test |
| 10 | Real traffic evidence and model experiment | Production metrics + controlled model quality/cost/latency comparison |
| 11 | Post-launch review and portfolio case study | Evidence-based case study and honest interview narrative |

Work phase-by-phase. Do not ask an AI coding agent to implement the entire lab at once.

Copyable prompts live in [PROMPTS.md](PROMPTS.md).

## Production Definition of Done

Lab 05 is **not complete** until all of these are true:

- [ ] Real OpenAI API integration is deployed server-side.
- [ ] Production secret storage is configured and no secret is committed.
- [ ] Public HTTPS deployment responds from outside the developer machine.
- [ ] Custom domain is connected.
- [ ] Only public GitHub PRs are accepted.
- [ ] Arbitrary outbound URL fetching is impossible through user input.
- [ ] Input budgets/truncation are enforced.
- [ ] Structured output validation is enforced.
- [ ] Public rate limiting is active.
- [ ] Provider/account spending controls are configured.
- [ ] Service kill switch is documented and tested.
- [ ] Production telemetry records total/GitHub/LLM latency separately.
- [ ] Provider-reported token usage is captured when available.
- [ ] Estimated per-request model cost is computed from a dated pricing snapshot.
- [ ] Raw PR content, prompts and model output are absent from operational logs.
- [ ] Eval gate passes for the selected model/configuration.
- [ ] CI passes.
- [ ] Production smoke test passes.
- [ ] At least one real external non-local request succeeds.
- [ ] At least one safe failure path is exercised in production.
- [ ] Real production measurements are recorded in PRODUCTION-EVIDENCE.md.
- [ ] README contains the final live link only after it has been verified.
- [ ] RUNBOOK.md reflects the deployed system.

## What success does and does not prove

A successful Lab 05 can prove that you personally designed, deployed and operated this public service under the recorded conditions.

It does **not** prove:

- enterprise-scale traffic;
- experience operating another company's production platform;
- universal model correctness;
- security against every attack;
- that estimated cost equals the provider invoice;
- that a finite eval set represents all future PRs;
- that public GitHub content is safe or trustworthy;
- that one model is globally better than another.

## Reference documentation to re-check during execution

Because APIs, models and pricing change, verify current official documentation during the relevant phase:

- OpenAI API: https://platform.openai.com/docs
- OpenAI models: https://platform.openai.com/docs/models
- OpenAI pricing: https://platform.openai.com/pricing
- GitHub REST pull requests: https://docs.github.com/en/rest/pulls/pulls
- Vercel docs: https://vercel.com/docs

The docs are inputs to the implementation decision; this README is not a permanently current pricing catalog.
