import { z } from "zod";
import { MAX_PR_NUMBER, MAX_URL_LENGTH } from "@/lib/pr-url";

// Request: exactly one field. Unknown fields are rejected, not stripped.
export const AnalyzeRequestSchema = z.strictObject({
  url: z.string().max(MAX_URL_LENGTH),
});

export const PullRequestRefSchema = z.strictObject({
  owner: z.string().min(1).max(39),
  repo: z.string().min(1).max(100),
  number: z.number().int().min(1).max(MAX_PR_NUMBER),
});

// Phase 1 success response: the PR was parsed and the API URL constructed, but
// nothing was fetched.
export const ParsedResponseSchema = z.strictObject({
  status: z.literal("parsed"),
  pr: PullRequestRefSchema,
  wouldFetch: z.string().startsWith("https://api.github.com/repos/"),
});

export type AnalyzeRequest = z.infer<typeof AnalyzeRequestSchema>;
export type ParsedResponse = z.infer<typeof ParsedResponseSchema>;
