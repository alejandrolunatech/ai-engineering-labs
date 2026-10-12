import type { EvalCase } from "@/evals/cases";
import type { Severity } from "@/evals/checks";
import type { BriefModel, ModelResult, ModelUsage } from "@/lib/llm/types";
import type { ModelBrief } from "@/lib/schemas/change-brief";

// Eval runner core: runs cases against model configs, grades each brief with
// the case's named checks, summarizes, and applies the pre-registered model
// pick rule (LEARNING-NOTES.md Phase 4). No I/O of its own: the model factory
// and cost function are passed in, so tests drive it with a fake model.
//
// [DETERMINISTIC] case evidence, grading, summaries and the pick rule.
// [PROBABILISTIC] the briefs themselves: the same config can pass on one
// repeat and fail on the next, which is why every case runs several times.

export const EFFORTS = ["none", "low", "medium", "high"] as const;
export type Effort = (typeof EFFORTS)[number];
export type EvalConfig = { model: string; effort: Effort };

export const MAX_EVAL_CALLS = 200;
export const MAX_CONCURRENCY = 4;
// Pick rule: configs within this many points of the best core pass rate count as tied on quality.
export const QUALITY_MARGIN = 0.05;

export function configLabel(c: EvalConfig): string {
  return `${c.model}:${c.effort}`;
}

// "gpt-6-luna:low" -> { model, effort }; effort defaults to none.
export function parseConfig(text: string): EvalConfig | null {
  const [model, effort = "none", ...rest] = text.split(":");
  if (rest.length > 0 || !/^[a-z0-9][a-z0-9.\-]{0,99}$/.test(model)) return null;
  if (!(EFFORTS as readonly string[]).includes(effort)) return null;
  return { model, effort: effort as Effort };
}

export type CheckOutcome = { name: string; severity: Severity; pass: boolean; detail?: string };

export type RunRecord = {
  config: string;
  case_id: string;
  gate: boolean;
  repeat: number;
  // "ok", or the model failure reason.
  status: "ok" | Extract<ModelResult, { ok: false }>["reason"];
  // provider_unavailable is an infrastructure failure (network, auth, quota):
  // it says nothing about quality and is excluded from pass rates.
  // output_invalid is model behavior: every check of that run fails.
  failure_kind: Extract<ModelResult, { ok: false }>["kind"] | null;
  served_model: string | null;
  usage: ModelUsage | null;
  llm_ms: number;
  cost_usd: number | null;
  checks: CheckOutcome[];
  brief: ModelBrief | null;
};

export function gradeBrief(c: EvalCase, brief: ModelBrief): CheckOutcome[] {
  return c.checks.map((chk) => {
    try {
      const r = chk.run(brief);
      return { name: chk.name, severity: chk.severity, pass: r.pass, ...(r.detail === undefined ? {} : { detail: r.detail }) };
    } catch {
      return { name: chk.name, severity: chk.severity, pass: false, detail: "check threw an error" };
    }
  });
}

export type RunOptions = {
  cases: readonly EvalCase[];
  configs: readonly EvalConfig[];
  repeat: number;
  concurrency: number;
  modelFor: (c: EvalConfig) => BriefModel;
  costOf: (result: ModelResult) => number | null;
  onRecord?: (r: RunRecord) => void;
};

export function plannedCalls(cases: number, configs: number, repeat: number): number {
  return cases * configs * repeat;
}

export async function runEvals(opts: RunOptions): Promise<RunRecord[]> {
  const calls = plannedCalls(opts.cases.length, opts.configs.length, opts.repeat);
  if (calls > MAX_EVAL_CALLS) throw new Error(`refusing ${calls} model calls (limit ${MAX_EVAL_CALLS})`);
  const concurrency = Math.max(1, Math.min(MAX_CONCURRENCY, Math.floor(opts.concurrency)));

  // Configs interleaved per case and repeat, so a slow minute at the provider
  // does not land on one config only.
  const jobs: { config: EvalConfig; c: EvalCase; repeat: number }[] = [];
  for (let repeat = 1; repeat <= opts.repeat; repeat++) {
    for (const c of opts.cases) for (const config of opts.configs) jobs.push({ config, c, repeat });
  }
  const models = new Map(opts.configs.map((c) => [configLabel(c), opts.modelFor(c)]));

  const records: RunRecord[] = [];
  let next = 0;
  async function worker() {
    while (next < jobs.length) {
      const { config, c, repeat } = jobs[next++];
      const label = configLabel(config);
      const result = await models.get(label)!.generateBrief(c.evidence);
      const record: RunRecord = {
        config: label,
        case_id: c.id,
        gate: c.gate,
        repeat,
        status: result.ok ? "ok" : result.reason,
        failure_kind: result.ok ? null : result.kind,
        served_model: result.model,
        usage: result.usage,
        llm_ms: result.llmMs,
        cost_usd: opts.costOf(result),
        checks: result.ok
          ? gradeBrief(c, result.brief)
          : c.checks.map((chk) => ({ name: chk.name, severity: chk.severity, pass: false, detail: `no valid brief (${result.reason})` })),
        brief: result.ok ? result.brief : null,
      };
      records.push(record);
      opts.onRecord?.(record);
    }
  }
  await Promise.all(Array.from({ length: concurrency }, worker));

  const order = (r: RunRecord) =>
    [opts.configs.findIndex((c) => configLabel(c) === r.config), opts.cases.findIndex((c) => c.id === r.case_id), r.repeat];
  return records.sort((a, b) => {
    const [x, y] = [order(a), order(b)];
    return x[0] - y[0] || x[1] - y[1] || x[2] - y[2];
  });
}

export type ConfigSummary = {
  config: string;
  runs: number;
  provider_errors: number;
  invalid_outputs: number;
  core: { passed: number; total: number; rate: number | null };
  bonus: { passed: number; total: number; rate: number | null };
  // Runs where every core check passed.
  clean_runs: number;
  // Gate-case runs with at least one failed core check.
  gate_failures: number;
  served_models: string[];
  llm_ms: { mean: number | null; max: number | null };
  // Mean estimated cost per call; null when any graded call has an unknown cost.
  mean_cost_usd: number | null;
  total_cost_usd: number | null;
  failures: { case_id: string; repeat: number; check: string; severity: Severity; detail?: string }[];
};

function rate(passed: number, total: number): number | null {
  return total === 0 ? null : passed / total;
}

export function summarize(records: readonly RunRecord[], configs: readonly EvalConfig[]): ConfigSummary[] {
  return configs.map((cfg) => {
    const label = configLabel(cfg);
    const mine = records.filter((r) => r.config === label);
    const graded = mine.filter((r) => r.failure_kind !== "provider_unavailable");
    const all = graded.flatMap((r) => r.checks);
    const core = all.filter((c) => c.severity === "core");
    const bonus = all.filter((c) => c.severity === "bonus");
    const coreFails = (r: RunRecord) => r.checks.some((c) => c.severity === "core" && !c.pass);
    const ms = graded.map((r) => r.llm_ms);
    const costs = graded.map((r) => r.cost_usd);
    const costKnown = costs.length > 0 && costs.every((c) => c !== null);
    const total = costKnown ? (costs as number[]).reduce((a, b) => a + b, 0) : null;
    return {
      config: label,
      runs: mine.length,
      provider_errors: mine.length - graded.length,
      invalid_outputs: graded.filter((r) => r.failure_kind === "output_invalid").length,
      core: { passed: core.filter((c) => c.pass).length, total: core.length, rate: rate(core.filter((c) => c.pass).length, core.length) },
      bonus: { passed: bonus.filter((c) => c.pass).length, total: bonus.length, rate: rate(bonus.filter((c) => c.pass).length, bonus.length) },
      clean_runs: graded.filter((r) => !coreFails(r)).length,
      gate_failures: graded.filter((r) => r.gate && coreFails(r)).length,
      served_models: [...new Set(graded.map((r) => r.served_model).filter((m): m is string => m !== null))].sort(),
      llm_ms: {
        mean: ms.length === 0 ? null : Math.round(ms.reduce((a, b) => a + b, 0) / ms.length),
        max: ms.length === 0 ? null : Math.max(...ms),
      },
      mean_cost_usd: total === null ? null : total / graded.length,
      total_cost_usd: total,
      failures: graded.flatMap((r) =>
        r.checks
          .filter((c) => !c.pass)
          .map((c) => ({ case_id: r.case_id, repeat: r.repeat, check: c.name, severity: c.severity, ...(c.detail === undefined ? {} : { detail: c.detail }) })),
      ),
    };
  });
}

export type Decision = { pick: string | null; reasons: string[] };

// The pre-registered pick rule, written before the first paid baseline
// (LEARNING-NOTES.md Phase 4). Configs are given in preference order: the
// first one wins exact ties.
export function decide(summaries: readonly ConfigSummary[]): Decision {
  const reasons: string[] = [];
  const incomplete = summaries.filter((s) => s.provider_errors > 0);
  if (incomplete.length > 0) {
    return {
      pick: null,
      reasons: incomplete.map((s) => `${s.config}: ${s.provider_errors} provider error(s); the run is incomplete, re-run before deciding.`),
    };
  }
  const qualified = summaries.filter((s) => {
    if (s.gate_failures > 0) reasons.push(`${s.config}: disqualified, ${s.gate_failures} gate-case run(s) failed a core check.`);
    if (s.core.rate === null) reasons.push(`${s.config}: disqualified, no graded runs.`);
    return s.gate_failures === 0 && s.core.rate !== null;
  });
  if (qualified.length === 0) {
    reasons.push("No config qualifies: no final model from this run.");
    return { pick: null, reasons };
  }
  const best = Math.max(...qualified.map((s) => s.core.rate!));
  const close = qualified.filter((s) => s.core.rate! >= best - QUALITY_MARGIN - 1e-9);
  reasons.push(
    `Best core pass rate ${(best * 100).toFixed(1)}%; within ${QUALITY_MARGIN * 100} points: ${close.map((s) => s.config).join(", ")}.`,
  );
  // Unknown cost is unknown, not cheap or expensive: one unpriced candidate
  // means the cheapest-config rule cannot be applied.
  const unpriced = close.filter((s) => s.mean_cost_usd === null);
  if (unpriced.length > 0) {
    reasons.push(`No cost estimate for ${unpriced.map((s) => s.config).join(", ")}: cannot apply the cheapest-config rule.`);
    return { pick: null, reasons };
  }
  const cheapest = close.reduce((a, b) => (b.mean_cost_usd! < a.mean_cost_usd! ? b : a));
  reasons.push(`Cheapest of those by mean estimated cost per brief: ${cheapest.config}.`);
  return { pick: cheapest.config, reasons };
}

// Report text can contain model output: keep it on one line and out of table syntax.
function cell(text: string, max = 220): string {
  const flat = text.replace(/[\u0000-\u001f\u007f-\u009f]/g, " ").replace(/\\/g, "\\\\").replace(/\|/g, "\\|").replace(/\s+/g, " ").trim();
  return flat.length > max ? `${flat.slice(0, max - 1)}…` : flat;
}

const pct = (r: number | null) => (r === null ? "n/a" : `${(r * 100).toFixed(1)}%`);
const usd = (v: number | null, digits = 6) => (v === null ? "unknown" : `$${v.toFixed(digits)}`);

export type ReportMeta = {
  generated_at: string;
  eval_set_version: string;
  prompt_version: string;
  schema_version: string;
  pricing_as_of: string;
  repeat: number;
  cases: string[];
};

export function toMarkdown(meta: ReportMeta, summaries: readonly ConfigSummary[], decision: Decision): string {
  const lines = [
    `# ChangeBrief eval report`,
    ``,
    `- generated: ${meta.generated_at}`,
    `- eval set ${meta.eval_set_version}, prompt ${meta.prompt_version}, schema ${meta.schema_version}`,
    `- cases (${meta.cases.length}): ${meta.cases.join(", ")}`,
    `- repeats per case: ${meta.repeat}`,
    `- costs are ESTIMATES from the pricing snapshot of ${meta.pricing_as_of}, not billing truth`,
    ``,
    `| config | served model | core | bonus | clean runs | gate failures | invalid | provider errors | mean llm_ms | max llm_ms | mean est. cost | total est. cost |`,
    `|---|---|---|---|---|---|---|---|---|---|---|---|`,
    ...summaries.map(
      (s) =>
        `| ${s.config} | ${s.served_models.join(", ") || "unknown"} | ${pct(s.core.rate)} (${s.core.passed}/${s.core.total}) | ${pct(s.bonus.rate)} (${s.bonus.passed}/${s.bonus.total}) | ${s.clean_runs}/${s.runs - s.provider_errors} | ${s.gate_failures} | ${s.invalid_outputs} | ${s.provider_errors} | ${s.llm_ms.mean ?? "n/a"} | ${s.llm_ms.max ?? "n/a"} | ${usd(s.mean_cost_usd)} | ${usd(s.total_cost_usd, 4)} |`,
    ),
    ``,
    `## Pick rule result`,
    ``,
    `Pick: **${decision.pick ?? "none"}**`,
    ``,
    ...decision.reasons.map((r) => `- ${r}`),
    ``,
    `## Failed checks`,
  ];
  for (const s of summaries) {
    lines.push(``, `### ${s.config}`, ``);
    if (s.failures.length === 0) {
      lines.push(`No failed checks.`);
      continue;
    }
    lines.push(`| case | repeat | check | severity | detail |`, `|---|---|---|---|---|`);
    for (const f of s.failures) {
      lines.push(`| ${f.case_id} | ${f.repeat} | ${f.check} | ${f.severity} | ${cell(f.detail ?? "")} |`);
    }
  }
  return `${lines.join("\n")}\n`;
}
