# Lab 05 — Production Runbook

This file begins as a runbook contract. Replace placeholders with the real deployed values during Phases 8–9.

## Service

- Product: ChangeBrief
- Production URL: **TBD — do not claim live before verification**
- Intended custom domain: `changebrief.alejandrolunatech.com`
- Hosting: Vercel (target)
- LLM provider: OpenAI (target)
- Exact production model: `gpt-6-luna` with `OPENAI_REASONING_EFFORT=none`, picked by the Phase 4 eval rule on 2026-10-12 (LEARNING-NOTES.md Phase 4, `app/evals/BASELINE-e3.md`). A model change is a behavior change: re-run `npm run evals` before promoting one.
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

Server-side only (never `NEXT_PUBLIC_`). Full notes in `app/.env.example`.

```text
OPENAI_API_KEY               secret, required for analysis
OPENAI_MODEL                 gpt-6-luna
OPENAI_REASONING_EFFORT      none (default)
GITHUB_TOKEN                 optional, public-repo read-only
SERVICE_ENABLED              true | false; unset = disabled on Vercel
KV_REST_API_URL              Upstash Redis REST URL (or UPSTASH_REDIS_REST_URL)
KV_REST_API_TOKEN            secret (or UPSTASH_REDIS_REST_TOKEN)
RATE_LIMIT_PER_IP_PER_HOUR   default 10
RATE_LIMIT_PER_IP_PER_DAY    default 30
ANALYSIS_DAILY_CAP           default 200, whole service
```

Prices for the estimated cost are code (`app/lib/pricing.ts`), not configuration.

`GET /api/health` reports `service` (kill switch), `rateLimit.backend` (`upstash`, `memory` or `not_configured`) and the limits. On Vercel, `not_configured` means every analysis is refused.

Never paste production secret values into this runbook.

## Fast disable / kill switch

Implemented in Phase 6. `SERVICE_ENABLED=false` makes `POST /api/analyze` return `503 service_disabled` (with `Retry-After: 300`) before it reads the body, so it makes zero GitHub and zero model calls (`app/tests/abuse-controls.test.ts`). Telemetry records `reason: "service_disabled"`.

On Vercel an environment variable change applies only to a new deployment. Three levels, fastest last:

1. **Kill switch (normal):** Vercel, project, Settings, Environment Variables: set `SERVICE_ENABLED` to `false` for Production. Then Deployments, the current production deployment, `...`, Redeploy. Takes about a minute. The site stays up; analysis is refused.
2. **Pause production:** in a terminal, anywhere: `vercel project pause <project-name>` (it asks you to type the name to confirm). The production deployment stops serving at once (visitors get a Vercel 503 page). Undo with `vercel project unpause <project-name>`.
3. **Cut the money:** OpenAI platform, the production project, API keys: revoke the key. Model calls fail at once (`provider_unavailable`). Make a new key in 1Password afterwards.

Recovery:

1. disable analysis (level 1, or 2/3 if spend is running);
2. check `/api/health` shows `"service":"disabled"` and new `"event":"analysis"` lines show `reason: "service_disabled"` with `github_ms: null`;
3. investigate logs, provider status and spend;
4. deploy/configure the fix;
5. set `SERVICE_ENABLED=true`, redeploy;
6. run the smoke test;
7. monitor.

## Rate limits

Implemented in Phase 6 (`app/lib/rate-limit.ts`), checked after the request is validated and before any GitHub or model call:

- per client: `RATE_LIMIT_PER_IP_PER_HOUR` and `RATE_LIMIT_PER_IP_PER_DAY` (fixed windows, UTC hours and days);
- whole service: `ANALYSIS_DAILY_CAP` per UTC day. It only counts requests the client limit allowed.

Refused requests get `429 rate_limited` with `Retry-After` and telemetry `reason` `rate_limited_ip` or `rate_limited_global`. If the store is down or slow (1 s timeout), analysis is refused with `503` and `reason: "rate_limiter_unavailable"`: it fails closed, never open.

The client is the IP Vercel writes into `x-real-ip`, IPv6 per /64, stored only as a SHA-256 digest that expires within a day. An IP is not an identity. The daily cap and the OpenAI prepaid credit are the real money limits.

To change a limit: set the variable in Vercel and redeploy. To let one person through after a false positive, wait for the window or delete their key in the Upstash console (keys start with `changebrief:rl:v1:`).

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

- enable kill switch if spend risk is active (see "Fast disable");
- lower `ANALYSIS_DAILY_CAP` or the per-client limits and redeploy;
- look for `reason: "rate_limited_global"` events: the daily cap is being hit;
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

## Telemetry events (Phase 5)

Every `POST /api/analyze` writes exactly one JSON line to stdout with `"event":"analysis"` (Vercel: project, Logs, search `"event":"analysis"`; locally: the `npm run dev` terminal). The allowlist is `app/lib/telemetry.ts`; an event that does not fit it is replaced by `{"event":"telemetry_dropped"}`, which is itself worth investigating.

Read an event like this:

- `outcome` and `http_status`: what the user got. `failure_stage` (`request`, `github`, `model`) and `reason`: where and why it failed, as a fixed code.
- `total_ms` = roughly `github_ms` + `normalization_ms` + `llm_ms` + `validation_ms` + request handling.
- `input_tokens`, `cached_input_tokens`, `output_tokens`, `reasoning_tokens`: provider-reported; `null` means not reported (`usage_status`).
- `estimated_cost_usd` with `pricing_as_of`: an estimate from `app/lib/pricing.ts`, never billing truth. `null` with `cost_status: "unknown"` means it could not be estimated, not that it was free.
- `rate_limited` from the model with `reason: "rate_limited"` can also mean the prepaid credit is used up. Check the OpenAI billing page before assuming load.

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
