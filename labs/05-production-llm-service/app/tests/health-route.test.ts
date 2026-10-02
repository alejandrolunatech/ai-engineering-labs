import { describe, expect, it, vi } from "vitest";
import { GET } from "@/app/api/health/route";

describe("GET /api/health", () => {
  it("reports process/config health only, with no external call", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    const res = GET();
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body).toEqual({ status: "ok", config: "valid", schemaVersion: "0.1" });
    expect(JSON.stringify(body)).not.toMatch(/github|llm|openai|model|provider/i);
    expect(fetchSpy).not.toHaveBeenCalled();
    fetchSpy.mockRestore();
  });
});
