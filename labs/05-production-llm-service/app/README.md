# ChangeBrief app (Lab 05)

Development build, not a production service. See the lab README for status.

## Run locally (Phase 3+)

`.env.local` (git-ignored) holds 1Password references, never real values:

```bash
OPENAI_API_KEY=op://Dev/changebrief-g0/credential
OPENAI_MODEL=gpt-6-luna            # Phase 4 eval pick; must be on the project allow-list
# OPENAI_REASONING_EFFORT=none     # optional: none | low | medium | high
```

```bash
npm ci
npm test                                   # mocked, no API key, no cost
op run --env-file=.env.local -- npm run dev
# http://localhost:3000 ; GET /api/health shows llm.status and the model ID

# One paid call per --model on the same PR evidence (estimated cost printed):
op run --env-file=.env.local -- npm run brief-pr -- https://github.com/nodejs/node/pull/66442 --model gpt-6-luna --model gpt-5.4-mini --save
```

`npm run inspect-pr -- <PR URL>` still shows the GitHub evidence with no model call.

## Behavioral evals (Phase 4)

```bash
npm run evals -- --dry-run                          # plan only: no calls, no key, no cost
op run --env-file=.env.local -- npm run evals       # PAID: 8 cases x 3 configs x 3 repeats = 72 calls
op run --env-file=.env.local -- npm run evals -- --config gpt-6-luna:none --repeat 1 --case security-auth
```

Cases and checks live in `evals/`; reports go to `evals/reports/` (git-ignored). `npm test` checks the eval harness itself and never calls a model.

## CI eval gate and telemetry (Phase 5)

```bash
npm run eval-gate      # no model calls: prompt, schema and eval set must match evals/baseline.json
```

If you change the prompt, the output schema or the eval set, the gate fails. Run the paid evals, read the report, then copy the `evals/reports/<stamp>.baseline.json` it wrote to `evals/baseline.json` and commit it with the report. Never edit the fingerprints by hand.

Every analysis writes one `"event":"analysis"` JSON line to stdout (see `lib/telemetry.ts` and RUNBOOK.md). Prices for the estimated cost are in `lib/pricing.ts`.

## Kill switch and rate limits (Phase 6)

- `SERVICE_ENABLED=false` refuses every analysis with 503 before any GitHub or model call. Unset means enabled locally and **disabled on Vercel**, so a new deployment spends nothing until you set it to `true`.
- Rate limits run before any paid work: per client 10/hour and 30/day, and 200 analyses/day for the whole service (`RATE_LIMIT_PER_IP_PER_HOUR`, `RATE_LIMIT_PER_IP_PER_DAY`, `ANALYSIS_DAILY_CAP`). Locally they count in memory; on Vercel they need Upstash Redis (`KV_REST_API_URL`/`KV_REST_API_TOKEN` or the `UPSTASH_REDIS_REST_` pair) and fail closed without it.
- `GET /api/health` shows `service` and `rateLimit`. Security headers (CSP and friends) are in `next.config.ts`.

---

This is a [Next.js](https://nextjs.org) project bootstrapped with [`create-next-app`](https://nextjs.org/docs/app/api-reference/cli/create-next-app).

## Getting Started

First, run the development server:

```bash
npm run dev
# or
yarn dev
# or
pnpm dev
# or
bun dev
```

Open [http://localhost:3000](http://localhost:3000) with your browser to see the result.

You can start editing the page by modifying `app/page.tsx`. The page auto-updates as you edit the file.

This project uses [`next/font`](https://nextjs.org/docs/app/building-your-application/optimizing/fonts) to automatically optimize and load [Geist](https://vercel.com/font), a new font family for Vercel.

## Learn More

To learn more about Next.js, take a look at the following resources:

- [Next.js Documentation](https://nextjs.org/docs) - learn about Next.js features and API.
- [Learn Next.js](https://nextjs.org/learn) - an interactive Next.js tutorial.

You can check out [the Next.js GitHub repository](https://github.com/vercel/next.js) - your feedback and contributions are welcome!

## Deploy on Vercel

The easiest way to deploy your Next.js app is to use the [Vercel Platform](https://vercel.com/new?utm_medium=default-template&filter=next.js&utm_source=create-next-app&utm_campaign=create-next-app-readme) from the creators of Next.js.

Check out our [Next.js deployment documentation](https://nextjs.org/docs/app/building-your-application/deploying) for more details.
