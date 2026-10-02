import { afterEach, describe, expect, it, vi } from "vitest";
import { GET } from "@/app/api/health/route";

afterEach(() => {
  vi.unstubAllEnvs();
  vi.restoreAllMocks();
});

describe("GET /api/health", () => {
  it("reports process/config health only, with no external call", async () => {
    vi.stubEnv("GITHUB_TOKEN", "");
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    const res = GET();
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body).toEqual({ status: "ok", config: "valid", schemaVersion: "0.1", githubAuth: "anonymous" });
    expect(JSON.stringify(body)).not.toMatch(/llm|openai|model|provider/i);
    expect(fetchSpy).not.toHaveBeenCalled();
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
