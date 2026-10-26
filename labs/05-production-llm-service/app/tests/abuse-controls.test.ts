import { afterEach, beforeEach, describe, expect, it, vi, type MockInstance } from "vitest";
import nextConfig, { CONTENT_SECURITY_POLICY } from "@/next.config";
import { POST } from "@/app/api/analyze/route";
import { GET as health } from "@/app/api/health/route";
import { getBriefModel } from "@/lib/llm";
import { checkRateLimit, clientKey, memoryStore, rateLimitSubject, upstashStore } from "@/lib/rate-limit";
import { AnalysisEventSchema } from "@/lib/telemetry";
import { API, fetchFrom, filesFor, fixture, json } from "./helpers/github";
import { fakeModel, type FakeModel } from "./helpers/llm";

// Phase 6: kill switch, rate limits and security headers. Mocked GitHub, a
// fake Upstash, a fake model: no network, no API money.
//
// The rule every refusal here must prove: zero GitHub calls and zero model calls.

vi.mock("@/lib/llm", () => ({ getBriefModel: vi.fn() }));

const PR_URL = "https://github.com/octo-org/widgets/pull/42";
const PULL_PATH = "/repos/octo-org/widgets/pulls/42";
const UPSTASH = "https://fake-store.upstash.example";
const UPSTASH_TOKEN = "CANARY-UPSTASH-TOKEN-0c1d";

// A fake Upstash REST pipeline: SET ... NX and INCR over a Map. TTLs are not
// simulated; tests that need windows use the memory store with fake timers.
function fakeUpstash() {
  const data = new Map<string, number>();
  const calls: string[][][] = [];
  const handler = async (init: RequestInit | undefined) => {
    expect(new Headers(init?.headers).get("authorization")).toBe(`Bearer ${UPSTASH_TOKEN}`);
    const commands = JSON.parse(String(init?.body)) as string[][];
    calls.push(commands);
    const reply = commands.map(([cmd, key]) => {
      if (cmd === "SET") {
        if (data.has(key)) return { result: null };
        data.set(key, 0);
        return { result: "OK" };
      }
      const next = (data.get(key) ?? 0) + 1;
      data.set(key, next);
      return { result: next };
    });
    return json(reply);
  };
  return { data, calls, handler };
}

type Upstash = ReturnType<typeof fakeUpstash>;

let fetchSpy: MockInstance<typeof fetch>;
let model: FakeModel;
let output: string[];

function serve(upstash?: Upstash | ((init: RequestInit | undefined) => Response | Promise<Response>)) {
  const routes: Parameters<typeof fetchFrom>[0] = {
    [`${API}${PULL_PATH}`]: json(fixture("pull-small.json")),
    [filesFor(PULL_PATH)]: json(fixture("files-small.json")),
  };
  if (upstash !== undefined) routes[`${UPSTASH}/pipeline`] = typeof upstash === "function" ? upstash : upstash.handler;
  fetchSpy = vi.spyOn(globalThis, "fetch").mockImplementation(fetchFrom(routes));
}

function githubCalls(): number {
  return fetchSpy.mock.calls.filter(([input]) => String(input).startsWith(API)).length;
}

function analyze(headers: Record<string, string> = {}, body: unknown = { url: PR_URL }) {
  return POST(
    new Request("http://localhost/api/analyze", {
      method: "POST",
      headers: { "content-type": "application/json", ...headers },
      body: JSON.stringify(body),
    }),
  );
}

async function expectError(res: Response, httpStatus: number, category: string) {
  expect(res.status).toBe(httpStatus);
  const body = await res.json();
  expect(body.status).toBe("error");
  expect(body.error.category).toBe(category);
}

function events() {
  return output.map((line) => JSON.parse(line));
}

function lastEvent() {
  const all = events();
  const event = all[all.length - 1];
  expect(AnalysisEventSchema.safeParse(event).success).toBe(true);
  return event;
}

function expectNoPaidWork() {
  expect(githubCalls()).toBe(0);
  expect(model.calls).toHaveLength(0);
}

function onVercel(upstash: boolean) {
  vi.stubEnv("VERCEL", "1");
  vi.stubEnv("SERVICE_ENABLED", "true");
  vi.stubEnv("UPSTASH_REDIS_REST_URL", upstash ? UPSTASH : "");
  vi.stubEnv("UPSTASH_REDIS_REST_TOKEN", upstash ? UPSTASH_TOKEN : "");
}

beforeEach(() => {
  output = [];
  for (const method of ["log", "info", "warn", "error", "debug"] as const) {
    vi.spyOn(console, method).mockImplementation((...args: unknown[]) => {
      output.push(args.map((a) => (typeof a === "string" ? a : JSON.stringify(a))).join(" "));
    });
  }
  vi.stubEnv("VERCEL", "");
  vi.stubEnv("SERVICE_ENABLED", "");
  for (const name of ["UPSTASH_REDIS_REST_URL", "UPSTASH_REDIS_REST_TOKEN", "KV_REST_API_URL", "KV_REST_API_TOKEN"]) {
    vi.stubEnv(name, "");
  }
  for (const name of ["RATE_LIMIT_PER_IP_PER_HOUR", "RATE_LIMIT_PER_IP_PER_DAY", "ANALYSIS_DAILY_CAP"]) {
    vi.stubEnv(name, "");
  }
  model = fakeModel();
  vi.mocked(getBriefModel).mockReturnValue(model);
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
  vi.unstubAllEnvs();
});

describe("kill switch", () => {
  it("SERVICE_ENABLED=false refuses with 503 and makes zero GitHub and model calls", async () => {
    serve();
    vi.stubEnv("SERVICE_ENABLED", "false");
    const res = await analyze();
    await expectError(res, 503, "service_disabled");
    expect(res.headers.get("retry-after")).toBe("300");
    expectNoPaidWork();
    expect(fetchSpy).not.toHaveBeenCalled();
    expect(lastEvent()).toMatchObject({ outcome: "service_disabled", reason: "service_disabled", github_ms: null, llm_ms: null });
  });

  it("refuses before reading the body: even a malformed request gets service_disabled", async () => {
    serve();
    vi.stubEnv("SERVICE_ENABLED", "false");
    await expectError(await analyze({}, { nope: true }), 503, "service_disabled");
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("is OFF by default on Vercel: a new deployment serves nothing until SERVICE_ENABLED=true", async () => {
    serve(fakeUpstash());
    onVercel(true);
    vi.stubEnv("SERVICE_ENABLED", "");
    await expectError(await analyze({ "x-real-ip": "198.51.100.1" }), 503, "service_disabled");
    expect(fetchSpy).not.toHaveBeenCalled();
    expectNoPaidWork();
  });

  it("is on by default off Vercel (local development)", async () => {
    serve();
    expect((await analyze()).status).toBe(200);
  });

  it("can be turned back on: the next request is served", async () => {
    serve();
    vi.stubEnv("SERVICE_ENABLED", "false");
    expect((await analyze()).status).toBe(503);
    vi.stubEnv("SERVICE_ENABLED", "true");
    expect((await analyze()).status).toBe(200);
    expect(model.calls).toHaveLength(1);
  });

  it.each(["yes", "1", "off", "enabled"])("an unclear value %j is a config error, never a guess", async (value) => {
    serve();
    vi.stubEnv("SERVICE_ENABLED", value);
    await expectError(await analyze(), 500, "internal_error");
    expectNoPaidWork();
  });

  it("accepts case and spaces around true/false", async () => {
    serve();
    vi.stubEnv("SERVICE_ENABLED", " FALSE ");
    expect((await analyze()).status).toBe(503);
    vi.stubEnv("SERVICE_ENABLED", "True");
    expect((await analyze()).status).toBe(200);
  });

  it("health shows the switch", async () => {
    vi.stubEnv("SERVICE_ENABLED", "false");
    expect((await health().json()).service).toBe("disabled");
  });
});

describe("rate limits — route", () => {
  it("exhausting the per-client hourly limit returns 429 with Retry-After and no paid work", async () => {
    serve();
    vi.stubEnv("RATE_LIMIT_PER_IP_PER_HOUR", "2");
    expect((await analyze()).status).toBe(200);
    expect((await analyze()).status).toBe(200);
    const githubBefore = githubCalls();

    const res = await analyze();
    await expectError(res, 429, "rate_limited");
    const retryAfter = Number(res.headers.get("retry-after"));
    expect(retryAfter).toBeGreaterThan(0);
    expect(retryAfter).toBeLessThanOrEqual(3_600);
    expect(githubCalls()).toBe(githubBefore);
    expect(model.calls).toHaveLength(2);
    expect(lastEvent()).toMatchObject({ outcome: "rate_limited", http_status: 429, reason: "rate_limited_ip", github_requests: null });
  });

  it("the daily per-client limit applies too", async () => {
    serve();
    vi.stubEnv("RATE_LIMIT_PER_IP_PER_DAY", "1");
    expect((await analyze()).status).toBe(200);
    await expectError(await analyze(), 429, "rate_limited");
    expect(model.calls).toHaveLength(1);
  });

  it("malformed requests never reach the limiter or count against it", async () => {
    serve();
    vi.stubEnv("RATE_LIMIT_PER_IP_PER_HOUR", "1");
    for (let i = 0; i < 5; i++) await expectError(await analyze({}, { url: "https://github.com.evil.example/a/b/pull/1" }), 400, "invalid_pr_url");
    expect((await analyze()).status).toBe(200);
  });

  it("on Vercel without a shared store, analysis fails closed (never falls back to memory)", async () => {
    serve();
    onVercel(false);
    await expectError(await analyze({ "x-real-ip": "198.51.100.1" }), 503, "service_disabled");
    expect(fetchSpy).not.toHaveBeenCalled();
    expectNoPaidWork();
    expect(lastEvent().reason).toBe("rate_limiter_not_configured");
    expect((await health().json()).rateLimit.backend).toBe("not_configured");
  });

  it("on Vercel, counts per client IP in the shared store", async () => {
    const upstash = fakeUpstash();
    serve(upstash);
    onVercel(true);
    vi.stubEnv("RATE_LIMIT_PER_IP_PER_HOUR", "1");
    expect((await analyze({ "x-real-ip": "198.51.100.1" })).status).toBe(200);
    await expectError(await analyze({ "x-real-ip": "198.51.100.1" }), 429, "rate_limited");
    // A different client still gets through.
    expect((await analyze({ "x-real-ip": "198.51.100.2" })).status).toBe(200);
    expect(model.calls).toHaveLength(2);
    // The raw IP never reaches the store.
    expect(JSON.stringify(upstash.calls)).not.toContain("198.51.100");
  });

  it("the global daily cap stops all clients once reached", async () => {
    const upstash = fakeUpstash();
    serve(upstash);
    onVercel(true);
    vi.stubEnv("ANALYSIS_DAILY_CAP", "2");
    expect((await analyze({ "x-real-ip": "198.51.100.1" })).status).toBe(200);
    expect((await analyze({ "x-real-ip": "198.51.100.2" })).status).toBe(200);
    const githubBefore = githubCalls();
    await expectError(await analyze({ "x-real-ip": "198.51.100.3" }), 429, "rate_limited");
    expect(githubCalls()).toBe(githubBefore);
    expect(model.calls).toHaveLength(2);
    expect(lastEvent().reason).toBe("rate_limited_global");
  });

  it("a client over its own limit does not use up the global cap", async () => {
    serve(fakeUpstash());
    onVercel(true);
    vi.stubEnv("RATE_LIMIT_PER_IP_PER_HOUR", "1");
    vi.stubEnv("ANALYSIS_DAILY_CAP", "2");
    for (let i = 0; i < 10; i++) await analyze({ "x-real-ip": "198.51.100.1" });
    expect((await analyze({ "x-real-ip": "198.51.100.2" })).status).toBe(200);
  });

  it.each([
    ["the store answers 500", () => new Response("store down", { status: 500 })],
    ["the store times out", () => Promise.reject(Object.assign(new Error("timeout"), { name: "TimeoutError" }))],
    ["the store returns malformed JSON", () => new Response("not json", { status: 200 })],
    ["the store returns an error entry", () => json([{ result: "OK" }, { error: "WRONGTYPE" }, { result: "OK" }, { result: 1 }])],
    ["the store returns a non-number count", () => json([{ result: "OK" }, { result: "1" }, { result: "OK" }, { result: 1 }])],
  ])("fails closed when %s: 503 and no paid work", async (_name, reply) => {
    serve(reply);
    onVercel(true);
    await expectError(await analyze({ "x-real-ip": "198.51.100.1" }), 503, "service_disabled");
    expectNoPaidWork();
    expect(lastEvent().reason).toBe("rate_limiter_unavailable");
  });

  it("never logs the client IP or the store token", async () => {
    serve(fakeUpstash());
    onVercel(true);
    vi.stubEnv("RATE_LIMIT_PER_IP_PER_HOUR", "1");
    await analyze({ "x-real-ip": "198.51.100.77" });
    await analyze({ "x-real-ip": "198.51.100.77" });
    const text = output.join("\n");
    expect(text).not.toContain("198.51.100.77");
    expect(text).not.toContain(UPSTASH_TOKEN);
    expect(text).not.toContain("fake-store");
  });

  it.each([
    ["RATE_LIMIT_PER_IP_PER_HOUR", "ten"],
    ["RATE_LIMIT_PER_IP_PER_DAY", "-1"],
    ["ANALYSIS_DAILY_CAP", "0"],
    ["ANALYSIS_DAILY_CAP", "1.5"],
  ])("an invalid %s=%j is a config error, so analysis fails closed", async (name, value) => {
    serve();
    vi.stubEnv(name, value);
    await expectError(await analyze(), 500, "internal_error");
    expectNoPaidWork();
  });
});

describe("rate limits — unit", () => {
  const limits = { perIpPerHour: 2, perIpPerDay: 3, globalPerDay: 100 };

  it("resets the hourly window, with Retry-After pointing at the reset", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-10-26T10:59:00Z"));
    expect(await checkRateLimit("k", limits, memoryStore)).toEqual({ ok: true });
    expect(await checkRateLimit("k", limits, memoryStore)).toEqual({ ok: true });
    expect(await checkRateLimit("k", limits, memoryStore)).toEqual({ ok: false, reason: "rate_limited_ip", retryAfterSec: 60 });
    vi.setSystemTime(new Date("2026-10-26T11:00:01Z"));
    // New hour, but this is the 4th request today: the daily limit (3) applies.
    expect(await checkRateLimit("k", limits, memoryStore)).toMatchObject({ ok: false, reason: "rate_limited_ip" });
    vi.setSystemTime(new Date("2026-10-27T00:00:01Z"));
    expect(await checkRateLimit("k", limits, memoryStore)).toEqual({ ok: true });
  });

  it("sends one pipeline per layer, starting each window once with its TTL", async () => {
    const upstash = fakeUpstash();
    serve(upstash);
    const store = upstashStore(`${UPSTASH}/`, UPSTASH_TOKEN);
    expect(await checkRateLimit("abc", limits, store, Date.parse("2026-10-26T10:00:00Z"))).toEqual({ ok: true });
    expect(upstash.calls).toHaveLength(2);
    const [client, global] = upstash.calls;
    expect(client.map((c) => c[0])).toEqual(["SET", "INCR", "SET", "INCR"]);
    expect(client[0].slice(2)).toEqual(["0", "EX", "3600", "NX"]);
    expect(client[2].slice(2)).toEqual(["0", "EX", "86400", "NX"]);
    expect(global[0][1]).toMatch(/^changebrief:rl:v1:global:d:\d+$/);
    expect(fetchSpy.mock.calls[0][1]).toMatchObject({ redirect: "error", method: "POST" });
  });
});

describe("client key", () => {
  const headers = (h: Record<string, string>) => new Headers(h);

  it("off Vercel, every request is the same local client, whatever headers say", () => {
    expect(clientKey(headers({ "x-real-ip": "1.2.3.4", "x-forwarded-for": "5.6.7.8" }), false)).toBe("local");
  });

  it("on Vercel, uses x-real-ip, falling back to the first x-forwarded-for entry", () => {
    const a = clientKey(headers({ "x-real-ip": "203.0.113.5", "x-forwarded-for": "198.51.100.9" }), true);
    expect(a).toBe(clientKey(headers({ "x-forwarded-for": "203.0.113.5, 10.0.0.1" }), true));
    expect(a).toMatch(/^[0-9a-f]{32}$/);
    expect(a).not.toContain("203");
  });

  it("puts unusable addresses into one shared strict bucket", () => {
    expect(clientKey(headers({}), true)).toBe("unknown");
    expect(clientKey(headers({ "x-real-ip": "not-an-ip" }), true)).toBe("unknown");
    expect(clientKey(headers({ "x-real-ip": "1.2.3.4:80" }), true)).toBe("unknown");
  });

  it("counts IPv6 per /64", () => {
    expect(rateLimitSubject("2001:db8:1:2:aaaa::1")).toBe("2001:0db8:0001:0002::/64");
    expect(rateLimitSubject("2001:db8:1:2::ffff")).toBe("2001:0db8:0001:0002::/64");
    expect(rateLimitSubject("::1")).toBe("0000:0000:0000:0000::/64");
    expect(rateLimitSubject("::ffff:192.0.2.1")).toBe("0000:0000:0000:0000::/64");
    expect(rateLimitSubject("192.0.2.1")).toBe("192.0.2.1");
    const k = (ip: string) => clientKey(headers({ "x-real-ip": ip }), true);
    expect(k("2001:db8:1:2::1")).toBe(k("2001:db8:1:2:ffff:ffff:ffff:ffff"));
    expect(k("2001:db8:1:2::1")).not.toBe(k("2001:db8:1:3::1"));
  });
});

describe("security headers", () => {
  it("sends CSP, no-framing, nosniff, referrer and HSTS headers on every path", async () => {
    const rules = await nextConfig.headers!();
    expect(rules).toHaveLength(1);
    expect(rules[0].source).toBe("/(.*)");
    const byKey = Object.fromEntries(rules[0].headers.map((h) => [h.key, h.value]));
    expect(byKey["X-Content-Type-Options"]).toBe("nosniff");
    expect(byKey["X-Frame-Options"]).toBe("DENY");
    expect(byKey["Referrer-Policy"]).toBe("strict-origin-when-cross-origin");
    expect(byKey["Strict-Transport-Security"]).toMatch(/^max-age=\d+/);
    expect(byKey["Content-Security-Policy"]).toBe(CONTENT_SECURITY_POLICY);
    expect(nextConfig.poweredByHeader).toBe(false);
  });

  it("the CSP blocks framing, plugins, foreign scripts and foreign connections", () => {
    for (const directive of [
      "default-src 'self'",
      "connect-src 'self'",
      "object-src 'none'",
      "frame-ancestors 'none'",
      "base-uri 'self'",
      "form-action 'self'",
    ]) {
      expect(CONTENT_SECURITY_POLICY).toContain(directive);
    }
    expect(CONTENT_SECURITY_POLICY).toMatch(/script-src 'self' 'unsafe-inline'(;|$)/);
  });
});
