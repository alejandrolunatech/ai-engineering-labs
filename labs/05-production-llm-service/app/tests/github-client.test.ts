import { afterEach, describe, expect, it, vi } from "vitest";
import { createGithubClient, GITHUB_API_VERSION, MAX_REQUESTS, MAX_RESPONSE_BYTES } from "@/lib/github/client";
import { API, json, mockFetch, redirect, status } from "./helpers/github";

const PULL = `${API}/repos/o/r/pulls/1`;

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllEnvs();
});

describe("github client — URL guard", () => {
  it.each([
    "https://github.com/o/r/pull/1",
    "http://api.github.com/repos/o/r/pulls/1",
    "https://api.github.com.evil.example/repos/o/r/pulls/1",
    "https://api.github.com@evil.example/repos",
    "https://API.GITHUB.COM/repos/o/r/pulls/1",
    "https://169.254.169.254/latest/meta-data",
    "http://localhost:3000/",
    "https://api.github.com",
    "",
  ])("refuses %j without calling fetch", async (url) => {
    const spy = mockFetch({});
    const client = createGithubClient();
    expect(await client.getJson(url)).toEqual({ ok: false, reason: "invalid_url" });
    expect(spy).not.toHaveBeenCalled();
    expect(client.stats().requests).toBe(0);
  });
});

describe("github client — request shape", () => {
  it("sends fixed headers, manual redirects and a timeout signal; no token by default", async () => {
    vi.stubEnv("GITHUB_TOKEN", "");
    const spy = mockFetch({ [PULL]: json({ ok: 1 }) });
    const result = await createGithubClient().getJson(PULL);
    expect(result).toEqual({ ok: true, json: { ok: 1 }, servedUrl: PULL });
    const init = spy.mock.calls[0][1]!;
    const headers = new Headers(init.headers);
    expect(headers.get("accept")).toBe("application/vnd.github+json");
    expect(headers.get("user-agent")).toBe("ChangeBrief/0.1");
    expect(headers.get("x-github-api-version")).toBe(GITHUB_API_VERSION);
    expect(GITHUB_API_VERSION).toBe("2026-03-10");
    expect(headers.has("authorization")).toBe(false);
    expect(init.method).toBe("GET");
    expect(init.redirect).toBe("manual");
    expect(init.signal).toBeInstanceOf(AbortSignal);
  });

  it("adds a bearer token only when GITHUB_TOKEN is set", async () => {
    vi.stubEnv("GITHUB_TOKEN", "test-token-not-real");
    const spy = mockFetch({ [PULL]: json({}) });
    await createGithubClient().getJson(PULL);
    expect(new Headers(spy.mock.calls[0][1]!.headers).get("authorization")).toBe("Bearer test-token-not-real");
  });

  it("records x-ratelimit-remaining (digits only)", async () => {
    const other = `${API}/repos/o/r/pulls/2`;
    mockFetch({
      [PULL]: json({}, { headers: { "x-ratelimit-remaining": "41" } }),
      [other]: json({}, { headers: { "x-ratelimit-remaining": "40; drop table" } }),
    });
    const client = createGithubClient();
    await client.getJson(PULL);
    await client.getJson(other);
    expect(client.stats().rateLimitRemaining).toEqual([41, null]);
  });
});

describe("github client — ceilings", () => {
  it(`never makes more than ${MAX_REQUESTS} requests`, async () => {
    const spy = mockFetch({ [PULL]: json({}) });
    const client = createGithubClient();
    for (let i = 0; i < MAX_REQUESTS; i++) expect((await client.getJson(PULL)).ok).toBe(true);
    expect(await client.getJson(PULL)).toEqual({ ok: false, reason: "request_budget_exhausted" });
    expect(spy).toHaveBeenCalledTimes(MAX_REQUESTS);
  });

  it("rejects a declared Content-Length over 2 MB", async () => {
    mockFetch({ [PULL]: json({}, { headers: { "content-length": String(MAX_RESPONSE_BYTES + 1) } }) });
    expect(await createGithubClient().getJson(PULL)).toEqual({ ok: false, reason: "too_large" });
  });

  it("stops reading a streamed response over 2 MB", async () => {
    let pulled = 0;
    const chunk = new Uint8Array(256 * 1024).fill(0x20);
    mockFetch({
      [PULL]: () =>
        new Response(
          new ReadableStream<Uint8Array>({
            pull(controller) {
              pulled += 1;
              if (pulled > 100) controller.close();
              else controller.enqueue(chunk);
            },
          }),
          { status: 200 },
        ),
    });
    expect(await createGithubClient().getJson(PULL)).toEqual({ ok: false, reason: "too_large" });
    expect(pulled).toBeLessThan(12);
  });

  it("maps a timeout to 'timeout'", async () => {
    mockFetch({
      [PULL]: () => {
        throw new DOMException("The operation was aborted due to timeout", "TimeoutError");
      },
    });
    expect(await createGithubClient().getJson(PULL)).toEqual({ ok: false, reason: "timeout" });
  });

  it("maps a timeout during the body read to 'timeout'", async () => {
    mockFetch({
      [PULL]: () =>
        new Response(
          new ReadableStream<Uint8Array>({
            pull(controller) {
              controller.error(new DOMException("timeout", "TimeoutError"));
            },
          }),
          { status: 200 },
        ),
    });
    expect(await createGithubClient().getJson(PULL)).toEqual({ ok: false, reason: "timeout" });
  });

  it("maps other fetch errors to 'network_error'", async () => {
    mockFetch({
      [PULL]: () => {
        throw new TypeError("fetch failed");
      },
    });
    expect(await createGithubClient().getJson(PULL)).toEqual({ ok: false, reason: "network_error" });
  });
});

describe("github client — upstream status mapping", () => {
  it.each([
    [404, {}, "not_found"],
    [401, {}, "unauthorized"],
    [403, { "x-ratelimit-remaining": "0" }, "rate_limited"],
    [403, { "x-ratelimit-remaining": "12" }, "forbidden"],
    [429, {}, "rate_limited"],
    [500, {}, "upstream_5xx"],
    [502, {}, "upstream_5xx"],
    [204, {}, "upstream_status"],
    [304, {}, "upstream_status"],
  ] as const)("%i %j -> %s", async (code, headers, reason) => {
    mockFetch({ [PULL]: status(code, headers, code === 204 || code === 304 ? null : undefined) });
    const result = await createGithubClient().getJson(PULL);
    expect(result).toEqual({ ok: false, reason });
    expect(JSON.stringify(result)).not.toContain("GITHUB-ERROR-TEXT-MARKER");
  });

  it("rejects malformed JSON", async () => {
    mockFetch({ [PULL]: new Response("{not json", { status: 200 }) });
    expect(await createGithubClient().getJson(PULL)).toEqual({ ok: false, reason: "malformed_json" });
  });

  it("rejects invalid UTF-8", async () => {
    mockFetch({ [PULL]: new Response(new Uint8Array([0x22, 0xff, 0x22]), { status: 200 }) });
    expect(await createGithubClient().getJson(PULL)).toEqual({ ok: false, reason: "malformed_json" });
  });
});

describe("github client — redirects", () => {
  const MOVED = `${API}/repositories/123/pulls/1`;

  it.each([301, 302, 307, 308])("follows one %i to api.github.com and counts it", async (code) => {
    const spy = mockFetch({ [PULL]: redirect(MOVED, code), [MOVED]: json({ moved: true }) });
    const client = createGithubClient();
    expect(await client.getJson(PULL)).toEqual({ ok: true, json: { moved: true }, servedUrl: MOVED });
    expect(spy).toHaveBeenCalledTimes(2);
    expect(client.stats()).toMatchObject({ requests: 2, redirects: 1 });
  });

  it.each([
    "https://evil.example/repos/o/r/pulls/1",
    "https://api.github.com.evil.example/x",
    "http://api.github.com/repos/o/r/pulls/1",
    "/repositories/123/pulls/1",
    "//evil.example/x",
  ])("refuses a redirect to %j", async (location) => {
    const spy = mockFetch({ [PULL]: redirect(location) });
    expect(await createGithubClient().getJson(PULL)).toEqual({ ok: false, reason: "bad_redirect" });
    expect(spy).toHaveBeenCalledTimes(1);
  });

  it("refuses a redirect without Location", async () => {
    mockFetch({ [PULL]: new Response(null, { status: 302 }) });
    expect(await createGithubClient().getJson(PULL)).toEqual({ ok: false, reason: "bad_redirect" });
  });

  it("refuses a second redirect in the same request (chain)", async () => {
    const third = `${API}/repositories/456/pulls/1`;
    const spy = mockFetch({ [PULL]: redirect(MOVED), [MOVED]: redirect(third), [third]: json({}) });
    expect(await createGithubClient().getJson(PULL)).toEqual({ ok: false, reason: "bad_redirect" });
    expect(spy).toHaveBeenCalledTimes(2);
  });

  it("refuses a redirect loop", async () => {
    const spy = mockFetch({ [PULL]: redirect(PULL) });
    expect(await createGithubClient().getJson(PULL)).toEqual({ ok: false, reason: "bad_redirect" });
    expect(spy).toHaveBeenCalledTimes(2);
  });

  it("allows only one redirect per client, across requests", async () => {
    const other = `${API}/repos/o/r/pulls/2`;
    const moved2 = `${API}/repositories/123/pulls/2`;
    const spy = mockFetch({ [PULL]: redirect(MOVED), [MOVED]: json({}), [other]: redirect(moved2), [moved2]: json({}) });
    const client = createGithubClient();
    expect((await client.getJson(PULL)).ok).toBe(true);
    expect(await client.getJson(other)).toEqual({ ok: false, reason: "bad_redirect" });
    expect(spy).toHaveBeenCalledTimes(3);
  });
});
