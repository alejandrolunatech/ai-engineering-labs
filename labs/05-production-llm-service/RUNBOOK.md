# Lab 05 — Production Runbook

This file begins as a runbook contract. Replace placeholders with the real deployed values during Phases 8–9.

## Service

- Product: ChangeBrief
- Production URL: **TBD — do not claim live before verification**
- Intended custom domain: `changebrief.alejandrolunatech.com`
- Hosting: Vercel (target)
- LLM provider: OpenAI (target)
- Exact production model: TBD in Phase 3
- Source repository: `alejandrolunatech/ai-engineering-labs`
- Lab path: `labs/05-production-llm-service`

## Health definition

Healthy means:

- homepage loads over HTTPS;
- analyze endpoint accepts a known in-bounds public PR;
- GitHub upstream succeeds;
- model call succeeds;
- structured result validates;
- telemetry event is emitted;
- no release-blocking alert/kill switch is active.

A static homepage returning 200 does not prove the LLM path is healthy.

## Configuration

Expected server-side configuration will include names like:

```text
OPENAI_API_KEY
OPENAI_MODEL
SERVICE_ENABLED
MODEL_INPUT_USD_PER_1M
MODEL_CACHED_INPUT_USD_PER_1M
MODEL_OUTPUT_USD_PER_1M
MODEL_PRICING_AS_OF
RATE_LIMIT_...
```

The final implementation decides exact names.

Never paste production secret values into this runbook.

## Fast disable / kill switch

Before launch, implement and test a server-side switch that makes analysis return a controlled `503 service temporarily disabled` without calling GitHub or OpenAI.

Target recovery procedure:

1. disable analysis;
2. confirm new requests make zero model calls;
3. investigate logs/provider status/spend;
4. deploy/configure fix;
5. run smoke test;
6. re-enable;
7. monitor.

## Common incidents

### Provider cost spike

Check:

- request rate;
- rate-limit behavior;
- input-size distribution;
- retries;
- token usage;
- model/pricing configuration;
- suspicious repeated PRs.

Immediate containment:

- enable kill switch if spend risk is active;
- lower/disable public traffic;
- verify provider account/project spending controls.

Do not "fix" a cost spike by hiding cost telemetry.

### Latency spike

Separate:

```text
GitHub latency
LLM latency
application/validation latency
total latency
```

A total-latency problem is not automatically a model problem.

### OpenAI/provider outage or throttling

Return a controlled provider-unavailable response.

Do not create an unbounded retry storm.

### GitHub upstream outage/rate exhaustion

Return an upstream-unavailable response. Do not fall back to arbitrary scraping.

### Invalid structured model output

Fail closed for the request. Capture only safe schema/error classification, not raw model output.

### Suspected secret exposure

1. disable service if necessary;
2. rotate affected credential;
3. remove exposed value from deployment/source/logs;
4. review provider usage;
5. document the event;
6. add regression coverage.

## Deployment rollback

Before launch, document the exact Vercel rollback procedure actually available to the project.

Rollback is not complete until:

- previous deployment is serving;
- smoke test passes;
- model/config compatibility is confirmed;
- incident telemetry stabilizes.

## Production smoke test

Run after every production release:

1. open production URL from a network/device outside local development;
2. submit a known small public PR;
3. verify structured brief renders;
4. verify displayed model metadata is expected;
5. inspect server telemetry for one request;
6. confirm no raw PR/prompt/model content is present;
7. record the deployment/request evidence in PRODUCTION-EVIDENCE.md when appropriate.

Do not use a giant or sensitive PR as the smoke fixture.

## Metrics to review

At minimum:

- requests;
- success/failure count;
- rate-limited count;
- total latency distribution;
- GitHub latency distribution;
- LLM latency distribution;
- input/output token distributions;
- estimated cost distribution;
- truncation rate;
- invalid-output rate.

Only report p50/p95 after there are enough samples to make those summaries meaningful; always include the sample size and time window.

## Contacts / escalation

This is initially a self-operated learning product. Record the actual owner/contact channel before public release.

There is no enterprise on-call organization behind this lab. Do not write one into existence.
