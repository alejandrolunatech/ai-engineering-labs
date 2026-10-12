import { describe, expect, it } from "vitest";
import { BRIEF_LIMITS, ChangeBriefSchema, ModelBriefSchema } from "@/lib/schemas/change-brief";

// Synthetic fixture for schema shape only. Not real model output.
const fixture = {
  pr: { owner: "o", repo: "r", number: 1 },
  truncated: false,
  truncation_limitations: [],
  files_considered: 2,
  files_total: 2,
  schema_version: "0.2",
  prompt_version: "test",
  model: "test-model",
  usage: null,
  estimated_cost: null,
  ai_generated: true,
  brief: {
    summary: "s",
    why_it_matters: "w",
    user_impact: [],
    technical_impact: ["t"],
    risk: { level: "low", evidence: ["e"], uncertainty: ["u"] },
    testing_signals: [],
    rollout_considerations: [],
    rollback_considerations: [],
    open_questions: [],
    limitations: [],
  },
};

describe("ChangeBriefSchema", () => {
  it("accepts a well-formed brief with unknown usage/cost as null", () => {
    expect(ChangeBriefSchema.safeParse(fixture).success).toBe(true);
  });

  it("requires usage and estimated_cost to be present (null, not omitted)", () => {
    const withoutUsage: Record<string, unknown> = { ...fixture };
    delete withoutUsage.usage;
    expect(ChangeBriefSchema.safeParse(withoutUsage).success).toBe(false);
  });

  it("rejects ai_generated: false", () => {
    expect(ChangeBriefSchema.safeParse({ ...fixture, ai_generated: false }).success).toBe(false);
  });

  it("rejects unknown top-level fields", () => {
    expect(ChangeBriefSchema.safeParse({ ...fixture, extra: 1 }).success).toBe(false);
  });

  it("has no place for a review verdict", () => {
    const withVerdict = { ...fixture, brief: { ...fixture.brief, verdict: "approve" } };
    expect(ChangeBriefSchema.safeParse(withVerdict).success).toBe(false);
  });

  it("rejects an unknown risk level", () => {
    const bad = { ...fixture, brief: { ...fixture.brief, risk: { ...fixture.brief.risk, level: "critical" } } };
    expect(ChangeBriefSchema.safeParse(bad).success).toBe(false);
  });

  it("rejects an estimated cost not marked as an estimate", () => {
    const bad = { ...fixture, estimated_cost: { usd: 0.01, is_estimate: false, pricing_as_of: "2026-10-01" } };
    expect(ChangeBriefSchema.safeParse(bad).success).toBe(false);
  });
});

describe("ModelBriefSchema size limits (schema 0.2)", () => {
  const brief = fixture.brief;
  const parse = (b: unknown) => ModelBriefSchema.safeParse(b).success;

  it("accepts values at the limits", () => {
    const atLimit = {
      ...brief,
      summary: "s".repeat(BRIEF_LIMITS.paragraphChars),
      technical_impact: Array.from({ length: BRIEF_LIMITS.listItems }, () => "t".repeat(BRIEF_LIMITS.itemChars)),
    };
    expect(parse(atLimit)).toBe(true);
  });

  it.each([
    ["an empty summary", { summary: "" }],
    ["a whitespace-only summary", { summary: "   " }],
    ["an over-long summary", { summary: "s".repeat(BRIEF_LIMITS.paragraphChars + 1) }],
    ["an over-long why_it_matters", { why_it_matters: "w".repeat(BRIEF_LIMITS.paragraphChars + 1) }],
    ["too many list items", { open_questions: Array.from({ length: BRIEF_LIMITS.listItems + 1 }, () => "q") }],
    ["an over-long list item", { limitations: ["l".repeat(BRIEF_LIMITS.itemChars + 1)] }],
    ["an empty list item", { user_impact: [""] }],
    ["too many risk evidence items", { risk: { ...brief.risk, evidence: Array.from({ length: BRIEF_LIMITS.listItems + 1 }, () => "e") } }],
  ])("rejects %s", (_label, change) => {
    expect(parse({ ...brief, ...change })).toBe(false);
  });

  it("keeps empty lists valid: nothing supported to say is a valid answer", () => {
    expect(parse({ ...brief, technical_impact: [], risk: { ...brief.risk, evidence: [], uncertainty: [] } })).toBe(true);
  });
});
