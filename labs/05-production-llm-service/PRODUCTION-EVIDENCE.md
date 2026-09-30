# ChangeBrief — Production Evidence

## Current status

**NOT RELEASED**

Do not replace this status until Phase 9 proves the public deployment.

## Identity

- Product: ChangeBrief
- Live URL: TBD
- Launch date: TBD
- Deployment commit SHA: TBD
- Hosting: TBD
- LLM provider: TBD
- Exact model ID: TBD
- Output schema version: TBD
- Prompt/instruction version: TBD
- Pricing snapshot date/source: TBD

## Production architecture evidence

Record links or descriptions for:

- production deployment;
- custom domain;
- CI run;
- rate-limit configuration;
- secret configuration (names/config only — never values);
- provider spend controls;
- kill switch;
- observability/log destination;
- rollback mechanism.

## First successful external request

- Date/time window:
- Client was outside local development:
- Public PR fixture/reference:
- Result: success/failure
- Total latency:
- GitHub latency:
- LLM latency:
- Input tokens:
- Output tokens:
- Usage status:
- Estimated model cost:
- Cost-estimate pricing snapshot:
- Truncated:
- Notes:

Never paste raw source patches, prompts, model outputs or secrets here.

## Production measurement window

Only populate percentiles after a meaningful sample exists.

- Window:
- Requests:
- Successful:
- Failed:
- Rate limited:
- Truncated:
- p50 total latency:
- p95 total latency:
- p50 LLM latency:
- p95 LLM latency:
- median input tokens:
- median output tokens:
- median estimated cost:
- total estimated model cost:
- notes/limitations:

## Model experiment

Compare models/configurations against the same eval set and representative request corpus.

| Candidate | Eval result | Median LLM latency | Estimated cost/request | Notes |
|---|---:|---:|---:|---|
| TBD | TBD | TBD | TBD | |

Selection decision:

Evidence:

## Incidents / operational learning

Record real incidents or controlled production failure exercises without sensitive payloads.

## Interview-safe narrative

Do not finalize this paragraph until the evidence above exists.

A future accurate structure is:

> I built and operated ChangeBrief, a self-directed public LLM service that converts public GitHub pull requests into structured stakeholder briefs. The backend integrates the OpenAI Responses API using [MODEL]. I selected that model after comparing quality, latency and cost on a fixed eval set. In production I measured [N] requests over [WINDOW], with [LATENCY] and an estimated model cost of [COST]. The main engineering challenges were bounding public input/cost, separating end-to-end latency from model latency, validating structured outputs, handling prompt-injection-like repository content as untrusted data, and keeping source content out of operational telemetry.

Keep these qualifiers:

- self-directed public product;
- not an enterprise/client deployment unless independently true;
- estimated cost is not provider billing;
- finite production/eval samples do not prove universal model quality.
