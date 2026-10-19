import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { POST } from "@/app/api/analyze/route";
import { getBriefModel } from "@/lib/llm";
import { PRICING_AS_OF } from "@/lib/pricing";
import { BriefResponseSchema } from "@/lib/schemas/change-brief";
import { AnalysisEventSchema } from "@/lib/telemetry";
import { API, filesFor, fixture, json, mockFetch, status } from "./helpers/github";
import { FAKE_USAGE, VALID_MODEL_BRIEF, fakeModel } from "./helpers/llm";

// Phase 5: one privacy-safe telemetry event per request, and no source content
// in ANY log output. Mocked GitHub, fake model, no network, no API money.

vi.mock("@/lib/llm", () => ({ getBriefModel: vi.fn() }));

const PR_URL = "https://github.com/octo-org/widgets/pull/42";
const PULL_PATH = "/repos/octo-org/widgets/pulls/42";

// Unmistakable strings planted in every place source content can come from.
const CANARIES = {
  title: "CANARY-TITLE-7f3a",
  body: "CANARY-BODY-91c2",
  filename: "CANARY-FILENAME-4d8e",
  patch: "CANARY-PATCH-b6f0",
  output: "CANARY-MODEL-OUTPUT-2e5d",
  openai: "CANARY-OPENAI-VALUE",
  github: "CANARY-GITHUB-VALUE",
  cookie: "CANARY-COOKIE-55aa",
  ip: "203.0.113.77",
};

function canaryPull() {
  const pull = fixture("pull-small.json") as Record<string, unknown>;
  return { ...pull, title: `Fix ${CANARIES.title}`, body: `Details ${CANARIES.body}` };
}

function canaryFiles() {
  const files = fixture("files-small.json") as Record<string, unknown>[];
  return files.map((f, i) =>
    i === 0 ? { ...f, filename: `src/${CANARIES.filename}.ts`, patch: `@@ -1 +1 @@\n+const k = "${CANARIES.patch}";` } : f,
  );
}

function serve(pull: unknown = canaryPull(), files: unknown = canaryFiles()) {
  mockFetch({ [`${API}${PULL_PATH}`]: json(pull), [filesFor(PULL_PATH)]: json(files) });
}

function analyze() {
  return POST(
    new Request("http://localhost/api/analyze", {
      method: "POST",
      headers: {
        "content-type": "application/json",
        cookie: `session=${CANARIES.cookie}`,
        "x-forwarded-for": CANARIES.ip,
      },
      body: JSON.stringify({ url: PR_URL }),
    }),
  );
}

// Every console method, so nothing written anywhere escapes the check.
let output: string[];
beforeEach(() => {
  output = [];
  for (const method of ["log", "info", "warn", "error", "debug"] as const) {
    vi.spyOn(console, method).mockImplementation((...args: unknown[]) => {
      output.push(args.map((a) => (typeof a === "string" ? a : JSON.stringify(a))).join(" "));
    });
  }
  vi.stubEnv("OPENAI_API_KEY", CANARIES.openai);
  vi.stubEnv("OPENAI_MODEL", "gpt-6-luna");
  vi.stubEnv("GITHUB_TOKEN", CANARIES.github);
});
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllEnvs();
});

function events() {
  return output.map((line) => JSON.parse(line));
}

function onlyEvent() {
  const all = events();
  expect(all).toHaveLength(1);
  const parsed = AnalysisEventSchema.safeParse(all[0]);
  expect(parsed.success).toBe(true);
  return all[0];
}

function expectNoLeak() {
  const text = output.join("\n");
  for (const [name, canary] of Object.entries(CANARIES)) {
    expect(text.includes(canary), `${name} leaked into logs`).toBe(false);
  }
}

describe("POST /api/analyze — telemetry", () => {
  it("success: one event with timings, usage and an estimated cost", async () => {
    serve();
    const brief = { ...VALID_MODEL_BRIEF, summary: `Summary ${CANARIES.output}` };
    vi.mocked(getBriefModel).mockReturnValue(fakeModel({ model: "gpt-6-luna", brief, llmMs: 40, validationMs: 2 }));

    const res = await analyze();
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(BriefResponseSchema.safeParse(body).success).toBe(true);
    // The brief itself does contain the PR's and model's content: that is the product.
    expect(body.brief.brief.summary).toContain(CANARIES.output);
    expect(body.brief.estimated_cost).toEqual({ usd: expect.any(Number), is_estimate: true, pricing_as_of: PRICING_AS_OF });
    expect(body.timing.llm_ms).toBe(40);
    expect(body.timing.total_ms).toBeGreaterThanOrEqual(0);

    const e = onlyEvent();
    expect(e).toMatchObject({
      event: "analysis",
      outcome: "success",
      http_status: 200,
      failure_stage: null,
      reason: null,
      provider: "openai",
      model: "gpt-6-luna",
      reasoning_effort: "none",
      llm_ms: 40,
      github_requests: 2,
      github_redirects: 0,
      github_rate_limit_remaining: 59,
      files_considered: 3,
      truncated: false,
      input_tokens: FAKE_USAGE.input_tokens,
      output_tokens: FAKE_USAGE.output_tokens,
      usage_status: "reported",
      cost_status: "estimated",
      pricing_as_of: PRICING_AS_OF,
      schema_valid: true,
    });
    expect(e.estimated_cost_usd).toBeCloseTo(body.brief.estimated_cost.usd, 12);
    for (const key of ["total_ms", "github_ms", "normalization_ms", "validation_ms", "evidence_chars"]) {
      expect(e[key], key).toEqual(expect.any(Number));
    }
    expectNoLeak();
  });

  it("an unpriced served model gives unknown cost, never zero", async () => {
    serve();
    vi.mocked(getBriefModel).mockReturnValue(fakeModel({ model: "gpt-test-model" }));
    const body = await (await analyze()).json();
    expect(body.brief.estimated_cost).toBeNull();
    expect(onlyEvent()).toMatchObject({ model: "gpt-test-model", estimated_cost_usd: null, cost_status: "unknown", pricing_as_of: null });
  });

  it("invalid output: counts the paid call and records the reason, not the text", async () => {
    serve();
    vi.mocked(getBriefModel).mockReturnValue(
      fakeModel({ ok: false, kind: "output_invalid", reason: "schema_mismatch", model: "gpt-6-luna", usage: FAKE_USAGE, llmMs: 30, validationMs: 1 }),
    );
    expect((await analyze()).status).toBe(502);
    expect(onlyEvent()).toMatchObject({
      outcome: "output_invalid",
      http_status: 502,
      failure_stage: "model",
      reason: "schema_mismatch",
      schema_valid: false,
      usage_status: "reported",
      cost_status: "estimated",
    });
    expectNoLeak();
  });

  it("provider failure: unknown usage and cost stay null", async () => {
    serve();
    vi.mocked(getBriefModel).mockReturnValue(
      fakeModel({ ok: false, kind: "provider_unavailable", reason: "rate_limited", model: null, usage: null, llmMs: 12, validationMs: null }),
    );
    expect((await analyze()).status).toBe(503);
    expect(onlyEvent()).toMatchObject({
      outcome: "provider_unavailable",
      failure_stage: "model",
      reason: "rate_limited",
      input_tokens: null,
      output_tokens: null,
      usage_status: "unknown",
      estimated_cost_usd: null,
      cost_status: "unknown",
      validation_ms: null,
      schema_valid: null,
    });
    expectNoLeak();
  });

  it("GitHub failure: records the GitHub reason and no model fields", async () => {
    mockFetch({ [`${API}${PULL_PATH}`]: status(404, {}, `not found ${CANARIES.body}`) });
    const model = fakeModel();
    vi.mocked(getBriefModel).mockReturnValue(model);
    expect((await analyze()).status).toBe(404);
    expect(model.calls).toHaveLength(0);
    expect(onlyEvent()).toMatchObject({
      outcome: "pr_not_found",
      failure_stage: "github",
      reason: "not_found",
      github_requests: 1,
      normalization_ms: null,
      llm_ms: null,
      files_considered: null,
    });
    expectNoLeak();
  });

  it("request failure: records the request reason, never the input", async () => {
    vi.mocked(getBriefModel).mockReturnValue(fakeModel());
    const res = await POST(
      new Request("http://localhost/api/analyze", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ url: `https://evil.example/${CANARIES.body}` }),
      }),
    );
    expect(res.status).toBe(400);
    expect(onlyEvent()).toMatchObject({ outcome: "invalid_pr_url", failure_stage: "request", reason: "bad_pr_url", github_ms: null });
    expectNoLeak();
  });

  it("unexpected exception: logs a fixed code, not the error message", async () => {
    serve();
    vi.mocked(getBriefModel).mockReturnValue({
      async generateBrief() {
        throw new Error(`boom ${CANARIES.patch}`);
      },
    });
    expect((await analyze()).status).toBe(500);
    expect(onlyEvent()).toMatchObject({ outcome: "internal_error", reason: "unexpected_exception" });
    expectNoLeak();
  });
});
