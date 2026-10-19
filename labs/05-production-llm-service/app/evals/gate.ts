import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { z } from "zod";
import { EVAL_CASES, EVAL_SET_VERSION } from "@/evals/cases";
import { configLabel, type ConfigSummary, type Decision, type EvalConfig } from "@/evals/run";
import { INSTRUCTIONS, PROMPT_VERSION, buildInput } from "@/lib/llm/prompt";
import { ModelBriefSchema, SCHEMA_VERSION } from "@/lib/schemas/change-brief";

// CI eval gate (Phase 5). Runs in `npm test` and as its own CI step, with NO
// model calls and no API key.
//
// What it proves: the prompt, the model output schema and the eval set that
// ship are byte-for-byte the ones a recorded paid eval run passed, and that run
// picked the production config with no gate-case failures. Change any of them
// and CI goes red until someone re-runs `npm run evals` (paid, on a laptop) and
// commits the new evals/baseline.json.
//
// What it does NOT prove: model quality today (models drift; only a paid run
// measures that), or which model the deployment uses (OPENAI_MODEL lives in
// Vercel, outside CI; checking it is part of the G1 click-through).
//
// [DETERMINISTIC] fingerprints and the rules below.

export const MIN_CORE_PASS_RATE = 0.95;

function sha256(text: string): string {
  return createHash("sha256").update(text.replace(/\r\n/g, "\n")).digest("hex");
}

function source(relative: string): string {
  return readFileSync(new URL(relative, import.meta.url), "utf8");
}

// prompt: the instructions plus the exact input built for every eval case, so a
// change to the input layout counts too. schema: the full model-output JSON
// Schema, size limits included. eval_set: the case and check source files.
export function currentFingerprint() {
  return {
    prompt_sha256: sha256(JSON.stringify([INSTRUCTIONS, ...EVAL_CASES.map((c) => buildInput(c.evidence))])),
    schema_sha256: sha256(JSON.stringify(z.toJSONSchema(ModelBriefSchema))),
    eval_set_sha256: sha256(source("./cases.ts") + "\n" + source("./checks.ts")),
  };
}

export const BaselineSchema = z.strictObject({
  eval_set_version: z.string(),
  prompt_version: z.string(),
  schema_version: z.string(),
  fingerprint: z.strictObject({
    prompt_sha256: z.string().regex(/^[0-9a-f]{64}$/),
    schema_sha256: z.string().regex(/^[0-9a-f]{64}$/),
    eval_set_sha256: z.string().regex(/^[0-9a-f]{64}$/),
  }),
  // The config production must run, as model:effort. Must be the run's pick.
  production_config: z.string(),
  run: z.strictObject({
    generated_at: z.string(),
    report: z.string(),
    pick: z.string().nullable(),
    calls: z.number().int().positive(),
    // The production config's own results in that run.
    core_pass_rate: z.number().min(0).max(1),
    gate_failures: z.number().int().nonnegative(),
    provider_errors: z.number().int().nonnegative(),
    invalid_outputs: z.number().int().nonnegative(),
  }),
});

export type Baseline = z.infer<typeof BaselineSchema>;

// Every reason the gate fails. Empty means it passes.
export function gateProblems(baseline: Baseline, current = currentFingerprint()): string[] {
  const problems: string[] = [];
  const same = (what: string, recorded: string, now: string) => {
    if (recorded !== now) problems.push(`${what} is ${now} but the baseline was run on ${recorded}.`);
  };
  same("EVAL_SET_VERSION", baseline.eval_set_version, EVAL_SET_VERSION);
  same("PROMPT_VERSION", baseline.prompt_version, PROMPT_VERSION);
  same("SCHEMA_VERSION", baseline.schema_version, SCHEMA_VERSION);
  for (const [key, value] of Object.entries(current) as [keyof typeof current, string][]) {
    if (baseline.fingerprint[key] !== value) {
      problems.push(`${key} changed since the baseline run: re-run the paid evals and commit a new evals/baseline.json.`);
    }
  }
  const r = baseline.run;
  if (r.pick !== baseline.production_config) {
    problems.push(`production config ${baseline.production_config} is not the run's pick (${r.pick ?? "none"}).`);
  }
  if (r.gate_failures > 0) problems.push(`${r.gate_failures} gate-case run(s) failed a core check.`);
  if (r.provider_errors > 0) problems.push(`${r.provider_errors} provider error(s): the run is incomplete.`);
  if (r.core_pass_rate < MIN_CORE_PASS_RATE) {
    problems.push(`core pass rate ${(r.core_pass_rate * 100).toFixed(1)}% is below ${MIN_CORE_PASS_RATE * 100}%.`);
  }
  return problems;
}

export function loadBaseline(): Baseline {
  return BaselineSchema.parse(JSON.parse(source("./baseline.json")));
}

// A baseline candidate from a finished run, for scripts/run-evals.ts. The run's
// pick becomes the production config; promoting it is a human commit.
export function baselineCandidate(
  meta: { generated_at: string },
  report: string,
  configs: readonly EvalConfig[],
  summaries: readonly ConfigSummary[],
  decision: Decision,
  calls: number,
): Baseline | null {
  const picked = summaries.find((s) => s.config === decision.pick);
  if (decision.pick === null || picked === undefined || picked.core.rate === null) return null;
  if (!configs.some((c) => configLabel(c) === decision.pick)) return null;
  return {
    eval_set_version: EVAL_SET_VERSION,
    prompt_version: PROMPT_VERSION,
    schema_version: SCHEMA_VERSION,
    fingerprint: currentFingerprint(),
    production_config: decision.pick,
    run: {
      generated_at: meta.generated_at,
      report,
      pick: decision.pick,
      calls,
      core_pass_rate: picked.core.rate,
      gate_failures: picked.gate_failures,
      provider_errors: picked.provider_errors,
      invalid_outputs: picked.invalid_outputs,
    },
  };
}
