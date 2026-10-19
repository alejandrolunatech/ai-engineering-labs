import { describe, expect, it } from "vitest";
import { MIN_CORE_PASS_RATE, baselineCandidate, currentFingerprint, gateProblems, loadBaseline, type Baseline } from "@/evals/gate";
import { decide, summarize, type RunRecord } from "@/evals/run";

// The CI eval gate (evals/gate.ts). No model calls, no API key.

describe("eval gate", () => {
  it("passes: the shipped prompt, schema and eval set are the ones the baseline run passed", () => {
    const problems = gateProblems(loadBaseline());
    // On failure this prints why. The fix is a paid re-run and a new
    // evals/baseline.json, never editing the fingerprint by hand.
    expect(problems).toEqual([]);
  });
});

describe("eval gate rules", () => {
  const baseline = (): Baseline => structuredClone(loadBaseline());

  it("fails when the prompt, schema or eval set changed", () => {
    for (const key of ["prompt_sha256", "schema_sha256", "eval_set_sha256"] as const) {
      const b = baseline();
      b.fingerprint[key] = "0".repeat(64);
      expect(gateProblems(b).join(" ")).toContain(key);
    }
  });

  it("fails when a version differs", () => {
    const b = baseline();
    b.prompt_version = "p0";
    expect(gateProblems(b).join(" ")).toContain("PROMPT_VERSION");
  });

  it("fails when production is not the run's pick", () => {
    const b = baseline();
    b.production_config = "gpt-5.4-mini:none";
    expect(gateProblems(b).join(" ")).toContain("not the run's pick");
  });

  it("fails on gate failures, provider errors or a low core rate", () => {
    const b = baseline();
    b.run.gate_failures = 1;
    b.run.provider_errors = 2;
    b.run.core_pass_rate = MIN_CORE_PASS_RATE - 0.01;
    expect(gateProblems(b)).toHaveLength(3);
  });

  it("builds a candidate from a run, and none without a pick", () => {
    const record = (config: string): RunRecord => ({
      config,
      case_id: "c",
      gate: false,
      repeat: 1,
      status: "ok",
      failure_kind: null,
      served_model: "gpt-6-luna",
      usage: null,
      llm_ms: 1,
      cost_usd: 0.001,
      checks: [{ name: "x", severity: "core", pass: true }],
      brief: null,
    });
    const configs = [{ model: "gpt-6-luna", effort: "none" as const }];
    const summaries = summarize([record("gpt-6-luna:none")], configs);
    const candidate = baselineCandidate({ generated_at: "t" }, "r.md", configs, summaries, decide(summaries), 1);
    expect(candidate).toMatchObject({ production_config: "gpt-6-luna:none", fingerprint: currentFingerprint() });
    expect(candidate !== null && gateProblems(candidate)).toEqual([]);
    expect(baselineCandidate({ generated_at: "t" }, "r.md", configs, summaries, { pick: null, reasons: [] }, 1)).toBeNull();
  });
});
