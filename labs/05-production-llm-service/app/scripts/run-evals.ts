// Behavioral evals for ChangeBrief (Phase 4). PAID: one real model call per
// case, config and repeat.
//
//   op run --env-file=.env.local -- npm run evals
//   op run --env-file=.env.local -- npm run evals -- --config gpt-6-luna:none --repeat 1 --case security-auth
//   npm run evals -- --dry-run      (prints the plan, makes no calls, needs no key)
//
// Defaults: configs gpt-6-luna:none, gpt-6-luna:low, gpt-5.4-mini:none (in
// preference order), 3 repeats, all cases, 3 calls at a time. At most
// MAX_EVAL_CALLS calls per run; SDK retries stay off.
//
// Uses the same prompt, schema and OpenAI adapter as POST /api/analyze; the
// evidence comes from the synthetic cases in evals/cases.ts (no GitHub calls).
// Writes evals/reports/<stamp>.md (summary) and .json (every brief), both
// git-ignored. Never prints the API key.

import { mkdirSync, writeFileSync } from "node:fs";
import { EVAL_CASES, EVAL_SET_VERSION } from "@/evals/cases";
import {
  configLabel,
  decide,
  MAX_CONCURRENCY,
  MAX_EVAL_CALLS,
  parseConfig,
  plannedCalls,
  runEvals,
  summarize,
  toMarkdown,
  type EvalConfig,
} from "@/evals/run";
import { briefModelFor } from "@/lib/llm";
import { PROMPT_VERSION } from "@/lib/llm/prompt";
import { SCHEMA_VERSION } from "@/lib/schemas/change-brief";
import { baselineCandidate } from "@/evals/gate";
import { estimateCost, loadPricingSnapshot, priceFor } from "@/scripts/pricing";

const DEFAULT_CONFIGS = ["gpt-6-luna:none", "gpt-6-luna:low", "gpt-5.4-mini:none"];

function usage(message: string): number {
  console.error(message);
  console.error(
    "usage: npm run evals -- [--config model:effort]... [--repeat 1-5] [--case id]... [--concurrency 1-4] [--dry-run]",
  );
  return 2;
}

async function main(): Promise<number> {
  const argv = process.argv.slice(2);
  const configTexts: string[] = [];
  const caseIds: string[] = [];
  let repeat = 3;
  let concurrency = 3;
  let dryRun = false;
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === "--config") configTexts.push(argv[++i] ?? "");
    else if (a === "--case") caseIds.push(argv[++i] ?? "");
    else if (a === "--repeat") repeat = Number(argv[++i]);
    else if (a === "--concurrency") concurrency = Number(argv[++i]);
    else if (a === "--dry-run") dryRun = true;
    else return usage(`unknown argument: ${a}`);
  }

  const configs: EvalConfig[] = [];
  for (const text of configTexts.length > 0 ? configTexts : DEFAULT_CONFIGS) {
    const c = parseConfig(text);
    if (c === null) return usage(`bad --config "${text}": expected model[:none|low|medium|high]`);
    if (!configs.some((x) => configLabel(x) === configLabel(c))) configs.push(c);
  }
  if (!Number.isInteger(repeat) || repeat < 1 || repeat > 5) return usage("--repeat must be 1-5");
  if (!Number.isInteger(concurrency) || concurrency < 1 || concurrency > MAX_CONCURRENCY) {
    return usage(`--concurrency must be 1-${MAX_CONCURRENCY}`);
  }
  const unknown = caseIds.filter((id) => !EVAL_CASES.some((c) => c.id === id));
  if (unknown.length > 0) return usage(`unknown case: ${unknown.join(", ")} (cases: ${EVAL_CASES.map((c) => c.id).join(", ")})`);
  const cases = caseIds.length > 0 ? EVAL_CASES.filter((c) => caseIds.includes(c.id)) : EVAL_CASES;

  const calls = plannedCalls(cases.length, configs.length, repeat);
  if (calls > MAX_EVAL_CALLS) return usage(`${calls} calls planned; the limit is ${MAX_EVAL_CALLS}`);

  const snapshot = loadPricingSnapshot();
  console.log(`eval set ${EVAL_SET_VERSION}   prompt ${PROMPT_VERSION}   schema ${SCHEMA_VERSION}`);
  console.log(`configs: ${configs.map(configLabel).join(", ")}`);
  console.log(`cases: ${cases.map((c) => c.id).join(", ")}`);
  console.log(`paid calls this run: ${calls} (${cases.length} cases x ${configs.length} configs x ${repeat} repeats, no retries)`);
  for (const c of configs) {
    if (priceFor(snapshot, c.model) === null) console.log(`note: no price for ${c.model} in the snapshot; its cost will be unknown`);
  }
  if (dryRun) {
    console.log("dry run: no model calls made");
    return 0;
  }
  if (briefModelFor(configs[0].model, configs[0].effort) === null) {
    console.error("No API key in the environment. Run through: op run --env-file=.env.local -- npm run evals");
    return 2;
  }

  let done = 0;
  const records = await runEvals({
    cases,
    configs,
    repeat,
    concurrency,
    modelFor: (c) => briefModelFor(c.model, c.effort)!,
    costOf: (r) => estimateCost(r.usage, r.model === null ? null : priceFor(snapshot, r.model)),
    onRecord: (r) => {
      done++;
      const failed = r.checks.filter((c) => !c.pass).map((c) => `${c.name}${c.severity === "bonus" ? "(bonus)" : ""}`);
      console.log(
        `[${done}/${calls}] ${r.config} ${r.case_id} #${r.repeat}: ${r.status} ${r.llm_ms} ms` +
          (failed.length > 0 ? `   failed: ${failed.join(", ")}` : "   all checks passed"),
      );
    },
  });

  const summaries = summarize(records, configs);
  const decision = decide(summaries);
  const meta = {
    generated_at: new Date().toISOString(),
    eval_set_version: EVAL_SET_VERSION,
    prompt_version: PROMPT_VERSION,
    schema_version: SCHEMA_VERSION,
    pricing_as_of: snapshot.as_of,
    repeat,
    cases: cases.map((c) => c.id),
  };
  const markdown = toMarkdown(meta, summaries, decision);

  mkdirSync("evals/reports", { recursive: true });
  const stamp = meta.generated_at.replace(/[:.]/g, "-");
  writeFileSync(`evals/reports/${stamp}.md`, markdown);
  writeFileSync(`evals/reports/${stamp}.json`, JSON.stringify({ meta, configs: configs.map(configLabel), summaries, decision, records }, null, 2));
  // CI eval gate input. Promoting it is a human step: review the report, then
  // copy it to evals/baseline.json and commit it with the report.
  const candidate = baselineCandidate(meta, `evals/reports/${stamp}.md`, configs, summaries, decision, calls);
  if (candidate !== null) writeFileSync(`evals/reports/${stamp}.baseline.json`, `${JSON.stringify(candidate, null, 2)}\n`);

  console.log(`\n${markdown}`);
  console.log(`saved: evals/reports/${stamp}.md and .json`);
  if (candidate !== null) console.log(`baseline candidate: evals/reports/${stamp}.baseline.json (copy to evals/baseline.json to promote)`);
  return summaries.some((s) => s.provider_errors > 0) ? 1 : 0;
}

main().then(
  (code) => process.exit(code),
  () => {
    console.error("evals failed with an unexpected error");
    process.exit(1);
  },
);
