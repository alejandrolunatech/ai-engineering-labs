// Manual exercise for Phase 3 (PAID): one real model call per model.
//
//   op run --env-file=.env.local -- npm run brief-pr -- <PR URL> [--model ID]... [--effort none|low|medium|high] [--show-brief] [--save]
//
// Runs the SAME parser, GitHub adapter, normalizer, prompt and OpenAI adapter
// as POST /api/analyze. GitHub is fetched once; then each --model gets exactly
// one call, one after another (default: OPENAI_MODEL). Use several --model
// flags to compare models on identical evidence.
//
// Prints status, latency, provider-reported tokens and an ESTIMATED cost from
// scripts/pricing-snapshot.json. --show-brief prints the brief text; --save
// writes each result to .briefs/ (git-ignored) for side-by-side reading.
// Never prints the API key.

import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { getConfig, REASONING_EFFORTS } from "@/lib/config";
import { ingestPullRequest } from "@/lib/github/ingest";
import { briefModelFor } from "@/lib/llm";
import { MAX_OUTPUT_TOKENS } from "@/lib/llm/openai";
import { PROMPT_VERSION } from "@/lib/llm/prompt";
import type { ModelResult, ModelUsage } from "@/lib/llm/types";
import { parsePrUrl } from "@/lib/pr-url";

type Effort = (typeof REASONING_EFFORTS)[number];
type Price = { input: number; cached_input: number; output: number };
type Snapshot = { as_of: string; models: Record<string, Price> };

// Model output can echo PR text: escape control characters before printing.
function safe(text: string): string {
  return text.replace(/[\u0000-\u001f\u007f-\u009f]/g, (c) => `\\u${c.charCodeAt(0).toString(16).padStart(4, "0")}`);
}

function priceFor(snapshot: Snapshot, model: string): Price | null {
  // Served IDs can be dated snapshots ("gpt-5.4-mini-2026-03-17"): match the
  // longest alias that prefixes it.
  const alias = Object.keys(snapshot.models)
    .filter((a) => model === a || model.startsWith(`${a}-`))
    .sort((a, b) => b.length - a.length)[0];
  return alias === undefined ? null : snapshot.models[alias];
}

// Unknown usage or price -> unknown cost, never zero.
function estimate(usage: ModelUsage | null, price: Price | null): number | null {
  if (usage === null || price === null) return null;
  const { input_tokens: input, output_tokens: output } = usage;
  if (input === null || output === null) return null;
  const cached = usage.cached_input_tokens ?? 0;
  return ((input - cached) * price.input + cached * price.cached_input + output * price.output) / 1_000_000;
}

function parseArgs(argv: string[]) {
  const models: string[] = [];
  let effort: string | null = null;
  let showBrief = false;
  let save = false;
  const rest: string[] = [];
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === "--model") models.push(argv[++i] ?? "");
    else if (a === "--effort") effort = argv[++i] ?? "";
    else if (a === "--show-brief") showBrief = true;
    else if (a === "--save") save = true;
    else rest.push(a);
  }
  return { models, effort, showBrief, save, rest };
}

async function main(): Promise<number> {
  const args = parseArgs(process.argv.slice(2));
  if (args.rest.length !== 1) {
    console.error(
      "usage: npm run brief-pr -- <https://github.com/owner/repo/pull/N> [--model ID]... [--effort none|low|medium|high] [--show-brief] [--save]",
    );
    return 2;
  }
  const parsed = parsePrUrl(args.rest[0]);
  if (!parsed.ok) {
    console.error(`rejected before any request: ${parsed.reason}`);
    return 2;
  }
  const config = getConfig();
  if (!config.ok) {
    console.error("config invalid: check OPENAI_MODEL and OPENAI_REASONING_EFFORT");
    return 2;
  }
  const llm = config.config.llm;
  const models = args.models.length > 0 ? args.models : llm.status === "configured" ? [llm.model] : [];
  if (models.length === 0 || models.some((m) => !/^[a-z0-9][a-z0-9.\-]{0,99}$/.test(m))) {
    console.error("give --model <id> (lower-case model ID) or set OPENAI_MODEL");
    return 2;
  }
  const effortRaw = args.effort ?? (llm.status === "configured" ? llm.reasoningEffort : "none");
  if (!(REASONING_EFFORTS as readonly string[]).includes(effortRaw)) {
    console.error(`--effort must be one of: ${REASONING_EFFORTS.join(", ")}`);
    return 2;
  }
  const effort = effortRaw as Effort;
  if (briefModelFor(models[0], effort) === null) {
    console.error("No API key in the environment. Run through: op run --env-file=.env.local -- npm run brief-pr -- ...");
    return 2;
  }
  const snapshot = JSON.parse(readFileSync(new URL("./pricing-snapshot.json", import.meta.url), "utf8")) as Snapshot;

  const { owner, repo, number } = parsed.pr;
  console.log(`PR: ${owner}/${repo}#${number}   prompt ${PROMPT_VERSION}   effort ${effort}   max output ${MAX_OUTPUT_TOKENS} tokens`);
  console.log(`paid calls this run: ${models.length} (one per model, no retries)`);

  const ghStart = performance.now();
  const ingest = await ingestPullRequest(parsed.pr);
  const githubMs = Math.round(performance.now() - ghStart);
  if (!ingest.ok) {
    console.log(`GitHub FAILED: kind=${ingest.kind} reason=${ingest.reason} (no model call made)`);
    return 1;
  }
  const e = ingest.evidence;
  console.log(
    `GitHub: ${ingest.stats.requests} requests, ${githubMs} ms   files ${e.coverage.files_considered}/${e.coverage.files_total}   ` +
      `evidence chars ${e.coverage.chars_included}/${e.coverage.chars_available}   truncated ${e.truncated}`,
  );

  const rows: { model: string; result: ModelResult; cost: number | null }[] = [];
  for (const id of models) {
    const result = await briefModelFor(id, effort)!.generateBrief(e);
    const served = result.ok ? result.model : (result.model ?? id);
    const cost = estimate(result.usage, priceFor(snapshot, served));
    rows.push({ model: id, result, cost });

    const u = result.usage;
    const n = (v: number | null | undefined) => (v === null || v === undefined ? "unknown" : String(v));
    console.log(`\n=== ${id} ===`);
    console.log(`status: ${result.ok ? "ok" : `FAILED ${result.kind} (${result.reason})`}   served model: ${served}   llm_ms: ${result.llmMs}`);
    console.log(
      `tokens: input ${n(u?.input_tokens)} (cached ${n(u?.cached_input_tokens)})   output ${n(u?.output_tokens)} (reasoning ${n(u?.reasoning_tokens)})`,
    );
    console.log(`estimated cost: ${cost === null ? "unknown" : `$${cost.toFixed(6)}`} (estimate, pricing as of ${snapshot.as_of})`);
    if (result.ok) {
      console.log(`risk: ${result.brief.risk.level}   summary: ${safe(result.brief.summary)}`);
      if (args.showBrief) console.log(JSON.stringify(result.brief, null, 2).split("\n").map(safe).join("\n"));
    }
    if (args.save) {
      mkdirSync(".briefs", { recursive: true });
      const stamp = new Date().toISOString().replace(/[:.]/g, "-");
      const file = `.briefs/${stamp}-${owner}-${repo}-${number}-${id}-${effort}.json`;
      writeFileSync(
        file,
        JSON.stringify(
          { pr: parsed.pr, prompt_version: PROMPT_VERSION, effort, github_ms: githubMs, coverage: e.coverage, truncated: e.truncated, model: id, cost_estimate_usd: cost, pricing_as_of: snapshot.as_of, result },
          null,
          2,
        ),
      );
      console.log(`saved: ${file}`);
    }
  }

  if (rows.length > 1) {
    console.log("\nmodel | status | llm_ms | in | out | est. USD");
    for (const { model, result, cost } of rows) {
      console.log(
        `${model} | ${result.ok ? "ok" : result.reason} | ${result.llmMs} | ${result.usage?.input_tokens ?? "?"} | ${result.usage?.output_tokens ?? "?"} | ${cost === null ? "unknown" : cost.toFixed(6)}`,
      );
    }
  }
  return rows.every((r) => r.result.ok) ? 0 : 1;
}

main().then(
  (code) => process.exit(code),
  () => {
    console.error("brief-pr failed with an unexpected error");
    process.exit(1);
  },
);
