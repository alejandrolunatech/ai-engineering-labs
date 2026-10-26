import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { SECURITY_HEADERS } from "@/next.config";
import { POST, maxDuration } from "@/app/api/analyze/route";
import { GET as health } from "@/app/api/health/route";
import { MAX_REQUESTS, REQUEST_TIMEOUT_MS } from "@/lib/github/client";
import { getBriefModel } from "@/lib/llm";
import { LLM_TIMEOUT_MS } from "@/lib/llm/openai";
import { REQUEST_ID } from "@/lib/telemetry";
import { runSmoke, SMOKE_PR } from "@/scripts/smoke-lib";
import { API, json, mockFetch, fixture, filesFor } from "./helpers/github";
import { fakeModel } from "./helpers/llm";

// Phase 7: request references, readiness, the function time limit and the
// smoke test. Mocked GitHub, fake model: no network, no API money.

vi.mock("@/lib/llm", () => ({ getBriefModel: vi.fn() }));
// openai.ts constants are read for the time-limit check; the SDK is never called.

const SMOKE_PATH = "/repos/nodejs/node/pulls/66442";

let output: string[];

beforeEach(() => {
  output = [];
  vi.spyOn(console, "info").mockImplementation((line: string) => void output.push(line));
  for (const name of ["VERCEL", "SERVICE_ENABLED", "UPSTASH_REDIS_REST_URL", "UPSTASH_REDIS_REST_TOKEN", "KV_REST_API_URL", "KV_REST_API_TOKEN"]) {
    vi.stubEnv(name, "");
  }
  vi.stubEnv("OPENAI_API_KEY", "test-key-not-real");
  vi.stubEnv("OPENAI_MODEL", "gpt-6-luna");
  vi.mocked(getBriefModel).mockReturnValue(fakeModel());
  mockFetch({
    [`${API}${SMOKE_PATH}`]: json(fixture("pull-small.json")),
    [filesFor(SMOKE_PATH)]: json(fixture("files-small.json")),
  });
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllEnvs();
});

function analyze(url: string) {
  return POST(
    new Request("http://localhost/api/analyze", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ url }),
    }),
  );
}

describe("request reference", () => {
  it("every response carries a fresh X-Request-Id that matches its telemetry event", async () => {
    const ok = await analyze(SMOKE_PR);
    const bad = await analyze("https://github.com.evil.example/a/b/pull/1");
    const ids = [ok, bad].map((r) => r.headers.get("x-request-id"));
    for (const id of ids) expect(id).toMatch(REQUEST_ID);
    expect(ids[0]).not.toBe(ids[1]);
    expect(output.map((l) => JSON.parse(l).request_id)).toEqual(ids);
  });

  it("refusals carry it too, and are never cached", async () => {
    vi.stubEnv("SERVICE_ENABLED", "false");
    const res = await analyze(SMOKE_PR);
    expect(res.status).toBe(503);
    expect(res.headers.get("x-request-id")).toMatch(REQUEST_ID);
    expect(res.headers.get("cache-control")).toBe("no-store");
  });
});

describe("readiness", () => {
  it("is ready when the service is on, a model is configured and a store exists", async () => {
    expect((await health().json()).ready).toBe(true);
  });

  it.each([
    ["the kill switch is on", { SERVICE_ENABLED: "false" }],
    ["no model is configured", { OPENAI_MODEL: "" }],
    ["on Vercel without a rate-limit store", { VERCEL: "1", SERVICE_ENABLED: "true" }],
  ])("is not ready when %s", async (_name, env) => {
    for (const [k, v] of Object.entries(env)) vi.stubEnv(k, v);
    const res = health();
    expect(res.status).toBe(200);
    expect((await res.json()).ready).toBe(false);
  });
});

describe("function time limit", () => {
  it("leaves room for the worst-case GitHub and model time", () => {
    expect(maxDuration * 1000).toBeGreaterThan(MAX_REQUESTS * REQUEST_TIMEOUT_MS + LLM_TIMEOUT_MS);
    expect(maxDuration).toBeLessThanOrEqual(120);
  });
});

describe("smoke test", () => {
  // Routes the smoke test's requests to the real handlers in this process.
  async function send(url: string, init?: RequestInit): Promise<Response> {
    const path = new URL(url).pathname;
    if (path === "/api/health") return health();
    if (path === "/api/analyze") return POST(new Request(url, init));
    if (path === "/") return new Response("<html></html>", { status: 200, headers: SECURITY_HEADERS.map((h) => [h.key, h.value]) });
    return new Response(null, { status: 404 });
  }

  it("passes against a healthy deployment, including one real analysis", async () => {
    const checks = await runSmoke("http://localhost:3000", { analyze: true }, send);
    expect(checks.filter((c) => !c.ok)).toEqual([]);
    expect(checks.map((c) => c.name)).toContain("one real analysis");
    expect(checks.map((c) => c.name)).toContain("safe failure (lookalike host refused)");
  });

  it("makes no analysis request without --analyze", async () => {
    const model = fakeModel();
    vi.mocked(getBriefModel).mockReturnValue(model);
    await runSmoke("http://localhost:3000", { analyze: false }, send);
    expect(model.calls).toHaveLength(0);
  });

  it("fails when the kill switch is on", async () => {
    vi.stubEnv("SERVICE_ENABLED", "false");
    const checks = await runSmoke("http://localhost:3000", { analyze: false }, send);
    expect(checks.filter((c) => !c.ok).map((c) => c.name).sort()).toEqual(["ready", "safe failure (lookalike host refused)", "service enabled"]);
  });

  it("requires the shared store on a public host", async () => {
    const checks = await runSmoke("https://changebrief.example", { analyze: false }, send);
    expect(checks.find((c) => c.name === "rate-limit store")).toMatchObject({ ok: false, detail: "backend=memory" });
  });

  it("prints no response body, only fixed values", async () => {
    const checks = await runSmoke("http://localhost:3000", { analyze: true }, send);
    const text = checks.map((c) => c.detail).join("\n");
    expect(text).not.toContain("Adds a widget cache");
    expect(text).not.toContain("test-key-not-real");
  });
});
