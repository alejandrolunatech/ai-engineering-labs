# Lab 05 — Learning Notes

Record evidence as you execute the lab. Do not pre-fill conclusions you have not observed.

## Status

**DESIGNED — NOT YET IMPLEMENTED OR RELEASED**

A repository design is not production evidence.

## Phase 0 — Product contract

Contract: [PRODUCT-CONTRACT.md](PRODUCT-CONTRACT.md) (v0.1, 2026-10-02). Markdown only; executable schemas deferred to Phase 1.

What did I decide?

- Primary user: an engineering manager / delivery lead who needs to understand a public PR they did not write, without reading the diff. Secondary: onboarding engineers, PMs, stakeholders.
- Input is one exact `https://github.com/<owner>/<repo>/pull/<number>` URL, public repos only. The server builds the GitHub API URLs itself.
- Every contract statement is labelled deterministic boundary / probabilistic behavior / product target / measured fact. Measured facts so far: zero.
- Output splits into model-generated fields (content is probabilistic, shape is validated) and server-generated fields (`truncated`, PR identity, model ID, versions, usage/cost) that the model is never trusted to report.
- `risk.level` means change risk (blast radius × uncertainty), not a code-quality verdict. This keeps it consistent with the "no review verdicts" non-goal.
- Initial budgets, all "calibrate in Phase 2": 2 KB request body, 50 files, 4,000 patch chars/file, 60,000 total evidence chars, 4,000 PR-body chars, 3 GitHub requests, 10 s GitHub timeout, at most 1 LLM call with no retries, 1,500 output tokens, 30 s LLM timeout.
- Over-budget evidence is truncated deterministically and reported (`truncated=true` + limitation). An over-budget request body is rejected, because truncating a URL makes no sense.
- No numeric latency, cost, availability, or rate-limit targets yet. Each one is TBD until the phase that measures it.

What did I deliberately exclude?

- Private repos and user GitHub auth; any GitHub write; code-review verdicts; whole-repo analysis, cloning, or files outside the PR; accounts, history, or stored briefs; model tool calling or agentic behavior; claims about tests passing, deployment, or business intent not present in the PR; any correctness guarantee.
- These are enforced by not building the capability, not by prompt text. The exception is non-goal 7 (no invented claims): withholding CI/deploy data is deterministic, but not inventing claims anyway is model behavior that evals must measure.

What production outcome would make this useful to a real stranger?

- Someone who did not write the PR reads the brief in under two minutes and correctly decides whether it needs their attention, what it affects, and what is still unknown.
- This is a product target, not a measurement. No method to measure it exists yet; that question is carried into Phase 4 / Phase 10.

Open tensions recorded (not resolved in Phase 0):

- THREAT-MODEL says reject beyond a hard upper bound; the contract truncates. Phase 2 decides whether extreme PRs are rejected instead.
- The 3-request GitHub budget looks like 2 needed + 1 spare. Phase 2 confirms against the real API.
- "60,000 chars ≈ 15k tokens" is a heuristic. Real counts depend on the tokenizer and content.

## Phase 1 — Deterministic application boundaries

Built: Next.js 16 app in `app/` with a URL input page, `POST /api/analyze` (validate + parse only), `GET /api/health`, zod schemas, and 109 Vitest tests. No GitHub call, no LLM call, no SDKs. Exact parser and request rules are in PRODUCT-CONTRACT.md §2a–§2b.

What is deterministic?

- The whole Phase 1 request path. Same request → same status code and body, every time. Checks run in this order: method → content type → body read with a 2,048-byte cap → JSON parse → strict `{url}` shape → URL parser.
- The URL parser matches the trimmed raw string against one anchored pattern before any normalization. I decided not to use `new URL()` for the decision: WHATWG parsing quietly rewrites `\` to `/`, resolves `..`, drops `:443`, maps full-width letters through IDNA and keeps trailing-dot hosts. Inputs that should be rejected could come out of it looking clean.
- The body cap counts streamed bytes. `Content-Length` can only reject earlier. A test sends 5,000 bytes with `Content-Length: 10` and gets 413; another streams 1 MB and checks that reading stopped after a few chunks. Checked by hand with `curl` against `next start`, including chunked transfer.
- Errors use only ARCHITECTURE.md categories with fixed messages. 400/405/415 all say `invalid_pr_url` and the HTTP status gives the exact reason (my choice, so the category set did not have to grow). A test checks that the submitted input never appears in an error body.
- Health reports only that the process is up and config parsed. It makes no external call. A 200 from it says nothing about GitHub or the model.
- The config module imports `server-only`, so a client import breaks the build. Phase 1 reads no environment variables. `.env.example` lists names for later phases, without values.

Which inputs are rejected before any external call?

- All of them. Phase 1 has no external call at all, and route tests make `fetch` throw and assert it was never called. Rejected: `http://`, `www.github.com`, any port including `:443`, credentials or any `@`, lookalike hosts (`github.com.evil.com`), trailing-dot and full-width hosts, IPs/localhost, backslashes, whitespace/control/non-ASCII characters, `/issues/`, PR `0`, leading zeros, numbers over 2,147,483,647, owners with edge hyphens or over 39 chars, repo `.`/`..`, dot-segment or other suffixes; non-POST, non-JSON content type, bodies over 2 KB, malformed JSON, invalid UTF-8, extra fields.
- Accepted and discarded: trailing slash, query, fragment, `/files`, `/commits`, `/checks`. Uppercase host is accepted and normalized; owner/repo case is kept.

Why construct the GitHub API URL instead of fetching the user's URL?

- If the server fetches what the user sends, the user picks the destination: internal addresses (`169.254.169.254`, `localhost`), lookalike domains, redirects, credentials-in-URL tricks, and inputs where my validator and the HTTP client's URL parser disagree (parser differentials). Constructing `https://api.github.com/repos/{owner}/{repo}/pulls/{number}` from three validated, `encodeURIComponent`-escaped values means the host and path shape are fixed in code. The user only picks values inside that shape.

What would still be probabilistic later?

- Everything the model writes (§3a fields). The zod `ChangeBriefSchema` (v0.1) enforces shape only: strict objects, `ai_generated: true`, `risk.level` in `low|medium|high` (provisional), no verdict field, `usage`/`estimated_cost` present but nullable (unknown is null, never zero). A valid shape still says nothing about whether the content is true. Nothing produces a ChangeBrief yet.

What this does not prove:

- Nothing about GitHub behavior, real PR sizes, budgets beyond the 2 KB body, the model, latency, cost, or production. These are local test and build results, which are not production evidence (contract §8). The static source-guard test (no `dangerouslySetInnerHTML`, no `fetch` in server code) catches regressions cheaply but is a grep, not a proof.
- Not exercised in a browser: the page was only checked with `curl` to render; the form was not clicked through.

## Phase 2 — GitHub ingestion

What real GitHub limits did I encounter?

What evidence is lost through truncation?

How did I prevent arbitrary URL fetching?

## Phase 3 — Real LLM integration

Exact model ID:

Why this model:

API used:

First real request evidence:

What surprised me about latency or response behavior?

## Phase 4 — Structured output and evals

Eval-set size:

Baseline pass rate:

Known failure modes:

Which checks are deterministic vs model-quality judgments?

## Phase 5 — Cost and latency

What does one representative request cost?

What is actually known vs estimated?

Where is latency spent?

Did token counts match my intuition?

## Phase 6 — Production abuse/security

What attacks or abuse cases did I test?

Which control actually enforces the boundary?

What remains an honest limitation?

## Phase 7 — UX and operability

How does the UI communicate uncertainty, truncation and failure?

Can I diagnose a failure without reading sensitive raw content?

## Phase 8 — CI/CD

What does CI prove?

What does a preview/production deployment prove that CI does not?

## Phase 9 — Public release

Launch date:

Live URL:

Deployment SHA:

External smoke request:

Failure path tested:

## Phase 10 — Production measurements / model experiment

Measurement window:

Request sample size:

p50 / p95 total latency:

p50 / p95 LLM latency:

Token distribution:

Estimated cost distribution:

Failure rate:

Truncation rate:

Models/configurations compared:

Decision and evidence:

## Phase 11 — Post-launch review

What would I change for meaningful scale?

What did I learn that I could not have learned from a local demo?

What is now truthful to say in an interview?

What must I still avoid claiming?
