# Lab 05 — Architecture Contract

This document defines the intended production architecture before implementation.

## Product boundary

ChangeBrief accepts a public GitHub pull-request URL and returns a structured explanatory brief. V1 is deliberately a **read-only analysis service**.

There is no model tool calling and no write path to GitHub or any other third-party system.

## Components

```text
+----------------------+
| Browser              |
| public anonymous UI  |
+----------+-----------+
           |
           | HTTPS POST /api/analyze
           v
+---------------------------------------------------+
| Next.js server boundary                          |
|                                                   |
|  1. request/body validation                       |
|  2. rate limiter                                  |
|  3. exact GitHub PR URL parser                    |
|  4. kill-switch / production config               |
+--------------------------+------------------------+
                           |
                           v
+---------------------------------------------------+
| GitHub ingestion                                  |
|                                                   |
| Construct api.github.com URLs ourselves           |
| Fetch public PR metadata + changed-file patches   |
| No arbitrary URL fetch                            |
+--------------------------+------------------------+
                           |
                           v
+---------------------------------------------------+
| Deterministic evidence builder                    |
|                                                   |
| sanitize shape                                    |
| normalize                                         |
| cap file count                                    |
| cap patch chars per file                          |
| cap total evidence                                |
| mark truncation explicitly                        |
+--------------------------+------------------------+
                           |
                           v
+---------------------------------------------------+
| LLM adapter                                       |
|                                                   |
| OpenAI Responses API                              |
| selected launch model                             |
| one bounded request                               |
| structured output contract                        |
+--------------------------+------------------------+
                           |
                           v
+---------------------------------------------------+
| Output validator                                  |
|                                                   |
| strict schema validation                          |
| reject invalid shape                              |
| no raw model text rendered as trusted structure   |
+--------------------------+------------------------+
                           |
              +------------+------------+
              |                         |
              v                         v
+--------------------------+  +----------------------------+
| Browser response         |  | Operational telemetry      |
| structured brief         |  | request outcome            |
| model/latency/cost info  |  | latency segments           |
+--------------------------+  | usage + cost estimate      |
                              | NO raw PR/prompt/output     |
                              +----------------------------+
```

## Trust boundaries

### User input

Untrusted.

Only an exact GitHub pull-request URL shape is accepted. The application extracts owner, repository and pull number, validates each component, and constructs known GitHub API endpoints itself.

### GitHub content

Untrusted.

PR titles, bodies, filenames, patches and comments/code can contain text that resembles instructions to an AI system. They are evidence to analyze, not control-plane instructions.

### Model output

Untrusted until schema validation succeeds.

A syntactically valid structured object is still not guaranteed semantically correct. Evals test declared behavioral expectations; the UI must expose uncertainty.

### Server configuration

Trusted only to the degree that deployment configuration is correctly controlled.

Secrets, model choice, price metadata, rate-limit configuration and service kill switch are server-side.

## Data minimization

V1 fetches only what is necessary to produce the brief:

- PR metadata required for context;
- changed-file metadata;
- bounded patch text where GitHub provides it.

V1 should not:

- clone repositories;
- fetch arbitrary raw files;
- process private repositories;
- persist raw source patches;
- send operational logs containing PR bodies/patches;
- expose API keys to the browser.

## Input budgeting

A large PR is both a quality problem and a denial-of-wallet vector.

The evidence builder must deterministically enforce limits such as:

```text
max files considered
max patch characters per file
max total normalized characters/tokens
max PR body length
```

Exact values are selected in Phase 2 using representative fixtures.

When evidence is truncated, the model and user-facing output receive an explicit `truncated=true` signal. Truncation must never be hidden.

## Model adapter

Application code depends on a small internal interface instead of spreading provider SDK calls through routes/components.

Conceptual shape:

```ts
interface BriefModel {
  generateBrief(input: NormalizedPullRequest): Promise<ModelResult>;
}

type ModelResult = {
  brief: ChangeBrief;
  provider: string;
  model: string;
  usage: {
    inputTokens: number | null;
    outputTokens: number | null;
    cachedInputTokens?: number | null;
  };
};
```

Provider-specific objects stop at the adapter boundary.

## Structured output contract

The model is asked for a strict object. A likely domain shape:

```text
ChangeBrief
  summary
  why_it_matters
  user_impact[]
  technical_impact[]
  risk
    level
    evidence[]
    uncertainty[]
  testing_signals[]
  rollout_considerations[]
  rollback_considerations[]
  open_questions[]
  limitations[]
```

The exact schema is created and versioned in Phase 1/4.

## Cost model

Cost is derived only when all required values are known:

```text
estimated_cost =
    input_tokens  * input_price_per_token
  + cached_tokens * cached_input_price_per_token
  + output_tokens * output_price_per_token
```

Pricing metadata must include:

- exact model ID;
- processing mode if relevant;
- pricing snapshot date;
- input rate;
- cached-input rate when relevant;
- output rate;
- currency;
- source URL.

Unknown usage or unmatched pricing means **cost unknown**, never zero.

The number shown to users is an estimate, not billing truth.

## Latency model

Measure at least:

```text
total_ms
github_ms
normalization_ms
llm_ms
validation_ms
```

The useful production question is not only "How slow is the model?" but:

> Where is the user actually waiting?

Do not derive p95 from a handful of local requests. Record distributions only after sufficient production/eval samples.

## Retries

V1 should be conservative.

- No semantic retry loop for "I dislike the answer".
- No unbounded retry for schema failure.
- Provider/network retry, if added, must be explicit, bounded, observable, and included in cost/latency evidence.
- A retry count of zero is a valid initial production decision.

Because this service has no external side effect beyond model/GitHub reads, retries do not create duplicate business writes, but they can double latency and cost.

## Rate limiting and spend controls

The public endpoint needs more than an in-memory counter because serverless instances are distributed.

Phase 6 chooses and implements a production-capable limiter. The design should support:

- per-client/IP-ish window limit;
- global emergency kill switch;
- provider/account project spending limit;
- maximum request-size budget;
- maximum one analysis in flight per browser action;
- useful 429 response without revealing internals.

Do not pretend an application-level IP limiter is perfect identity or abuse prevention.

## Cache experiment

Do not add caching before measuring the baseline.

A later optimization may cache a validated brief keyed by a deterministic identity such as:

```text
repo identity + pull number + head SHA + model ID + prompt/schema version
```

Raw patches should not be persisted merely to support cache reuse.

The experiment should measure whether caching materially improves latency/cost before making it permanent.

## Production telemetry event

A safe structured event may include:

```json
{
  "event": "analysis_completed",
  "status": "success",
  "provider": "openai",
  "model": "<exact-id>",
  "total_ms": 0,
  "github_ms": 0,
  "llm_ms": 0,
  "input_tokens": null,
  "output_tokens": null,
  "usage_status": "unknown",
  "estimated_cost": null,
  "cost_status": "unknown",
  "files_considered": 0,
  "evidence_chars": 0,
  "truncated": false,
  "schema_valid": true
}
```

Do not log:

- PR title/body;
- patch/code;
- prompt text;
- raw model output;
- API keys;
- arbitrary headers;
- full IP address;
- cookies.

## Deployment architecture

Target:

```text
GitHub main
   |
   v
CI checks
   |
   v
Vercel production deployment
   |
   v
changebrief.alejandrolunatech.com
```

CI proves the repository checks. A successful Vercel deployment plus an external smoke test proves that the production artifact actually responds.

These are different pieces of evidence.

## Failure semantics

User-facing categories should remain small and safe:

- invalid PR URL;
- public PR not found/unavailable;
- request too large;
- rate limited;
- model/provider temporarily unavailable;
- model output invalid;
- service temporarily disabled;
- internal error.

Detailed diagnostics stay server-side and must still be redacted.

## Versioning

Version independently:

- product/application release;
- output schema;
- prompt/instruction set;
- selected model/pricing snapshot;
- eval dataset.

A model change is a behavior change. Re-run evals before production promotion.

## Production gaps intentionally left for later

V1 does not need:

- login/accounts;
- payments;
- private repository access;
- GitHub write operations;
- vector database/RAG;
- autonomous tools;
- background queues unless measurements prove synchronous execution unsuitable;
- multi-region active-active architecture;
- enterprise SSO;
- complex data warehouse;
- Kubernetes.

Do not add platform complexity to make the project "look production". Add controls that production evidence actually requires.
