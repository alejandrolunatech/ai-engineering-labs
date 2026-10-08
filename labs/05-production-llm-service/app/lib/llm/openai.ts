import "server-only";
import { z } from "zod";
import {
  APIConnectionError,
  APIConnectionTimeoutError,
  APIError,
  OpenAI,
} from "openai";
import { INSTRUCTIONS, buildInput } from "@/lib/llm/prompt";
import type { BriefModel, ModelFailureReason, ModelResult, ModelUsage } from "@/lib/llm/types";
import { ModelBriefSchema } from "@/lib/schemas/change-brief";
import type { NormalizedPullRequest } from "@/lib/schemas/normalized-pr";

// The ONLY module that imports the OpenAI SDK (enforced by
// tests/source-guards.test.ts). OpenAI objects never leave this file.
//
// Every limit below is a deterministic code boundary (PRODUCT-CONTRACT.md §5):
// - exactly one request per generateBrief call; SDK retries are OFF
// - 30 s provider timeout
// - 1,500 output tokens, reasoning tokens included
// - no tools; store: false so OpenAI does not keep the response for later
// - the reply is parsed and schema-validated here before anything uses it

export const MAX_OUTPUT_TOKENS = 1_500;
export const LLM_TIMEOUT_MS = 30_000;
export const LLM_MAX_RETRIES = 0;

// Strict JSON Schema for the provider's structured-output mode, generated from
// the same Zod schema that validates the reply. The provider constraint is a
// convenience; the Zod check below is the boundary.
export const MODEL_BRIEF_JSON_SCHEMA: Record<string, unknown> = z.toJSONSchema(ModelBriefSchema) as Record<string, unknown>;
delete MODEL_BRIEF_JSON_SCHEMA.$schema;

// The slice of the SDK this adapter uses, so tests can pass a fake client.
type CreateParams = Parameters<OpenAI["responses"]["create"]>[0];
type CreateOptions = { timeout?: number; maxRetries?: number };
export type ResponsesClient = {
  responses: { create(params: CreateParams, options?: CreateOptions): Promise<unknown> };
};

export type OpenAIBriefModelOptions = {
  apiKey: string;
  model: string;
  reasoningEffort: "none" | "low" | "medium" | "high";
  // Tests inject a fake. Production builds the real SDK client.
  client?: ResponsesClient;
};

// Loose view of the fields read from a Responses API reply. Everything is
// optional because the reply is checked, not trusted.
type ResponseView = {
  model?: unknown;
  status?: unknown;
  incomplete_details?: { reason?: unknown } | null;
  output_text?: unknown;
  output?: unknown;
  usage?: {
    input_tokens?: unknown;
    output_tokens?: unknown;
    input_tokens_details?: { cached_tokens?: unknown } | null;
    output_tokens_details?: { reasoning_tokens?: unknown } | null;
  } | null;
};

function count(value: unknown): number | null {
  return typeof value === "number" && Number.isInteger(value) && value >= 0 ? value : null;
}

function readUsage(r: ResponseView): ModelUsage | null {
  if (r.usage === null || typeof r.usage !== "object") return null;
  return {
    input_tokens: count(r.usage.input_tokens),
    cached_input_tokens: count(r.usage.input_tokens_details?.cached_tokens),
    output_tokens: count(r.usage.output_tokens),
    reasoning_tokens: count(r.usage.output_tokens_details?.reasoning_tokens),
  };
}

function hasRefusal(output: unknown): boolean {
  if (!Array.isArray(output)) return false;
  return output.some(
    (item) =>
      item !== null &&
      typeof item === "object" &&
      Array.isArray((item as { content?: unknown }).content) &&
      (item as { content: unknown[] }).content.some(
        (c) => c !== null && typeof c === "object" && (c as { type?: unknown }).type === "refusal",
      ),
  );
}

function errorReason(error: unknown): ModelFailureReason {
  // Order matters: the timeout error is a subclass of the connection error,
  // which is a subclass of APIError.
  if (error instanceof APIConnectionTimeoutError) return "timeout";
  if (error instanceof APIConnectionError) return "network_error";
  if (error instanceof APIError) {
    const status = error.status ?? 0;
    if (status === 401 || status === 403) return "auth";
    if (status === 429) return "rate_limited";
    if (status === 400 || status === 404 || status === 422) return "bad_request";
    if (status >= 500) return "upstream_5xx";
    return "upstream_status";
  }
  // AbortError from the timeout signal, or anything unexpected from the SDK.
  if (error instanceof Error && error.name === "AbortError") return "timeout";
  return "network_error";
}

export function createOpenAIBriefModel(options: OpenAIBriefModelOptions): BriefModel {
  const client: ResponsesClient =
    options.client ??
    new OpenAI({ apiKey: options.apiKey, maxRetries: LLM_MAX_RETRIES, timeout: LLM_TIMEOUT_MS });

  return {
    async generateBrief(evidence: NormalizedPullRequest): Promise<ModelResult> {
      const started = performance.now();
      const elapsed = () => Math.round(performance.now() - started);

      let raw: unknown;
      try {
        raw = await client.responses.create(
          {
            model: options.model,
            instructions: INSTRUCTIONS,
            input: buildInput(evidence),
            max_output_tokens: MAX_OUTPUT_TOKENS,
            reasoning: { effort: options.reasoningEffort },
            store: false,
            text: {
              format: {
                type: "json_schema",
                name: "change_brief",
                strict: true,
                schema: MODEL_BRIEF_JSON_SCHEMA,
              },
            },
          },
          // Per-request options repeat the client settings so an injected
          // client cannot silently loosen them.
          { timeout: LLM_TIMEOUT_MS, maxRetries: LLM_MAX_RETRIES },
        );
      } catch (error) {
        // Provider error text is never passed on: it can echo request content.
        return {
          ok: false,
          kind: "provider_unavailable",
          reason: errorReason(error),
          model: null,
          usage: null,
          llmMs: elapsed(),
        };
      }

      const llmMs = elapsed();
      const r = (raw ?? {}) as ResponseView;
      const model = typeof r.model === "string" ? r.model : null;
      const usage = readUsage(r);
      const fail = (reason: ModelFailureReason): ModelResult => ({
        ok: false,
        kind: "output_invalid",
        reason,
        model,
        usage,
        llmMs,
      });

      if (r.status === "incomplete") {
        return fail(r.incomplete_details?.reason === "max_output_tokens" ? "incomplete_max_tokens" : "incomplete_other");
      }
      if (hasRefusal(r.output)) return fail("refusal");
      if (typeof r.output_text !== "string" || r.output_text.trim() === "") return fail("empty_output");

      let json: unknown;
      try {
        json = JSON.parse(r.output_text);
      } catch {
        return fail("malformed_json");
      }
      const brief = ModelBriefSchema.safeParse(json);
      if (!brief.success) return fail("schema_mismatch");

      return {
        ok: true,
        brief: brief.data,
        provider: "openai",
        model: model ?? options.model,
        usage: usage ?? { input_tokens: null, cached_input_tokens: null, output_tokens: null, reasoning_tokens: null },
        llmMs,
      };
    },
  };
}
