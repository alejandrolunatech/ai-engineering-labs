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

export type AnalyzeRequest = z.infer<typeof AnalyzeRequestSchema>;
