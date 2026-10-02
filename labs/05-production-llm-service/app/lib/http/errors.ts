// User-facing failure categories (ARCHITECTURE.md "Failure semantics").
//
// Phase 1 only emits invalid_pr_url, request_too_large and internal_error. The
// others are declared so later phases reuse the same small, fixed set.
// Messages are fixed strings: no request content or internal detail is echoed.

export const ERROR_CATEGORIES = {
  invalid_pr_url:
    "Send a POST request with a JSON body {\"url\": \"https://github.com/<owner>/<repo>/pull/<number>\"}.",
  pr_not_found: "That public pull request was not found or is unavailable.",
  request_too_large: "The request is too large.",
  rate_limited: "Too many requests. Try again later.",
  provider_unavailable: "The model provider is temporarily unavailable.",
  output_invalid: "The model returned an invalid result.",
  service_disabled: "The service is temporarily disabled.",
  internal_error: "Internal error.",
} as const;

export type ErrorCategory = keyof typeof ERROR_CATEGORIES;

export type ErrorBody = {
  status: "error";
  error: { category: ErrorCategory; message: string };
};

export function errorResponse(
  category: ErrorCategory,
  httpStatus: number,
  headers?: HeadersInit,
): Response {
  const body: ErrorBody = {
    status: "error",
    error: { category, message: ERROR_CATEGORIES[category] },
  };
  return Response.json(body, { status: httpStatus, headers });
}
