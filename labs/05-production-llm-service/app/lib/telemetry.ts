import "server-only";
import { z } from "zod";
import type { GithubFailureReason } from "@/lib/github/client";
import type { IngestFailureReason } from "@/lib/github/ingest";
import { ERROR_CATEGORIES } from "@/lib/http/errors";
import type { ModelFailureReason, ModelUsage } from "@/lib/llm/types";

// Privacy-safe operational telemetry (ARCHITECTURE.md "Production telemetry
// event", PRODUCT-CONTRACT.md §6). One structured JSON line per /api/analyze
// request, written to stdout (Vercel keeps it in the runtime logs).
//
// [BOUNDARY] The allowlist is this Zod schema, not a convention. It is strict
// (no unknown keys), and every string field is an enum, a fixed version
// pattern or a model-ID pattern. Numbers are counts and durations. So no PR
// title, body, patch, prompt, model output, header, IP, cookie or key CAN be
// recorded: there is no field that would accept it. An event that fails the
// schema is dropped and replaced by a bare "telemetry_dropped" marker.
//
// Unknown is null, never zero (usage, cost, timings of steps that never ran).
// estimated_cost_usd is an estimate from lib/pricing.ts, not billing truth.

// Request-level reasons. Ingest and model reasons come from their modules.
export const REQUEST_REASONS = [
  "config_invalid",
  "bad_content_type",
  "body_too_large",
  "body_unreadable",
  "bad_json",
  "bad_request_shape",
  "bad_pr_url",
  "model_not_configured",
  // Phase 6 abuse controls: all decided before any GitHub or model call.
  "service_disabled",
  "rate_limited_ip",
  "rate_limited_global",
  "rate_limiter_unavailable",
  "rate_limiter_not_configured",
  "server_fields_invalid",
  "unexpected_exception",
] as const;

const GITHUB_REASONS = [
  "invalid_url",
  "request_budget_exhausted",
  "not_found",
  "unauthorized",
  "forbidden",
  "rate_limited",
  "upstream_5xx",
  "upstream_status",
  "bad_redirect",
  "timeout",
  "network_error",
  "too_large",
  "malformed_json",
  "malformed_response",
] as const satisfies readonly IngestFailureReason[];

const MODEL_REASONS = [
  "not_configured",
  "timeout",
  "network_error",
  "auth",
  "rate_limited",
  "bad_request",
  "upstream_5xx",
  "upstream_status",
  "incomplete_max_tokens",
  "incomplete_other",
  "refusal",
  "empty_output",
  "malformed_json",
  "schema_mismatch",
] as const satisfies readonly ModelFailureReason[];

// Compile-time completeness: adding a reason in client.ts, ingest.ts or
// types.ts without listing it here fails typecheck.
type Missing<All, Listed> = Exclude<All, Listed>;
const _githubComplete: Missing<GithubFailureReason | "malformed_response", (typeof GITHUB_REASONS)[number]> extends never ? true : never = true;
const _modelComplete: Missing<ModelFailureReason, (typeof MODEL_REASONS)[number]> extends never ? true : never = true;
void _githubComplete;
void _modelComplete;

const MODEL_ID = /^[a-z0-9][a-z0-9.\-]{0,99}$/;
const VERSION = /^[a-z0-9][a-z0-9.\-]{0,19}$/;
const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;

const count = z.number().int().nonnegative().nullable();
const ms = z.number().int().nonnegative().nullable();

export const OUTCOMES = ["success", ...(Object.keys(ERROR_CATEGORIES) as (keyof typeof ERROR_CATEGORIES)[])] as const;

// A random v4 UUID made by the server for each request (Phase 7). It is also
// sent to the client as X-Request-Id, so a user can quote it and the operator
// can find this event. It carries no information about the request.
export const REQUEST_ID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

export const AnalysisEventSchema = z.strictObject({
  event: z.literal("analysis"),
  request_id: z.string().regex(REQUEST_ID),
  outcome: z.enum(OUTCOMES),
  http_status: z.number().int().min(100).max(599),
  // Where the failure happened, then its code. Both null on success.
  failure_stage: z.enum(["request", "github", "model"]).nullable(),
  reason: z.enum([...REQUEST_REASONS, ...GITHUB_REASONS, ...MODEL_REASONS]).nullable(),

  provider: z.enum(["openai"]).nullable(),
  model: z.string().regex(MODEL_ID).nullable(),
  reasoning_effort: z.enum(["none", "low", "medium", "high"]).nullable(),
  schema_version: z.string().regex(VERSION),
  prompt_version: z.string().regex(VERSION),

  total_ms: z.number().int().nonnegative(),
  github_ms: ms,
  normalization_ms: ms,
  llm_ms: ms,
  validation_ms: ms,

  github_requests: count,
  github_redirects: count,
  github_rate_limit_remaining: count,

  files_considered: count,
  files_total: count,
  evidence_chars: count,
  truncated: z.boolean().nullable(),

  input_tokens: count,
  cached_input_tokens: count,
  output_tokens: count,
  reasoning_tokens: count,
  // reported: input and output both known. partial: some known. unknown: none.
  usage_status: z.enum(["reported", "partial", "unknown"]),

  estimated_cost_usd: z.number().nonnegative().nullable(),
  cost_status: z.enum(["estimated", "unknown"]),
  pricing_as_of: z.string().regex(ISO_DATE).nullable(),

  // Did the reply pass schema validation? null when no reply was validated.
  schema_valid: z.boolean().nullable(),
});

export type AnalysisEvent = z.infer<typeof AnalysisEventSchema>;
export type FailureReason = NonNullable<AnalysisEvent["reason"]>;

export function usageStatus(usage: ModelUsage | null): AnalysisEvent["usage_status"] {
  if (usage === null) return "unknown";
  const known = [usage.input_tokens, usage.output_tokens].filter((v) => v !== null).length;
  return known === 2 ? "reported" : known === 1 ? "partial" : "unknown";
}

// A model ID from the provider is data from outside: kept only if it looks like one.
export function safeModelId(model: string | null | undefined): string | null {
  return typeof model === "string" && MODEL_ID.test(model) ? model : null;
}

export type TelemetrySink = (line: string) => void;

// stdout. Replaced only by tests.
const defaultSink: TelemetrySink = (line) => console.info(line);

export function emitAnalysisEvent(event: AnalysisEvent, sink: TelemetrySink = defaultSink): void {
  const parsed = AnalysisEventSchema.safeParse(event);
  // Never log the rejected event or the Zod error: either could hold whatever
  // made it invalid.
  sink(JSON.stringify(parsed.success ? parsed.data : { event: "telemetry_dropped" }));
}
