import { afterEach, describe, expect, it, vi } from "vitest";
import { APIConnectionError, APIConnectionTimeoutError, APIError } from "openai";
import {
  LLM_MAX_RETRIES,
  LLM_TIMEOUT_MS,
  MAX_OUTPUT_TOKENS,
  MODEL_BRIEF_JSON_SCHEMA,
  createOpenAIBriefModel,
  type ResponsesClient,
} from "@/lib/llm/openai";
import { INSTRUCTIONS, PROMPT_VERSION } from "@/lib/llm/prompt";
import { normalizeEvidence } from "@/lib/normalize/evidence";
import { mapFiles, mapPull } from "@/lib/github/map";
import { fixture } from "./helpers/github";
import { VALID_MODEL_BRIEF } from "./helpers/llm";

// The OpenAI adapter against a FAKE client. No network, no API money.

const PR = { owner: "octo-org", repo: "widgets", number: 42 };

function evidence(pull = "pull-small.json", files = "files-small.json") {
  const p = mapPull(fixture(pull));
  const f = mapFiles(fixture(files));
  if (p === null || f === null) throw new Error("fixture did not map");
  return normalizeEvidence(PR, p, f);
}

function okResponse(overrides: Record<string, unknown> = {}) {
  return {
    id: "resp_test",
    object: "response",
    model: "gpt-6-luna-2026-09-01",
    status: "completed",
    incomplete_details: null,
    output_text: JSON.stringify(VALID_MODEL_BRIEF),
    output: [{ type: "message", content: [{ type: "output_text", text: "…" }] }],
    usage: {
      input_tokens: 2100,
      input_tokens_details: { cached_tokens: 1024, cache_write_tokens: 0 },
      output_tokens: 410,
      output_tokens_details: { reasoning_tokens: 0 },
      total_tokens: 2510,
    },
    ...overrides,
  };
}

function fakeClient(respond: () => unknown) {
  const create = vi.fn(async () => respond());
  const client: ResponsesClient = { responses: { create } };
  return { client, create };
}

function model(client: ResponsesClient, reasoningEffort: "none" | "low" | "medium" | "high" = "none") {
  return createOpenAIBriefModel({ apiKey: "sk-TEST_MARKER_not_real", model: "gpt-6-luna", reasoningEffort, client });
}

afterEach(() => vi.restoreAllMocks());

describe("OpenAI adapter — request", () => {
  it("makes exactly one bounded request with no tools, no storage, and strict structured output", async () => {
    const { client, create } = fakeClient(() => okResponse());
    await model(client, "low").generateBrief(evidence());
    expect(create).toHaveBeenCalledTimes(1);
    const [params, options] = create.mock.calls[0] as unknown as [Record<string, unknown>, Record<string, unknown>];
    expect(Object.keys(params).sort()).toEqual(
      ["input", "instructions", "max_output_tokens", "model", "reasoning", "store", "text"].sort(),
    );
    expect(params).toMatchObject({
      model: "gpt-6-luna",
      instructions: INSTRUCTIONS,
      max_output_tokens: 1500,
      reasoning: { effort: "low" },
      store: false,
      text: { format: { type: "json_schema", name: "change_brief", strict: true, schema: MODEL_BRIEF_JSON_SCHEMA } },
    });
    expect(params).not.toHaveProperty("tools");
    expect(options).toEqual({ timeout: 30_000, maxRetries: 0 });
    expect([MAX_OUTPUT_TOKENS, LLM_TIMEOUT_MS, LLM_MAX_RETRIES]).toEqual([1500, 30_000, 0]);
  });

  it("sends the normalized evidence as one JSON document, and nothing else", async () => {
    const { client, create } = fakeClient(() => okResponse());
    const ev = evidence();
    await model(client).generateBrief(ev);
    const params = create.mock.calls[0] as unknown as [{ input: string }];
    expect(JSON.parse(params[0].input)).toEqual(ev);
  });

  it("keeps instruction-like PR text inside JSON string values, out of the instructions", async () => {
    const { client, create } = fakeClient(() => okResponse());
    await model(client).generateBrief(evidence("pull-injection.json", "files-injection.json"));
    const params = create.mock.calls[0] as unknown as [{ input: string; instructions: string }];
    expect(params[0].instructions).toBe(INSTRUCTIONS);
    expect(params[0].instructions).not.toMatch(/<script>/);
    const parsed = JSON.parse(params[0].input);
    expect(parsed.files[0].patch).toContain("<script>alert(document.domain)</script>");
  });

  it("uses a strict JSON schema: every object closed, every field required", () => {
    const walk = (node: unknown): void => {
      if (node === null || typeof node !== "object") return;
      const n = node as Record<string, unknown>;
      if (n.type === "object") {
        expect(n.additionalProperties).toBe(false);
        expect(Object.keys(n.properties as object).sort()).toEqual([...(n.required as string[])].sort());
      }
      Object.values(n).forEach(walk);
    };
    walk(MODEL_BRIEF_JSON_SCHEMA);
    expect(MODEL_BRIEF_JSON_SCHEMA).not.toHaveProperty("$schema");
  });

  it("has a prompt version", () => {
    expect(PROMPT_VERSION).toMatch(/^p\d+\.\d+$/);
  });
});

describe("OpenAI adapter — successful reply", () => {
  it("returns the validated brief, the served model ID and provider-reported usage", async () => {
    const { client } = fakeClient(() => okResponse());
    const result = await model(client).generateBrief(evidence());
    expect(result).toMatchObject({
      ok: true,
      provider: "openai",
      model: "gpt-6-luna-2026-09-01",
      brief: VALID_MODEL_BRIEF,
      usage: { input_tokens: 2100, cached_input_tokens: 1024, output_tokens: 410, reasoning_tokens: 0 },
    });
    expect(result.llmMs).toBeGreaterThanOrEqual(0);
  });

  it("reports missing usage as unknown (null), never zero", async () => {
    const { client } = fakeClient(() => okResponse({ usage: undefined }));
    const result = await model(client).generateBrief(evidence());
    expect(result.ok && result.usage).toEqual({
      input_tokens: null,
      cached_input_tokens: null,
      output_tokens: null,
      reasoning_tokens: null,
    });
  });

  it("reports malformed usage fields as unknown", async () => {
    const { client } = fakeClient(() => okResponse({ usage: { input_tokens: -1, output_tokens: "410" } }));
    const result = await model(client).generateBrief(evidence());
    expect(result.ok && result.usage).toEqual({
      input_tokens: null,
      cached_input_tokens: null,
      output_tokens: null,
      reasoning_tokens: null,
    });
  });
});

describe("OpenAI adapter — invalid output never passes", () => {
  it.each([
    ["hit the output-token ceiling", { status: "incomplete", incomplete_details: { reason: "max_output_tokens" } }, "incomplete_max_tokens"],
    ["content filter", { status: "incomplete", incomplete_details: { reason: "content_filter" } }, "incomplete_other"],
    ["refusal", { output_text: "", output: [{ type: "message", content: [{ type: "refusal", refusal: "no" }] }] }, "refusal"],
    ["empty output", { output_text: "" }, "empty_output"],
    ["no output_text", { output_text: undefined }, "empty_output"],
    ["malformed JSON", { output_text: "{not json" }, "malformed_json"],
    ["wrong shape", { output_text: JSON.stringify({ summary: "x" }) }, "schema_mismatch"],
    [
      "an extra field (e.g. an approve verdict)",
      { output_text: JSON.stringify({ ...VALID_MODEL_BRIEF, approved: true }) },
      "schema_mismatch",
    ],
    [
      "an unknown risk level",
      { output_text: JSON.stringify({ ...VALID_MODEL_BRIEF, risk: { ...VALID_MODEL_BRIEF.risk, level: "none" } }) },
      "schema_mismatch",
    ],
  ])("%s -> output_invalid", async (_label, overrides, reason) => {
    const { client } = fakeClient(() => okResponse(overrides));
    const result = await model(client).generateBrief(evidence());
    expect(result).toMatchObject({ ok: false, kind: "output_invalid", reason, model: "gpt-6-luna-2026-09-01" });
    // A failed reply still reports what it cost, when the provider said.
    expect(!result.ok && result.usage?.input_tokens).toBe(2100);
  });
});

describe("OpenAI adapter — provider failures", () => {
  const headers = new Headers();
  it.each([
    ["timeout", () => new APIConnectionTimeoutError(), "timeout"],
    ["connection error", () => new APIConnectionError({ message: "PROVIDER-ERROR-TEXT-MARKER" }), "network_error"],
    ["401", () => APIError.generate(401, { message: "PROVIDER-ERROR-TEXT-MARKER" }, undefined, headers), "auth"],
    ["403", () => APIError.generate(403, { message: "PROVIDER-ERROR-TEXT-MARKER" }, undefined, headers), "auth"],
    ["429 (rate limit or credit exhausted)", () => APIError.generate(429, { message: "PROVIDER-ERROR-TEXT-MARKER" }, undefined, headers), "rate_limited"],
    ["400 (e.g. model not allowed)", () => APIError.generate(400, { message: "PROVIDER-ERROR-TEXT-MARKER" }, undefined, headers), "bad_request"],
    ["404", () => APIError.generate(404, { message: "PROVIDER-ERROR-TEXT-MARKER" }, undefined, headers), "bad_request"],
    ["500", () => APIError.generate(500, { message: "PROVIDER-ERROR-TEXT-MARKER" }, undefined, headers), "upstream_5xx"],
    ["409", () => APIError.generate(409, { message: "PROVIDER-ERROR-TEXT-MARKER" }, undefined, headers), "upstream_status"],
    ["unexpected throw", () => new Error("PROVIDER-ERROR-TEXT-MARKER"), "network_error"],
  ])("%s -> provider_unavailable, no retry, no provider text", async (_label, makeError, reason) => {
    const { client, create } = fakeClient(() => {
      throw makeError();
    });
    const result = await model(client).generateBrief(evidence());
    expect(create).toHaveBeenCalledTimes(1);
    expect(result).toMatchObject({ ok: false, kind: "provider_unavailable", reason, model: null, usage: null });
    expect(JSON.stringify(result)).not.toContain("PROVIDER-ERROR-TEXT-MARKER");
  });
});
