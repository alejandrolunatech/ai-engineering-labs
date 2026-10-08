import type { BriefModel, ModelResult } from "@/lib/llm/types";
import type { ModelBrief } from "@/lib/schemas/change-brief";
import type { NormalizedPullRequest } from "@/lib/schemas/normalized-pr";

// Test-only fake model. No SDK, no network, no API money.

export const VALID_MODEL_BRIEF: ModelBrief = {
  summary: "Adds a widget cache.",
  why_it_matters: "Pages load faster for repeat visitors.",
  user_impact: ["Faster repeat page loads."],
  technical_impact: ["New cache module."],
  risk: { level: "medium", evidence: ["Touches request handling."], uncertainty: ["No load-test data in the PR."] },
  testing_signals: ["A test file was changed."],
  rollout_considerations: [],
  rollback_considerations: ["Revert the PR."],
  open_questions: ["What is the cache eviction policy?"],
  limitations: [],
};

export const FAKE_USAGE = { input_tokens: 1234, cached_input_tokens: 0, output_tokens: 321, reasoning_tokens: 0 };

export type FakeModel = BriefModel & { calls: NormalizedPullRequest[] };

export function fakeModel(result: Partial<Extract<ModelResult, { ok: true }>> | Extract<ModelResult, { ok: false }> = {}): FakeModel {
  const calls: NormalizedPullRequest[] = [];
  return {
    calls,
    async generateBrief(evidence) {
      calls.push(evidence);
      if ("ok" in result && result.ok === false) return result;
      return {
        ok: true,
        brief: VALID_MODEL_BRIEF,
        provider: "openai",
        model: "gpt-test-model",
        usage: FAKE_USAGE,
        llmMs: 5,
        ...result,
      } as ModelResult;
    },
  };
}
