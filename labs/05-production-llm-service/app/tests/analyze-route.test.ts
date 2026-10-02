import { afterEach, beforeEach, describe, expect, it, vi, type MockInstance } from "vitest";
import { DELETE, GET, PATCH, POST, PUT } from "@/app/api/analyze/route";
import { ParsedResponseSchema } from "@/lib/schemas/analyze";

const ENDPOINT = "http://localhost/api/analyze";
const VALID_URL = "https://github.com/vercel/next.js/pull/12345";

let fetchSpy: MockInstance<typeof fetch>;

beforeEach(() => {
  fetchSpy = vi.spyOn(globalThis, "fetch").mockImplementation(() => {
    throw new Error("network access is not allowed in Phase 1");
  });
});

afterEach(() => {
  // Every case: the analyze boundary made no network call.
  expect(fetchSpy).not.toHaveBeenCalled();
  fetchSpy.mockRestore();
});

function post(body: BodyInit | null, headers: Record<string, string> = { "content-type": "application/json" }) {
  return POST(new Request(ENDPOINT, { method: "POST", body, headers }));
}

async function expectError(res: Response, status: number, category: string) {
  expect(res.status).toBe(status);
  const body = await res.json();
  expect(Object.keys(body).sort()).toEqual(["error", "status"]);
  expect(body.status).toBe("error");
  expect(Object.keys(body.error).sort()).toEqual(["category", "message"]);
  expect(body.error.category).toBe(category);
  return body;
}

describe("POST /api/analyze — success", () => {
  it("returns the parsed PR and the constructed API URL", async () => {
    const res = await post(JSON.stringify({ url: VALID_URL }));
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body).toEqual({
      status: "parsed",
      pr: { owner: "vercel", repo: "next.js", number: 12345 },
      wouldFetch: "https://api.github.com/repos/vercel/next.js/pulls/12345",
    });
    expect(ParsedResponseSchema.safeParse(body).success).toBe(true);
  });

  it("accepts a content type with a charset parameter", async () => {
    const res = await post(JSON.stringify({ url: VALID_URL }), {
      "content-type": "Application/JSON; charset=utf-8",
    });
    expect(res.status).toBe(200);
  });

  it("accepts a body of exactly 2048 bytes", async () => {
    const base = JSON.stringify({ url: VALID_URL + "?" });
    const body = JSON.stringify({ url: VALID_URL + "?" + "a".repeat(2048 - base.length) });
    expect(new TextEncoder().encode(body).byteLength).toBe(2048);
    const res = await post(body);
    expect(res.status).toBe(200);
  });
});

describe("POST /api/analyze — body size (hard 2 KB cap)", () => {
  it("rejects 2049 bytes with 413", async () => {
    const base = JSON.stringify({ url: VALID_URL + "?" });
    const body = JSON.stringify({ url: VALID_URL + "?" + "a".repeat(2049 - base.length) });
    expect(new TextEncoder().encode(body).byteLength).toBe(2049);
    await expectError(await post(body), 413, "request_too_large");
  });

  it("counts bytes, not characters (multi-byte UTF-8)", async () => {
    // 1100 x "é" is ~1110 characters but 2200+ bytes.
    const body = JSON.stringify({ url: "é".repeat(1100) });
    expect(body.length).toBeLessThan(2048);
    expect(new TextEncoder().encode(body).byteLength).toBeGreaterThan(2048);
    await expectError(await post(body), 413, "request_too_large");
  });

  it("does not trust a lying Content-Length", async () => {
    const body = JSON.stringify({ url: VALID_URL, pad: "x".repeat(5000) });
    const res = await post(body, { "content-type": "application/json", "content-length": "10" });
    await expectError(res, 413, "request_too_large");
  });

  it("rejects early on a declared Content-Length over the cap", async () => {
    const res = await post("{}", { "content-type": "application/json", "content-length": "999999" });
    await expectError(res, 413, "request_too_large");
  });

  it("stops reading an oversized streamed body", async () => {
    let pulled = 0;
    const chunk = new TextEncoder().encode("x".repeat(1024));
    const stream = new ReadableStream<Uint8Array>({
      pull(controller) {
        pulled += 1;
        if (pulled > 1000) controller.close();
        else controller.enqueue(chunk);
      },
    });
    const req = new Request(ENDPOINT, {
      method: "POST",
      body: stream,
      headers: { "content-type": "application/json" },
      // @ts-expect-error -- Node requires duplex for stream bodies; not in the DOM lib types.
      duplex: "half",
    });
    await expectError(await POST(req), 413, "request_too_large");
    expect(pulled).toBeLessThan(10);
  });
});

describe("POST /api/analyze — content type", () => {
  it.each([
    ["missing", {}],
    ["text/plain", { "content-type": "text/plain" }],
    ["form", { "content-type": "application/x-www-form-urlencoded" }],
    ["json lookalike", { "content-type": "application/jsonx" }],
    ["multipart", { "content-type": "multipart/form-data; boundary=x" }],
  ])("rejects %s with 415", async (_label, headers) => {
    await expectError(await post(JSON.stringify({ url: VALID_URL }), headers), 415, "invalid_pr_url");
  });
});

describe("/api/analyze — method", () => {
  it.each([
    ["GET", GET],
    ["PUT", PUT],
    ["PATCH", PATCH],
    ["DELETE", DELETE],
  ])("%s returns 405 with Allow: POST", async (_m, handler) => {
    const res = handler();
    await expectError(res, 405, "invalid_pr_url");
    expect(res.headers.get("allow")).toBe("POST");
  });
});

describe("POST /api/analyze — JSON shape", () => {
  it.each([
    ["malformed JSON", "{url:"],
    ["empty body", ""],
    ["JSON null", "null"],
    ["JSON array", JSON.stringify([VALID_URL])],
    ["JSON string", JSON.stringify(VALID_URL)],
    ["missing url", JSON.stringify({})],
    ["url is a number", JSON.stringify({ url: 12345 })],
    ["url is null", JSON.stringify({ url: null })],
    ["extra field", JSON.stringify({ url: VALID_URL, model: "gpt-x" })],
    ["prototype key", '{"url":"' + VALID_URL + '","__proto__":{"x":1}}'],
    ["invalid URL", JSON.stringify({ url: "https://evil.com/o/r/pull/1" })],
  ])("rejects %s with 400", async (_label, body) => {
    await expectError(await post(body), 400, "invalid_pr_url");
  });

  it("rejects invalid UTF-8 with 400", async () => {
    const bytes = new Uint8Array([0x7b, 0x22, 0x75, 0x22, 0x3a, 0x22, 0xff, 0xfe, 0x22, 0x7d]);
    await expectError(await post(bytes), 400, "invalid_pr_url");
  });

  it("never echoes the submitted input in an error", async () => {
    const marker = "https://github.com.evil.example/<script>/pull/1";
    const res = await post(JSON.stringify({ url: marker }));
    const text = await res.clone().text();
    expect(text).not.toContain("evil.example");
    expect(text).not.toContain("<script>");
    await expectError(res, 400, "invalid_pr_url");
  });
});
