// The production smoke test (RUNBOOK.md "Production smoke test"), as checks a
// test can run against a fake server. scripts/smoke.ts runs it for real.
//
// Uses no secret and prints no response body: only statuses, fixed field
// values, timings and the request reference. The base URL is the operator's
// own deployment; every request goes to a fixed path on it.

import { BriefResponseSchema } from "@/lib/schemas/change-brief";

export const SMOKE_PR = "https://github.com/nodejs/node/pull/66442";
// Must be refused by the URL parser: no GitHub call, no model call, no cost.
export const SAFE_FAILURE_URL = "https://github.com.evil.example/a/b/pull/1";

export type Check = { name: string; ok: boolean; detail: string };

type Send = (url: string, init?: RequestInit) => Promise<Response>;

async function jsonOrNull(res: Response): Promise<unknown> {
  try {
    return await res.json();
  } catch {
    return null;
  }
}

function field(obj: unknown, ...path: string[]): unknown {
  let cur = obj;
  for (const key of path) {
    if (cur === null || typeof cur !== "object") return undefined;
    cur = (cur as Record<string, unknown>)[key];
  }
  return cur;
}

export async function runSmoke(base: string, opts: { analyze: boolean }, send: Send): Promise<Check[]> {
  const origin = new URL(base).origin;
  const checks: Check[] = [];
  const check = (name: string, ok: boolean, detail: string) => checks.push({ name, ok, detail });

  const home = await send(`${origin}/`, { redirect: "manual" });
  check("home page", home.status === 200, `HTTP ${home.status}`);
  const csp = home.headers.get("content-security-policy") ?? "";
  check("security headers", csp.includes("frame-ancestors 'none'") && home.headers.get("x-content-type-options") === "nosniff", csp === "" ? "no CSP" : "CSP present");

  const healthRes = await send(`${origin}/api/health`);
  const health = await jsonOrNull(healthRes);
  check("health", healthRes.status === 200 && field(health, "status") === "ok", `HTTP ${healthRes.status}`);
  check("ready", field(health, "ready") === true, `ready=${String(field(health, "ready"))}`);
  check("service enabled", field(health, "service") === "enabled", `service=${String(field(health, "service"))}`);
  const backend = field(health, "rateLimit", "backend");
  const local = ["localhost", "127.0.0.1", "[::1]"].includes(new URL(origin).hostname);
  check("rate-limit store", local ? backend !== "not_configured" : backend === "upstash", `backend=${String(backend)}`);
  check("model", typeof field(health, "llm", "model") === "string", `model=${String(field(health, "llm", "model"))}`);

  const post = (url: string) =>
    send(`${origin}/api/analyze`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ url }),
    });

  const refused = await post(SAFE_FAILURE_URL);
  const refusedBody = await jsonOrNull(refused);
  check(
    "safe failure (lookalike host refused)",
    refused.status === 400 && field(refusedBody, "error", "category") === "invalid_pr_url",
    `HTTP ${refused.status}, reference ${refused.headers.get("x-request-id") ?? "none"}`,
  );

  if (opts.analyze) {
    const started = Date.now();
    const res = await post(SMOKE_PR);
    const parsed = BriefResponseSchema.safeParse(await jsonOrNull(res));
    const ref = res.headers.get("x-request-id") ?? "none";
    if (res.status === 200 && parsed.success) {
      const b = parsed.data.brief;
      const cost = b.estimated_cost === null ? "unknown" : `~$${b.estimated_cost.usd.toFixed(6)} (estimate)`;
      check("one real analysis", true, `model ${b.model}, ${Date.now() - started} ms, cost ${cost}, reference ${ref}`);
    } else {
      check("one real analysis", false, `HTTP ${res.status}, schema ${parsed.success ? "valid" : "invalid"}, reference ${ref}`);
    }
  }
  return checks;
}
