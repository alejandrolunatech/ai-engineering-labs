# ChangeBrief app (Lab 05)

Development build, not a production service. See the lab README for status.

## Run locally (Phase 3)

`.env.local` (git-ignored) holds 1Password references, never real values:

```bash
OPENAI_API_KEY=op://Dev/changebrief-g0/credential
OPENAI_MODEL=<model id>            # e.g. gpt-6-luna once it is on the project allow-list
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
