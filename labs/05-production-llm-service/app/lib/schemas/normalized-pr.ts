import { z } from "zod";
import { PullRequestRefSchema } from "@/lib/schemas/analyze";

// Provider-neutral evidence envelope produced by lib/normalize/evidence.ts.
// Contains only what ChangeBrief needs: no author emails, avatars, user IDs or
// GitHub URLs. title/body/filename/patch are UNTRUSTED PR content carried as
// data; limitations[] is server-written and never contains PR content.

export const FILE_STATUSES = [
  "added",
  "removed",
  "modified",
  "renamed",
  "copied",
  "changed",
  "unchanged",
] as const;

export const PATCH_UNAVAILABLE_REASONS = [
  // GitHub sent no patch (binary file, or a diff too large on GitHub's side).
  "not_provided_by_github",
  // The 60,000-character total evidence budget was used up by earlier content.
  "evidence_budget_exhausted",
] as const;

export const NormalizedFileSchema = z.strictObject({
  filename: z.string(),
  status: z.enum(FILE_STATUSES),
  additions: z.number().int().nonnegative(),
  deletions: z.number().int().nonnegative(),
  patch: z.string().nullable(),
  patch_truncated: z.boolean(),
  patch_unavailable_reason: z.enum(PATCH_UNAVAILABLE_REASONS).nullable(),
});

export const CoverageSchema = z.strictObject({
  files_total: z.number().int().nonnegative(),
  files_considered: z.number().int().nonnegative(),
  chars_available: z.number().int().nonnegative(),
  chars_included: z.number().int().nonnegative(),
});

export const NormalizedPullRequestSchema = z.strictObject({
  pr: PullRequestRefSchema,
  title: z.string(),
  body: z.string().nullable(),
  state: z.enum(["open", "closed"]),
  draft: z.boolean(),
  merged: z.boolean(),
  base_ref: z.string(),
  head_ref: z.string(),
  additions: z.number().int().nonnegative(),
  deletions: z.number().int().nonnegative(),
  changed_files: z.number().int().nonnegative(),
  files: z.array(NormalizedFileSchema).max(50),
  coverage: CoverageSchema,
  truncated: z.boolean(),
  limitations: z.array(z.string()),
});

export type NormalizedFile = z.infer<typeof NormalizedFileSchema>;
export type NormalizedPullRequest = z.infer<typeof NormalizedPullRequestSchema>;

// POST /api/analyze success response in Phase 2. DEVELOPMENT OUTPUT: Phase 3
// replaces it with the ChangeBrief; the evidence is then sent to the model,
// not returned to the browser.
export const NormalizedResponseSchema = z.strictObject({
  status: z.literal("normalized"),
  evidence: NormalizedPullRequestSchema,
});

export type NormalizedResponse = z.infer<typeof NormalizedResponseSchema>;
