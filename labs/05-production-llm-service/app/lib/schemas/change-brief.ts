import { z } from "zod";
import { PullRequestRefSchema } from "@/lib/schemas/analyze";

// ChangeBrief output schema, version 0.1 (PRODUCT-CONTRACT.md §3).
// Field names follow the contract's proposed names. Phase 4 hardens them
// (string limits, list sizes, risk levels). Nothing produces this object yet.

export const SCHEMA_VERSION = "0.1";

const TextList = z.array(z.string());

// §3a — the model writes the content. The schema enforces shape only; it says
// nothing about whether the content is true.
export const ModelBriefSchema = z.strictObject({
  summary: z.string(),
  why_it_matters: z.string(),
  user_impact: TextList,
  technical_impact: TextList,
  risk: z.strictObject({
    // Change risk (blast radius x uncertainty), not a code-quality verdict.
    level: z.enum(["low", "medium", "high"]),
    evidence: TextList,
    uncertainty: TextList,
  }),
  testing_signals: TextList,
  rollout_considerations: TextList,
  rollback_considerations: TextList,
  open_questions: TextList,
  limitations: TextList,
});

// §3b — set by server code, never taken from the model.
// Unknown usage/cost is null, never zero.
export const UsageSchema = z
  .strictObject({
    input_tokens: z.number().int().nonnegative().nullable(),
    output_tokens: z.number().int().nonnegative().nullable(),
  })
  .nullable();

export const EstimatedCostSchema = z
  .strictObject({
    usd: z.number().nonnegative(),
    is_estimate: z.literal(true),
    pricing_as_of: z.string(),
  })
  .nullable();

export const ServerFieldsSchema = z.strictObject({
  pr: PullRequestRefSchema,
  truncated: z.boolean(),
  truncation_limitations: TextList,
  files_considered: z.number().int().nonnegative(),
  files_total: z.number().int().nonnegative(),
  schema_version: z.literal(SCHEMA_VERSION),
  prompt_version: z.string(),
  model: z.string(),
  usage: UsageSchema,
  estimated_cost: EstimatedCostSchema,
  ai_generated: z.literal(true),
});

export const ChangeBriefSchema = z.strictObject({
  ...ServerFieldsSchema.shape,
  brief: ModelBriefSchema,
});

export type ModelBrief = z.infer<typeof ModelBriefSchema>;
export type ChangeBrief = z.infer<typeof ChangeBriefSchema>;
