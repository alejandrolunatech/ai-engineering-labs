import { getConfig } from "@/lib/config";
import { errorResponse, type ErrorCategory } from "@/lib/http/errors";
import { readBodyWithLimit } from "@/lib/http/read-body";
import { ingestPullRequest } from "@/lib/github/ingest";
import { getBriefModel } from "@/lib/llm";
import { PROMPT_VERSION } from "@/lib/llm/prompt";
import { parsePrUrl } from "@/lib/pr-url";
import { estimateCost } from "@/lib/pricing";
import { checkRateLimit, clientKey, storeFor } from "@/lib/rate-limit";
import { AnalyzeRequestSchema } from "@/lib/schemas/analyze";
import { ChangeBriefSchema, SCHEMA_VERSION, type BriefResponse } from "@/lib/schemas/change-brief";
import {
  emitAnalysisEvent,
  safeModelId,
  usageStatus,
  type AnalysisEvent,
  type FailureReason,
} from "@/lib/telemetry";

// POST /api/analyze — validate, parse, fetch and normalize the public PR from
// GitHub, then make ONE model call and return a validated ChangeBrief.
//
// Check order (each step is deterministic and runs before any later one):
//   method -> kill switch -> content type -> capped body read -> JSON
//   -> request shape -> PR URL -> model configured? -> rate limits
//   -> GitHub ingestion -> one model call -> validation.
// The GitHub and model calls are the paid external calls; the rate-limit store
// is the only call before them. No retries.
//
// Phase 6: the kill switch and the rate limits sit in front of all paid work.
// A refused request makes zero GitHub and zero model calls
// (tests/abuse-controls.test.ts proves it for every refusal).
//
// Phase 5: every request, success or failure, writes exactly one telemetry
// event (lib/telemetry.ts). The event holds counts, durations and fixed codes
// only; nothing from the PR, the prompt or the model's text.

function isJsonContentType(header: string | null): boolean {
  if (header === null) return false;
  const mediaType = header.split(";", 1)[0].trim().toLowerCase();
  return mediaType === "application/json";
}

type Stage = NonNullable<AnalysisEvent["failure_stage"]>;

function newEvent(): AnalysisEvent {
  return {
    event: "analysis",
    outcome: "internal_error",
    http_status: 500,
    failure_stage: null,
    reason: null,
    provider: null,
    model: null,
    reasoning_effort: null,
    schema_version: SCHEMA_VERSION,
    prompt_version: PROMPT_VERSION,
    total_ms: 0,
    github_ms: null,
    normalization_ms: null,
    llm_ms: null,
    validation_ms: null,
    github_requests: null,
    github_redirects: null,
    github_rate_limit_remaining: null,
    files_considered: null,
    files_total: null,
    evidence_chars: null,
    truncated: null,
    input_tokens: null,
    cached_input_tokens: null,
    output_tokens: null,
    reasoning_tokens: null,
    usage_status: "unknown",
    estimated_cost_usd: null,
    cost_status: "unknown",
    pricing_as_of: null,
    schema_valid: null,
  };
}

export async function POST(request: Request): Promise<Response> {
  const started = performance.now();
  const elapsed = () => Math.round(performance.now() - started);
  const event = newEvent();

  const fail = (
    category: ErrorCategory,
    httpStatus: number,
    stage: Stage,
    reason: FailureReason,
    headers?: HeadersInit,
  ): Response => {
    Object.assign(event, { outcome: category, http_status: httpStatus, failure_stage: stage, reason });
    return errorResponse(category, httpStatus, headers);
  };

  try {
    const configResult = getConfig();
    if (!configResult.ok) {
      return fail("internal_error", 500, "request", "config_invalid");
    }
    const { config } = configResult;
    if (config.llm.status === "configured") {
      Object.assign(event, {
        provider: config.llm.provider,
        model: config.llm.model,
        reasoning_effort: config.llm.reasoningEffort,
      });
    }

    // Kill switch: first, so a disabled service reads no body and calls nothing.
    if (!config.serviceEnabled) {
      return fail("service_disabled", 503, "request", "service_disabled", { "Retry-After": "300" });
    }

    if (!isJsonContentType(request.headers.get("content-type"))) {
      return fail("invalid_pr_url", 415, "request", "bad_content_type");
    }

    const body = await readBodyWithLimit(request, config.maxRequestBodyBytes);
    if (!body.ok) {
      return body.reason === "too_large"
        ? fail("request_too_large", 413, "request", "body_too_large")
        : fail("invalid_pr_url", 400, "request", "body_unreadable");
    }

    let json: unknown;
    try {
      json = JSON.parse(body.text);
    } catch {
      return fail("invalid_pr_url", 400, "request", "bad_json");
    }

    const shape = AnalyzeRequestSchema.safeParse(json);
    if (!shape.success) {
      return fail("invalid_pr_url", 400, "request", "bad_request_shape");
    }

    const parsed = parsePrUrl(shape.data.url);
    if (!parsed.ok) {
      return fail("invalid_pr_url", 400, "request", "bad_pr_url");
    }

    // Fail closed before spending GitHub quota when no model is configured.
    const model = getBriefModel(config.llm);
    if (model === null) {
      return fail("provider_unavailable", 503, "request", "model_not_configured");
    }

    // Rate limits: the last check before paid work, so malformed requests
    // never touch the store. Any store problem is a refusal (fail closed).
    const store = storeFor(config.rateLimit);
    if (store === null) {
      return fail("service_disabled", 503, "request", "rate_limiter_not_configured");
    }
    const limit = await checkRateLimit(clientKey(request.headers, config.onVercel), config.rateLimit.limits, store);
    if (!limit.ok) {
      return limit.reason === "rate_limiter_unavailable"
        ? fail("service_disabled", 503, "request", limit.reason)
        : fail("rate_limited", 429, "request", limit.reason, { "Retry-After": String(limit.retryAfterSec) });
    }

    const ingest = await ingestPullRequest(parsed.pr);
    const remaining = ingest.stats.rateLimitRemaining.filter((v): v is number => v !== null);
    Object.assign(event, {
      github_ms: ingest.timings.githubMs,
      normalization_ms: ingest.timings.normalizationMs,
      github_requests: ingest.stats.requests,
      github_redirects: ingest.stats.redirects,
      github_rate_limit_remaining: remaining.length === 0 ? null : remaining[remaining.length - 1],
    });
    if (!ingest.ok) {
      // ingest.reason goes to telemetry only: no GitHub error text reaches the client.
      return ingest.kind === "not_found"
        ? fail("pr_not_found", 404, "github", ingest.reason)
        : fail("pr_not_found", 503, "github", ingest.reason);
    }

    const evidence = ingest.evidence;
    Object.assign(event, {
      files_considered: evidence.coverage.files_considered,
      files_total: evidence.coverage.files_total,
      evidence_chars: evidence.coverage.chars_included,
      truncated: evidence.truncated,
    });

    const result = await model.generateBrief(evidence);
    const servedModel = safeModelId(result.model);
    const cost = estimateCost(result.usage, servedModel);
    Object.assign(event, {
      model: servedModel ?? event.model,
      llm_ms: result.llmMs,
      validation_ms: result.validationMs,
      input_tokens: result.usage?.input_tokens ?? null,
      cached_input_tokens: result.usage?.cached_input_tokens ?? null,
      output_tokens: result.usage?.output_tokens ?? null,
      reasoning_tokens: result.usage?.reasoning_tokens ?? null,
      usage_status: usageStatus(result.usage),
      // A failed call that still reported usage was still paid for: count it.
      estimated_cost_usd: cost?.usd ?? null,
      cost_status: cost === null ? "unknown" : "estimated",
      pricing_as_of: cost?.pricing_as_of ?? null,
    });
    if (!result.ok) {
      if (result.kind === "output_invalid") {
        event.schema_valid = false;
        return fail("output_invalid", 502, "model", result.reason);
      }
      return fail("provider_unavailable", 503, "model", result.reason);
    }

    // Server-written fields come from code, never from the model
    // (PRODUCT-CONTRACT.md §3b). Truncation is reported whatever the model says.
    const validationStarted = performance.now();
    const brief = ChangeBriefSchema.safeParse({
      pr: evidence.pr,
      truncated: evidence.truncated,
      truncation_limitations: evidence.limitations,
      files_considered: evidence.coverage.files_considered,
      files_total: evidence.coverage.files_total,
      schema_version: SCHEMA_VERSION,
      prompt_version: PROMPT_VERSION,
      model: result.model,
      usage: result.usage,
      estimated_cost: cost,
      ai_generated: true,
      brief: result.brief,
    });
    event.validation_ms = result.validationMs + Math.round(performance.now() - validationStarted);
    event.schema_valid = brief.success;
    if (!brief.success) {
      return fail("output_invalid", 502, "model", "server_fields_invalid");
    }

    const response: BriefResponse = {
      status: "brief",
      brief: brief.data,
      timing: { total_ms: elapsed(), github_ms: ingest.timings.githubMs, llm_ms: result.llmMs },
    };
    Object.assign(event, { outcome: "success", http_status: 200 });
    return Response.json(response, { status: 200, headers: { "Cache-Control": "no-store" } });
  } catch {
    // Never echo or log the exception: it could contain request content.
    return fail("internal_error", 500, "request", "unexpected_exception");
  } finally {
    event.total_ms = elapsed();
    emitAnalysisEvent(event);
  }
}

// Explicit handlers so other methods get the same safe error shape instead of
// the framework default. HEAD and OPTIONS are left to Next.js. Not analysis
// requests, so no telemetry event.
function methodNotAllowed(): Response {
  return errorResponse("invalid_pr_url", 405, { Allow: "POST" });
}

export const GET = methodNotAllowed;
export const PUT = methodNotAllowed;
export const PATCH = methodNotAllowed;
export const DELETE = methodNotAllowed;
