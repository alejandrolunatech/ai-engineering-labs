import { afterEach, beforeEach, describe, expect, it, vi, type MockInstance } from "vitest";
import { POST } from "@/app/api/analyze/route";
import { getBriefModel } from "@/lib/llm";
import { PROMPT_VERSION } from "@/lib/llm/prompt";
import { BriefResponseSchema } from "@/lib/schemas/change-brief";
import { API, filesFor, fixture, json, mockFetch } from "./helpers/github";
import { FAKE_USAGE, VALID_MODEL_BRIEF, fakeModel, type FakeModel } from "./helpers/llm";

// POST /api/analyze — the model step, with mocked GitHub and a fake model.

vi.mock("@/lib/llm", () => ({ getBriefModel: vi.fn() }));

const PR_URL = "https://github.com/octo-org/widgets/pull/42";
const PULL_PATH = "/repos/octo-org/widgets/pulls/42";

let spy: MockInstance<typeof fetch>;

function serveSmallPr() {
  spy = mockFetch({ [`${API}${PULL_PATH}`]: json(fixture("pull-small.json")), [filesFor(PULL_PATH)]: json(fixture("files-small.json")) });
}

function useModel(m: FakeModel | null) {
  vi.mocked(getBriefModel).mockReturnValue(m);
  return m;
}

function analyze() {
  return POST(
    new Request("http://localhost/api/analyze", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ url: PR_URL }),
    }),
  );
}

async function expectError(res: Response, httpStatus: number, category: string) {
  expect(res.status).toBe(httpStatus);
  const body = await res.json();
  expect(body.status).toBe("error");
  expect(body.error.category).toBe(category);
  expect(Object.keys(body.error).sort()).toEqual(["category", "message"]);
}

beforeEach(() => serveSmallPr());
afterEach(() => vi.restoreAllMocks());

describe("POST /api/analyze — brief", () => {
  it("returns a schema-valid ChangeBrief with server-written fields", async () => {
    useModel(fakeModel());
    const res = await analyze();
    expect(res.status).toBe(200);
    expect(res.headers.get("cache-control")).toBe("no-store");
    const body = await res.json();
    expect(BriefResponseSchema.safeParse(body).success).toBe(true);
    expect(body.brief).toMatchObject({
      pr: { owner: "octo-org", repo: "widgets", number: 42 },
      schema_version: "0.1",
      prompt_version: PROMPT_VERSION,
      model: "gpt-test-model",
      usage: FAKE_USAGE,
      estimated_cost: null,
      ai_generated: true,
      truncated: false,
      files_considered: 3,
      files_total: 3,
      brief: VALID_MODEL_BRIEF,
    });
  });

  it("calls the model exactly once per analysis", async () => {
    const m = useModel(fakeModel())!;
    await analyze();
    expect(m.calls).toHaveLength(1);
  });

  it("keeps unknown usage as null in the response, never zero", async () => {
    const unknown = { input_tokens: null, cached_input_tokens: null, output_tokens: null, reasoning_tokens: null };
    useModel(fakeModel({ usage: unknown }));
    const { brief } = await (await analyze()).json();
    expect(brief.usage).toEqual(unknown);
  });
});

describe("POST /api/analyze — model failures map to safe categories", () => {
  it("no model configured -> 503 provider_unavailable, before any GitHub request", async () => {
    useModel(null);
    await expectError(await analyze(), 503, "provider_unavailable");
    expect(spy).not.toHaveBeenCalled();
  });

  it.each(["timeout", "auth", "rate_limited", "bad_request", "upstream_5xx", "network_error"] as const)(
    "provider failure (%s) -> 503 provider_unavailable",
    async (reason) => {
      useModel(fakeModel({ ok: false, kind: "provider_unavailable", reason, model: null, usage: null, llmMs: 1 }));
      await expectError(await analyze(), 503, "provider_unavailable");
    },
  );

  it.each(["incomplete_max_tokens", "refusal", "malformed_json", "schema_mismatch", "empty_output"] as const)(
    "invalid output (%s) -> 502 output_invalid",
    async (reason) => {
      useModel(fakeModel({ ok: false, kind: "output_invalid", reason, model: "m", usage: null, llmMs: 1 }));
      await expectError(await analyze(), 502, "output_invalid");
    },
  );

  it("a brief that fails the final schema check never reaches the client", async () => {
    // The adapter validates too; this checks the route's own final check.
    useModel(fakeModel({ brief: { ...VALID_MODEL_BRIEF, summary: 42 } as never }));
    const res = await analyze();
    await expectError(res, 502, "output_invalid");
  });
});
