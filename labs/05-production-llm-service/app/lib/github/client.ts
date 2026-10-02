import "server-only";
import { declaredLengthExceeds, readStreamWithLimit } from "@/lib/http/read-body";
import { GITHUB_API_ORIGIN } from "@/lib/github/endpoints";

// The ONLY module in the app allowed to call fetch (enforced by
// tests/source-guards.test.ts). Every limit here is a deterministic code
// boundary (PRODUCT-CONTRACT.md §5); none depends on prompt text.
//
// - refuses any URL that does not start with https://api.github.com/
// - at most MAX_REQUESTS fetches per client; one client per analysis
// - at most one redirect per client, and only to https://api.github.com/
// - 10 s timeout per request (covers the body read), 2 MB per response
// - non-200 bodies are discarded unread: GitHub error text never travels on

export const MAX_REQUESTS = 3;
export const MAX_REDIRECTS = 1;
export const REQUEST_TIMEOUT_MS = 10_000;
export const MAX_RESPONSE_BYTES = 2 * 1024 * 1024;
export const GITHUB_API_VERSION = "2026-03-10";
const USER_AGENT = "ChangeBrief/0.1";

// Server-side reason codes for later telemetry. Never sent to the client.
export type GithubFailureReason =
  | "invalid_url"
  | "request_budget_exhausted"
  | "not_found"
  | "unauthorized"
  | "forbidden"
  | "rate_limited"
  | "upstream_5xx"
  | "upstream_status"
  | "bad_redirect"
  | "timeout"
  | "network_error"
  | "too_large"
  | "malformed_json";

export type GithubResult =
  | { ok: true; json: unknown; servedUrl: string }
  | { ok: false; reason: GithubFailureReason };

export type GithubStats = {
  requests: number;
  redirects: number;
  // x-ratelimit-remaining from each response, in order. Digits only; anything
  // else is recorded as null.
  rateLimitRemaining: (number | null)[];
};

export type GithubClient = {
  getJson(url: string): Promise<GithubResult>;
  stats(): GithubStats;
};

const REDIRECT_STATUSES = new Set([301, 302, 307, 308]);

function isGithubApiUrl(url: string): boolean {
  return url.startsWith(GITHUB_API_ORIGIN);
}

function buildHeaders(): Headers {
  const headers = new Headers({
    Accept: "application/vnd.github+json",
    "User-Agent": USER_AGENT,
    "X-GitHub-Api-Version": GITHUB_API_VERSION,
  });
  // Optional fine-grained token (public repositories, read-only, no
  // permissions). Read here only; never logged, returned or stored.
  const token = process.env.GITHUB_TOKEN;
  if (token !== undefined && token.trim() !== "") {
    headers.set("Authorization", `Bearer ${token.trim()}`);
  }
  return headers;
}

function failureForStatus(response: Response): GithubFailureReason {
  const { status } = response;
  if (status === 404) return "not_found";
  if (status === 401) return "unauthorized";
  if (status === 429) return "rate_limited";
  if (status === 403) {
    return response.headers.get("x-ratelimit-remaining") === "0" ? "rate_limited" : "forbidden";
  }
  if (status >= 500) return "upstream_5xx";
  return "upstream_status";
}

function isTimeout(error: unknown): boolean {
  return error instanceof Error && (error.name === "TimeoutError" || error.name === "AbortError");
}

export function createGithubClient(): GithubClient {
  const stats: GithubStats = { requests: 0, redirects: 0, rateLimitRemaining: [] };

  async function send(url: string): Promise<Response | GithubFailureReason> {
    if (!isGithubApiUrl(url)) return "invalid_url";
    if (stats.requests >= MAX_REQUESTS) return "request_budget_exhausted";
    stats.requests += 1;
    try {
      const response = await fetch(url, {
        method: "GET",
        headers: buildHeaders(),
        redirect: "manual",
        signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
      });
      const remaining = response.headers.get("x-ratelimit-remaining");
      stats.rateLimitRemaining.push(remaining !== null && /^\d+$/.test(remaining) ? Number(remaining) : null);
      return response;
    } catch (error) {
      return isTimeout(error) ? "timeout" : "network_error";
    }
  }

  function discard(response: Response): void {
    response.body?.cancel().catch(() => {});
  }

  async function getJson(url: string): Promise<GithubResult> {
    let currentUrl = url;
    let response = await send(currentUrl);
    if (typeof response === "string") return { ok: false, reason: response };

    if (REDIRECT_STATUSES.has(response.status)) {
      const location = response.headers.get("location");
      discard(response);
      if (stats.redirects >= MAX_REDIRECTS || location === null || !isGithubApiUrl(location)) {
        return { ok: false, reason: "bad_redirect" };
      }
      stats.redirects += 1;
      currentUrl = location;
      response = await send(currentUrl);
      if (typeof response === "string") return { ok: false, reason: response };
      if (REDIRECT_STATUSES.has(response.status)) {
        discard(response);
        return { ok: false, reason: "bad_redirect" };
      }
    }

    if (response.status !== 200) {
      discard(response);
      return { ok: false, reason: failureForStatus(response) };
    }

    if (declaredLengthExceeds(response.headers, MAX_RESPONSE_BYTES)) {
      discard(response);
      return { ok: false, reason: "too_large" };
    }

    let bytes: Uint8Array;
    try {
      const read = await readStreamWithLimit(response.body, MAX_RESPONSE_BYTES);
      if (!read.ok) return { ok: false, reason: "too_large" };
      bytes = read.bytes;
    } catch (error) {
      return { ok: false, reason: isTimeout(error) ? "timeout" : "network_error" };
    }

    try {
      const text = new TextDecoder("utf-8", { fatal: true }).decode(bytes);
      return { ok: true, json: JSON.parse(text), servedUrl: currentUrl };
    } catch {
      return { ok: false, reason: "malformed_json" };
    }
  }

  return {
    getJson,
    stats: () => ({ ...stats, rateLimitRemaining: [...stats.rateLimitRemaining] }),
  };
}
