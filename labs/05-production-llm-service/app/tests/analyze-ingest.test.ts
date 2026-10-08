import { afterEach, describe, expect, it, vi, type MockInstance } from "vitest";
import { POST } from "@/app/api/analyze/route";
import { MAX_REQUESTS } from "@/lib/github/client";
import { BriefResponseSchema } from "@/lib/schemas/change-brief";
import { beforeEach } from "vitest";
import { API, filesFor, fixture, json, makeFiles, mockFetch, redirect, status } from "./helpers/github";
import { getBriefModel } from "@/lib/llm";
import { fakeModel, type FakeModel } from "./helpers/llm";

// The model is faked: no SDK, no network, no API money.
vi.mock("@/lib/llm", () => ({ getBriefModel: vi.fn() }));

// POST /api/analyze end to end with mocked GitHub responses (no network).

const PR_URL = "https://github.com/octo-org/widgets/pull/42";
const PULL_PATH = "/repos/octo-org/widgets/pulls/42";
const PULL = `${API}${PULL_PATH}`;
const FILES = filesFor(PULL_PATH);

let spy: MockInstance<typeof fetch> | undefined;
let model: FakeModel;

beforeEach(() => {
  model = fakeModel();
  vi.mocked(getBriefModel).mockReturnValue(model);
});

afterEach(() => {
  // Request ceiling holds in every test.
  if (spy) expect(spy.mock.calls.length).toBeLessThanOrEqual(MAX_REQUESTS);
  spy = undefined;
  vi.restoreAllMocks();
});

function analyze(url = PR_URL) {
  return POST(
    new Request("http://localhost/api/analyze", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ url }),
    }),
  );
}

async function expectUnavailable(res: Response, httpStatus = 503) {
  expect(res.status).toBe(httpStatus);
  const text = await res.text();
  expect(JSON.parse(text)).toEqual({
    status: "error",
    error: { category: "pr_not_found", message: "That public pull request was not found or is unavailable." },
  });
  expect(text).not.toContain("GITHUB-ERROR-TEXT-MARKER");
  // A GitHub failure never reaches the model.
  expect(model.calls).toHaveLength(0);
}

describe("POST /api/analyze — normalized evidence reaches the model", () => {
  it("fetches exactly the PR and its first files page, and sends the normalized evidence to one model call", async () => {
    spy = mockFetch({ [PULL]: json(fixture("pull-small.json")), [FILES]: json(fixture("files-small.json")) });
    const res = await analyze();
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(BriefResponseSchema.safeParse(body).success).toBe(true);
    expect(body.brief.pr).toEqual({ owner: "octo-org", repo: "widgets", number: 42 });
    expect(spy.mock.calls.map((c) => c[0])).toEqual([PULL, FILES]);
    expect(model.calls).toHaveLength(1);
    expect(model.calls[0].pr).toEqual({ owner: "octo-org", repo: "widgets", number: 42 });
    expect(model.calls[0].files).toHaveLength(3);
    expect(JSON.stringify(model.calls[0])).not.toMatch(/avatar|email|_links|html_url/);
    // The evidence itself is no longer returned to the browser.
    expect(body).not.toHaveProperty("evidence");
  });

  it("carries a large PR as truncated evidence instead of rejecting it, and says so in the brief", async () => {
    const pull = { ...(fixture("pull-small.json") as object), changed_files: 400 };
    spy = mockFetch({ [PULL]: json(pull), [FILES]: json(makeFiles(50)) });
    const res = await analyze();
    expect(res.status).toBe(200);
    const { brief } = await res.json();
    expect(model.calls[0].truncated).toBe(true);
    expect(model.calls[0].coverage).toMatchObject({ files_total: 400, files_considered: 50 });
    expect(brief).toMatchObject({ truncated: true, files_total: 400, files_considered: 50 });
    expect(brief.truncation_limitations.length).toBeGreaterThan(0);
    expect(spy).toHaveBeenCalledTimes(2);
  });

  it("passes untrusted PR text to the model as JSON data, unchanged", async () => {
    spy = mockFetch({ [PULL]: json(fixture("pull-injection.json")), [FILES]: json(fixture("files-injection.json")) });
    const res = await analyze();
    expect(res.status).toBe(200);
    expect(res.headers.get("content-type")).toMatch(/^application\/json/);
    const evidence = model.calls[0];
    expect(evidence.title).toBe((fixture("pull-injection.json") as { title: string }).title);
    expect(evidence.files[0].patch).toContain("<script>alert(document.domain)</script>");
  });

  it("follows a renamed-repository redirect within 3 requests", async () => {
    const moved = `${API}/repositories/5000002/pulls/42`;
    const movedFiles = `${moved}/files?per_page=50&page=1`;
    spy = mockFetch({
      [PULL]: redirect(moved, 301),
      [moved]: json(fixture("pull-small.json")),
      [movedFiles]: json(fixture("files-small.json")),
    });
    const res = await analyze();
    expect(res.status).toBe(200);
    expect(spy.mock.calls.map((c) => c[0])).toEqual([PULL, moved, movedFiles]);
  });

  it("refuses a redirect to another host", async () => {
    spy = mockFetch({ [PULL]: redirect("https://evil.example/repos/octo-org/widgets/pulls/42") });
    await expectUnavailable(await analyze());
    expect(spy).toHaveBeenCalledTimes(1);
  });

  it("refuses a redirect to an unexpected api.github.com path for the files URL", async () => {
    const odd = `${API}/repos/octo-org/widgets/contents/secret`;
    spy = mockFetch({ [PULL]: redirect(odd), [odd]: json(fixture("pull-small.json")) });
    await expectUnavailable(await analyze());
    expect(spy).toHaveBeenCalledTimes(2);
  });

  it("refuses a second redirect (on the files request)", async () => {
    const moved = `${API}/repositories/5000002/pulls/42`;
    spy = mockFetch({
      [PULL]: redirect(moved),
      [moved]: json(fixture("pull-small.json")),
      [`${moved}/files?per_page=50&page=1`]: redirect(`${API}/repositories/9/pulls/42/files`),
    });
    await expectUnavailable(await analyze());
    expect(spy).toHaveBeenCalledTimes(3);
  });
});

describe("POST /api/analyze — upstream failures", () => {
  it("GitHub 404 -> 404 pr_not_found", async () => {
    spy = mockFetch({ [PULL]: status(404) });
    await expectUnavailable(await analyze(), 404);
  });

  it("GitHub 404 on the files request -> 404 pr_not_found", async () => {
    spy = mockFetch({ [PULL]: json(fixture("pull-small.json")), [FILES]: status(404) });
    await expectUnavailable(await analyze(), 404);
  });

  it.each([
    ["403 rate limit", () => status(403, { "x-ratelimit-remaining": "0" })],
    ["403 forbidden", () => status(403)],
    ["401", () => status(401)],
    ["429", () => status(429, { "retry-after": "60" })],
    ["500", () => status(500)],
    ["503", () => status(503)],
    ["malformed JSON", () => new Response("{oops GITHUB-ERROR-TEXT-MARKER", { status: 200 })],
    ["wrong JSON shape", () => json({ message: "GITHUB-ERROR-TEXT-MARKER" })],
    ["oversized response", () => json({}, { headers: { "content-length": String(3 * 1024 * 1024) } })],
    [
      "timeout",
      () => {
        throw new DOMException("timeout", "TimeoutError");
      },
    ],
  ])("%s -> 503 unavailable", async (_label, respond) => {
    spy = mockFetch({ [PULL]: respond });
    await expectUnavailable(await analyze());
    expect(spy).toHaveBeenCalledTimes(1);
  });

  it("files request failing after a good PR response -> 503", async () => {
    spy = mockFetch({ [PULL]: json(fixture("pull-small.json")), [FILES]: status(502) });
    await expectUnavailable(await analyze());
  });
});
