import { z } from "zod";
import { PullRequestRefSchema } from "@/lib/schemas/analyze";

// ChangeBrief output schema (PRODUCT-CONTRACT.md §3). POST /api/analyze returns
// it, built from one model call (lib/llm/) plus server-written fields.
//
// Versions (bump on ANY change to fields or limits; it ships with every brief):
// - 0.1 (Phase 1-3): shape only.
// - 0.2 (Phase 4): size limits on every model-written string and list.

export const SCHEMA_VERSION = "0.2";

// [BOUNDARY] Size limits. They bound what the UI renders and what a reply can
// contain; they are deliberately looser than the prompt's style asks (at most 5
// short items), so an eval can measure the style without the schema turning a
// slightly long answer into an error. A reply outside these limits is rejected.
export const BRIEF_LIMITS = {
  paragraphChars: 800,
  itemChars: 400,
  listItems: 8,
} as const;

const Paragraph = z.string().trim().min(1).max(BRIEF_LIMITS.paragraphChars);
const TextList = z.array(z.string().trim().min(1).max(BRIEF_LIMITS.itemChars)).max(BRIEF_LIMITS.listItems);

// §3a — the model writes the content. The schema enforces shape and size only;
// it says nothing about whether the content is true. Evals measure that.
export const ModelBriefSchema = z.strictObject({
  summary: Paragraph,
  why_it_matters: Paragraph,
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
    cached_input_tokens: z.number().int().nonnegative().nullable(),
    output_tokens: z.number().int().nonnegative().nullable(),
    // Part of output_tokens; billed as output.
    reasoning_tokens: z.number().int().nonnegative().nullable(),
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
  // Server-written by lib/normalize/evidence.ts (one line per affected file, so
  // up to ~100 short lines). NOT the model's TextList: its 8-item cap would turn
  // a valid large-PR brief into output_invalid after a paid call.
  truncation_limitations: z.array(z.string()),
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

// Timing of THIS request (Phase 5). Kept outside the brief: it describes the
// request that produced the brief, not the brief itself.
export const RequestTimingSchema = z.strictObject({
  total_ms: z.number().int().nonnegative(),
  github_ms: z.number().int().nonnegative(),
  llm_ms: z.number().int().nonnegative(),
});

// POST /api/analyze success response (Phase 3; timing added in Phase 5).
export const BriefResponseSchema = z.strictObject({
  status: z.literal("brief"),
  brief: ChangeBriefSchema,
  timing: RequestTimingSchema,
});

export type BriefResponse = z.infer<typeof BriefResponseSchema>;
