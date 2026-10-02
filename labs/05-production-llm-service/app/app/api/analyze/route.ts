import { getConfig } from "@/lib/config";
import { errorResponse } from "@/lib/http/errors";
import { readBodyWithLimit } from "@/lib/http/read-body";
import { ingestPullRequest } from "@/lib/github/ingest";
import { parsePrUrl } from "@/lib/pr-url";
import { AnalyzeRequestSchema } from "@/lib/schemas/analyze";
import type { NormalizedResponse } from "@/lib/schemas/normalized-pr";

// POST /api/analyze — Phase 2: validate, parse, then fetch and normalize the
// public PR from GitHub. No LLM call.
//
// Check order (each step is deterministic and runs before any later one):
//   method -> content type -> capped body read -> JSON -> request shape -> PR URL
//   -> GitHub ingestion (the first and only external call).

function isJsonContentType(header: string | null): boolean {
  if (header === null) return false;
  const mediaType = header.split(";", 1)[0].trim().toLowerCase();
  return mediaType === "application/json";
}

export async function POST(request: Request): Promise<Response> {
  try {
    const configResult = getConfig();
    if (!configResult.ok) {
      return errorResponse("internal_error", 500);
    }
    const { config } = configResult;

    if (!isJsonContentType(request.headers.get("content-type"))) {
      return errorResponse("invalid_pr_url", 415);
    }

    const body = await readBodyWithLimit(request, config.maxRequestBodyBytes);
    if (!body.ok) {
      return body.reason === "too_large"
        ? errorResponse("request_too_large", 413)
        : errorResponse("invalid_pr_url", 400);
    }

    let json: unknown;
    try {
      json = JSON.parse(body.text);
    } catch {
      return errorResponse("invalid_pr_url", 400);
    }

    const shape = AnalyzeRequestSchema.safeParse(json);
    if (!shape.success) {
      return errorResponse("invalid_pr_url", 400);
    }

    const parsed = parsePrUrl(shape.data.url);
    if (!parsed.ok) {
      return errorResponse("invalid_pr_url", 400);
    }

    const ingest = await ingestPullRequest(parsed.pr);
    if (!ingest.ok) {
      // ingest.reason is a server-side code kept for later telemetry. It is not
      // logged yet and never sent: no GitHub error text reaches the client.
      return ingest.kind === "not_found"
        ? errorResponse("pr_not_found", 404)
        : errorResponse("pr_not_found", 503);
    }

    // DEVELOPMENT OUTPUT, replaced in Phase 3: the browser gets the normalized
    // evidence so it can be inspected. Phase 3 sends it to the model instead.
    const response: NormalizedResponse = { status: "normalized", evidence: ingest.evidence };
    return Response.json(response, { status: 200, headers: { "Cache-Control": "no-store" } });
  } catch {
    // Never echo the exception: it could contain request content.
    return errorResponse("internal_error", 500);
  }
}

// Explicit handlers so other methods get the same safe error shape instead of
// the framework default. HEAD and OPTIONS are left to Next.js.
function methodNotAllowed(): Response {
  return errorResponse("invalid_pr_url", 405, { Allow: "POST" });
}

export const GET = methodNotAllowed;
export const PUT = methodNotAllowed;
export const PATCH = methodNotAllowed;
export const DELETE = methodNotAllowed;
