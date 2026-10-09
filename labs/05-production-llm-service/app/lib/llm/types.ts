import type { ModelBrief } from "@/lib/schemas/change-brief";
import type { NormalizedPullRequest } from "@/lib/schemas/normalized-pr";

// Provider-neutral model interface (ARCHITECTURE.md "Model adapter").
// Provider SDK objects stop at the adapter: nothing here mentions OpenAI.

// Provider-reported counts. null means the provider did not report it:
// unknown, never zero.
export type ModelUsage = {
  input_tokens: number | null;
  cached_input_tokens: number | null;
  output_tokens: number | null;
  reasoning_tokens: number | null;
};

// Server-side reason codes for later telemetry. Never sent to the client.
export type ModelFailureReason =
  | "not_configured" // no API key or model configured
  | "timeout"
  | "network_error"
  | "auth" // 401/403: bad, expired or under-scoped key
  | "rate_limited" // 429: rate limit OR quota/prepaid credit exhausted
  | "bad_request" // 400/404/422: e.g. model not on the project allow-list
  | "upstream_5xx"
  | "upstream_status"
  | "incomplete_max_tokens" // hit the output-token ceiling: output is cut
  | "incomplete_other"
  | "refusal"
  | "empty_output"
  | "malformed_json"
  | "schema_mismatch";

export type ModelResult =
  | {
      ok: true;
      brief: ModelBrief;
      provider: string;
      model: string; // exact model ID the provider reports it served
      usage: ModelUsage;
      llmMs: number;
    }
  | {
      ok: false;
      // provider_unavailable: the call failed or was not made.
      // output_invalid: the call returned, but nothing safe to show.
      kind: "provider_unavailable" | "output_invalid";
      reason: ModelFailureReason;
      // Present when the provider answered; lets a failed call still be counted.
      model: string | null;
      usage: ModelUsage | null;
      llmMs: number;
    };

export interface BriefModel {
  generateBrief(evidence: NormalizedPullRequest): Promise<ModelResult>;
}
