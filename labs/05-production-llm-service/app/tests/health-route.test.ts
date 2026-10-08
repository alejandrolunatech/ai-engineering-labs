import { afterEach, describe, expect, it, vi } from "vitest";
import { GET } from "@/app/api/health/route";

afterEach(() => {
  vi.unstubAllEnvs();
  vi.restoreAllMocks();
});

describe("GET /api/health", () => {
  it("reports process/config health only, with no external call", async () => {
    vi.stubEnv("GITHUB_TOKEN", "");
    vi.stubEnv("OPENAI_API_KEY", "");
    vi.stubEnv("OPENAI_MODEL", "");
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    const res = GET();
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body).toEqual({
      status: "ok",
      config: "valid",
      schemaVersion: "0.1",
      githubAuth: "anonymous",
      llm: { status: "not_configured" },
    });
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("reports the configured model and effort, never the API key, and makes no model call", async () => {
    vi.stubEnv("OPENAI_API_KEY", "sk-TEST_MARKER_not_real");
    vi.stubEnv("OPENAI_MODEL", "gpt-6-luna");
    vi.stubEnv("OPENAI_REASONING_EFFORT", "");
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    const res = GET();
    const text = await res.text();
    expect(JSON.parse(text).llm).toEqual({ status: "configured", model: "gpt-6-luna", reasoningEffort: "none" });
    expect(text).not.toContain("TEST_MARKER");
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("needs both the key and the model to count as configured", async () => {
    vi.stubEnv("OPENAI_API_KEY", "sk-TEST_MARKER_not_real");
    vi.stubEnv("OPENAI_MODEL", "  ");
    expect((await GET().json()).llm).toEqual({ status: "not_configured" });
    vi.stubEnv("OPENAI_API_KEY", "");
    vi.stubEnv("OPENAI_MODEL", "gpt-6-luna");
    expect((await GET().json()).llm).toEqual({ status: "not_configured" });
  });

  it("treats an unresolved 1Password reference as no key (started without op run)", async () => {
    vi.stubEnv("OPENAI_API_KEY", "op://Dev/changebrief-g0/credential");
    vi.stubEnv("OPENAI_MODEL", "gpt-6-luna");
    const text = await GET().text();
    expect(JSON.parse(text).llm).toEqual({ status: "not_configured" });
    expect(text).not.toContain("op://");
  });

  it.each([
    ["a malformed model ID", { OPENAI_MODEL: "gpt 6; rm -rf /" }],
    ["an upper-case model ID", { OPENAI_MODEL: "GPT-6-LUNA" }],
    ["an unknown reasoning effort", { OPENAI_MODEL: "gpt-6-luna", OPENAI_REASONING_EFFORT: "max" }],
  ])("fails closed with 503 on %s", async (_label, env) => {
    vi.stubEnv("OPENAI_API_KEY", "sk-TEST_MARKER_not_real");
    vi.stubEnv("OPENAI_REASONING_EFFORT", "");
    for (const [k, v] of Object.entries(env)) vi.stubEnv(k, v);
    const res = GET();
    expect(res.status).toBe(503);
    const text = await res.text();
    expect(JSON.parse(text)).toEqual({ status: "error", config: "invalid" });
    expect(text).not.toContain("TEST_MARKER");
  });

  it("reports that a token is configured, never the token itself", async () => {
    const marker = "github_pat_TEST_MARKER_not_real";
    vi.stubEnv("GITHUB_TOKEN", marker);
    const res = GET();
    const text = await res.text();
    expect(JSON.parse(text).githubAuth).toBe("token");
    expect(text).not.toContain("TEST_MARKER");
  });

  it("treats a blank token as anonymous", async () => {
    vi.stubEnv("GITHUB_TOKEN", "   ");
    expect((await GET().json()).githubAuth).toBe("anonymous");
  });
});
