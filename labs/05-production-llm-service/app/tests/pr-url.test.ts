import { describe, expect, it } from "vitest";
import { buildPullApiUrl, parsePrUrl, type PullRequestRef } from "@/lib/pr-url";

type Case = { input: string; expected: PullRequestRef | null };

const NEXT = { owner: "vercel", repo: "next.js", number: 12345 };

// The 20 required cases. `null` means rejected.
const REQUIRED: Case[] = [
  { input: "https://github.com/vercel/next.js/pull/12345", expected: NEXT },
  { input: "http://github.com/vercel/next.js/pull/12345", expected: null },
  { input: "https://www.github.com/vercel/next.js/pull/12345", expected: null },
  { input: "https://github.com:443/vercel/next.js/pull/12345", expected: null },
  { input: "https://user:pass@github.com/vercel/next.js/pull/12345", expected: null },
  { input: "https://github.com@evil.com/vercel/next.js/pull/12345", expected: null },
  { input: "https://github.com.evil.com/vercel/next.js/pull/12345", expected: null },
  { input: "https://GitHub.com/vercel/next.js/pull/12345", expected: NEXT },
  { input: "https://github.com/vercel/next.js/pull/12345/files", expected: NEXT },
  { input: "https://github.com/vercel/next.js/pull/12345#issuecomment-1", expected: NEXT },
  { input: "https://github.com/vercel/next.js/pull/0", expected: null },
  { input: "https://github.com/vercel/next.js/pull/0012", expected: null },
  { input: "https://github.com/vercel/next.js/pull/99999999999999999999", expected: null },
  { input: "https://github.com/vercel/next.js/issues/12345", expected: null },
  { input: "https://github.com/-bad/repo/pull/1", expected: null },
  { input: "https://github.com/owner/../pull/1", expected: null },
  { input: "https://github.com/o/r/pull/1/../../x/y/pull/2", expected: null },
  { input: "http://localhost:3000/o/r/pull/1", expected: null },
  { input: "https://169.254.169.254/o/r/pull/1", expected: null },
  { input: "   https://github.com/o/r/pull/1   ", expected: { owner: "o", repo: "r", number: 1 } },
];

const OWNER_39 = "a".repeat(39);
const REPO_100 = "r".repeat(100);

const EXTRA: Case[] = [
  // Accept-and-discard suffixes
  { input: "https://github.com/o/r/pull/1/", expected: { owner: "o", repo: "r", number: 1 } },
  { input: "https://github.com/o/r/pull/1?x=1", expected: { owner: "o", repo: "r", number: 1 } },
  { input: "https://github.com/o/r/pull/1/commits", expected: { owner: "o", repo: "r", number: 1 } },
  { input: "https://github.com/o/r/pull/1/checks/", expected: { owner: "o", repo: "r", number: 1 } },
  { input: "https://github.com/o/r/pull/1/files?diff=split#top", expected: { owner: "o", repo: "r", number: 1 } },
  // Case: host normalized, owner/repo case preserved
  { input: "https://GITHUB.COM/Vercel/Next.js/pull/7", expected: { owner: "Vercel", repo: "Next.js", number: 7 } },
  // Component limits
  { input: `https://github.com/${OWNER_39}/r/pull/1`, expected: { owner: OWNER_39, repo: "r", number: 1 } },
  { input: `https://github.com/${OWNER_39}a/r/pull/1`, expected: null },
  { input: "https://github.com/bad-/r/pull/1", expected: null },
  { input: "https://github.com/a-b/r/pull/1", expected: { owner: "a-b", repo: "r", number: 1 } },
  { input: "https://github.com/o_x/r/pull/1", expected: null },
  { input: `https://github.com/o/${REPO_100}/pull/1`, expected: { owner: "o", repo: REPO_100, number: 1 } },
  { input: `https://github.com/o/${REPO_100}r/pull/1`, expected: null },
  { input: "https://github.com/o/.../pull/1", expected: { owner: "o", repo: "...", number: 1 } },
  { input: "https://github.com/o/./pull/1", expected: null },
  { input: "https://github.com/o/r/pull/2147483647", expected: { owner: "o", repo: "r", number: 2147483647 } },
  { input: "https://github.com/o/r/pull/2147483648", expected: null },
  { input: "https://github.com/o/r/pull/-1", expected: null },
  { input: "https://github.com/o/r/pull/1e3", expected: null },
  // Other suffixes / shapes
  { input: "https://github.com/o/r/pull/1/foo", expected: null },
  { input: "https://github.com/o/r/pull/1/files/x", expected: null },
  { input: "https://github.com/o/r/pull/1//", expected: null },
  { input: "https://github.com/o/r/pulls/1", expected: null },
  { input: "https://github.com//o/r/pull/1", expected: null },
  { input: "https://github.com/o/r/pull/1/%2e%2e", expected: null },
  { input: "https://github.com/o%2Fx/r/pull/1", expected: null },
  // Scheme / host tricks
  { input: "HTTPS://github.com/o/r/pull/1", expected: null },
  { input: "https:/github.com/o/r/pull/1", expected: null },
  { input: "//github.com/o/r/pull/1", expected: null },
  { input: "github.com/o/r/pull/1", expected: null },
  { input: "https://github.com./o/r/pull/1", expected: null },
  { input: "https://github.com:/o/r/pull/1", expected: null },
  { input: "https://@github.com/o/r/pull/1", expected: null },
  { input: "https://api.github.com/o/r/pull/1", expected: null },
  { input: "https://ｇithub.com/o/r/pull/1", expected: null },
  { input: "https://github.com\\@evil.com/o/r/pull/1", expected: null },
  { input: "https:\\\\github.com\\o\\r\\pull\\1", expected: null },
  { input: "https://githüb.com/o/r/pull/1", expected: null },
  { input: "javascript:alert(1)//github.com/o/r/pull/1", expected: null },
  // Whitespace / control characters inside
  { input: "https://github.com/o/r/pull/1 x", expected: null },
  { input: "https://github.com/o/r/pull/1\n", expected: { owner: "o", repo: "r", number: 1 } },
  { input: "https://github.com/o/r\t/pull/1", expected: null },
  { input: "https://github.com/o/r/pull/1\u0000", expected: null },
  { input: "", expected: null },
  { input: "   ", expected: null },
  { input: "https://github.com/o/r/pull/1?" + "a".repeat(2048), expected: null },
];

describe("parsePrUrl — required 20 cases", () => {
  it.each(REQUIRED.map((c, i) => ({ n: i + 1, ...c })))(
    "#$n $input",
    ({ input, expected }) => {
      const result = parsePrUrl(input);
      if (expected === null) {
        expect(result.ok).toBe(false);
      } else {
        expect(result).toEqual({ ok: true, pr: expected });
      }
    },
  );
});

describe("parsePrUrl — additional edges", () => {
  it.each(EXTRA)("$input", ({ input, expected }) => {
    const result = parsePrUrl(input);
    if (expected === null) {
      expect(result.ok).toBe(false);
    } else {
      expect(result).toEqual({ ok: true, pr: expected });
    }
  });
});

describe("buildPullApiUrl", () => {
  it("builds the api.github.com pulls endpoint from validated parts", () => {
    expect(buildPullApiUrl(NEXT)).toBe("https://api.github.com/repos/vercel/next.js/pulls/12345");
  });

  it("percent-encodes each part (defense in depth; parser never yields these)", () => {
    expect(buildPullApiUrl({ owner: "a/b", repo: "c?d#e", number: 1 })).toBe(
      "https://api.github.com/repos/a%2Fb/c%3Fd%23e/pulls/1",
    );
  });
});
