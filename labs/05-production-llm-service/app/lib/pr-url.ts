// Exact GitHub pull-request URL parser.
//
// Deterministic boundary: the raw (trimmed) string is matched against ONE anchored
// pattern before any normalization. `new URL()` is deliberately not used for the
// decision: WHATWG URL parsing normalizes backslashes, dot-segments, default ports,
// IDNA/full-width hosts and trailing dots, which would let a lookalike input be
// "cleaned up" into something that passes.

export type PullRequestRef = {
  owner: string;
  repo: string;
  number: number;
};

export type ParseRejectReason =
  | "too_long"
  | "disallowed_characters"
  | "shape_mismatch"
  | "repo_dot_segment"
  | "number_out_of_range";

export type ParseResult =
  | { ok: true; pr: PullRequestRef }
  | { ok: false; reason: ParseRejectReason };

export const MAX_URL_LENGTH = 2048;
export const MAX_PR_NUMBER = 2147483647;

// Printable ASCII only (0x21-0x7E). Rejects whitespace inside the URL, control
// characters, non-ASCII and full-width characters before the pattern runs.
const PRINTABLE_ASCII = /^[\x21-\x7E]+$/;

const PR_URL_PATTERN = new RegExp(
  "^https://" +
    // Host: exactly github.com, any letter case (hostnames are case-insensitive).
    // No port, no credentials, no subdomain, no trailing dot.
    "[Gg][Ii][Tt][Hh][Uu][Bb]\\.[Cc][Oo][Mm]" +
    // Owner: 1-39 letters/digits/hyphens, no leading or trailing hyphen.
    "/([A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?)" +
    // Repo: 1-100 letters/digits/./_/-. "." and ".." are rejected after the match.
    "/([A-Za-z0-9._-]{1,100})" +
    // PR number: positive, no leading zeros, at most 10 digits (range checked after).
    "/pull/([1-9][0-9]{0,9})" +
    // Accepted and discarded: one PR tab, trailing slash, query string, fragment.
    "(?:/(?:files|commits|checks))?/?(?:\\?[^#]*)?(?:#.*)?$",
);

export function parsePrUrl(input: string): ParseResult {
  const candidate = input.trim();

  if (candidate.length === 0 || candidate.length > MAX_URL_LENGTH) {
    return { ok: false, reason: "too_long" };
  }
  if (!PRINTABLE_ASCII.test(candidate) || candidate.includes("\\")) {
    return { ok: false, reason: "disallowed_characters" };
  }

  const match = PR_URL_PATTERN.exec(candidate);
  if (!match) {
    return { ok: false, reason: "shape_mismatch" };
  }

  const [, owner, repo, numberText] = match;
  if (repo === "." || repo === "..") {
    return { ok: false, reason: "repo_dot_segment" };
  }

  const number = Number(numberText);
  if (!Number.isSafeInteger(number) || number < 1 || number > MAX_PR_NUMBER) {
    return { ok: false, reason: "number_out_of_range" };
  }

  // The host is not returned: the only accepted host is github.com, so it is
  // normalized to lowercase by construction. Owner/repo case is preserved.
  return { ok: true, pr: { owner, repo, number } };
}

// The server builds the GitHub API URL itself from validated parts. The
// user-supplied URL is never fetched.
export function buildPullApiUrl(pr: PullRequestRef): string {
  return (
    "https://api.github.com/repos/" +
    `${encodeURIComponent(pr.owner)}/${encodeURIComponent(pr.repo)}` +
    `/pulls/${encodeURIComponent(String(pr.number))}`
  );
}
