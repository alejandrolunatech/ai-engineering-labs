import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { describe, expect, it } from "vitest";

// Static guards over the source tree. These catch regressions cheaply; they are
// not a substitute for code review.

const ROOT = join(__dirname, "..");

function sourceFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return sourceFiles(path);
    return /\.(ts|tsx)$/.test(name) ? [path] : [];
  });
}

const appFiles = [...sourceFiles(join(ROOT, "app")), ...sourceFiles(join(ROOT, "lib"))];
// Everything that ships or runs outside tests (scripts/ includes .mjs; evals/
// runs through scripts/run-evals.ts).
const shippedFiles = [
  ...appFiles,
  ...sourceFiles(join(ROOT, "evals")),
  ...readdirSync(join(ROOT, "scripts"))
    .filter((n) => /\.(ts|mjs)$/.test(n))
    .map((n) => join(ROOT, "scripts", n)),
];

// The OpenAI SDK makes its own HTTPS calls inside node_modules; it is fenced
// by the import guard below (only lib/llm/openai.ts may import it).
const NETWORK_CALL = /\bfetch\s*\(|\bhttps?\.request\b|\bhttps?\.get\b|XMLHttpRequest|\bnet\.connect\b|WebSocket/;
const GITHUB_CLIENT = join("lib", "github", "client.ts");
// The browser form posts to this app's own API route. It is the only other
// fetch call, and its target is a fixed same-origin path.
const BROWSER_FORM = join("app", "analyze-form.tsx");
// The rate-limit store (Phase 6). Its target is the Upstash URL from server
// configuration, never anything from the request.
const RATE_LIMIT = join("lib", "rate-limit.ts");
// The operator's smoke test (Phase 7). Not shipped in the app; it calls fixed
// paths on the deployment URL the operator passes (scripts/smoke-lib.ts).
const SMOKE = join("scripts", "smoke.ts");

describe("source guards", () => {
  it("never uses dangerouslySetInnerHTML", () => {
    const offenders = appFiles.filter((f) => readFileSync(f, "utf8").includes("dangerouslySetInnerHTML"));
    expect(offenders.map((f) => relative(ROOT, f))).toEqual([]);
  });

  it("calls fetch only from lib/github/client.ts, the rate-limit store and the smoke script", () => {
    expect(shippedFiles.length).toBeGreaterThan(0);
    const callers = shippedFiles.filter((f) => NETWORK_CALL.test(readFileSync(f, "utf8")));
    expect(callers.map((f) => relative(ROOT, f)).sort()).toEqual([BROWSER_FORM, GITHUB_CLIENT, RATE_LIMIT, SMOKE].sort());
    const formCalls = readFileSync(join(ROOT, BROWSER_FORM), "utf8").match(/\bfetch\s*\([^,)]*/g);
    expect(formCalls).toEqual(['fetch("/api/analyze"']);
    const storeCalls = readFileSync(join(ROOT, RATE_LIMIT), "utf8").match(/\bfetch\s*\([^,]*/g);
    expect(storeCalls).toEqual(["fetch(endpoint"]);
    const smokeCalls = readFileSync(join(ROOT, SMOKE), "utf8").match(/\bfetch\s*\([^,]*/g);
    expect(smokeCalls).toEqual(["fetch(url"]);
  });

  it("reads the Upstash credentials only in config (presence) and the rate-limit store (value)", () => {
    const readers = shippedFiles.filter((f) => /UPSTASH_REDIS_REST_TOKEN|KV_REST_API_TOKEN/.test(readFileSync(f, "utf8")));
    expect(readers.map((f) => relative(ROOT, f)).sort()).toEqual([join("lib", "config.ts"), RATE_LIMIT].sort());
  });

  it("the rate-limit module is server-only", () => {
    expect(readFileSync(join(ROOT, RATE_LIMIT), "utf8")).toMatch(/^import "server-only";/m);
  });

  it("reads GITHUB_TOKEN only in the client (value) and config (presence)", () => {
    const readers = shippedFiles.filter((f) => /GITHUB_TOKEN/.test(readFileSync(f, "utf8")));
    expect(readers.map((f) => relative(ROOT, f)).sort()).toEqual([join("lib", "config.ts"), GITHUB_CLIENT].sort());
  });

  it("imports the OpenAI SDK only in lib/llm/openai.ts", () => {
    const importers = shippedFiles.filter((f) => /from\s+["']openai["']|require\(["']openai["']\)/.test(readFileSync(f, "utf8")));
    expect(importers.map((f) => relative(ROOT, f))).toEqual([join("lib", "llm", "openai.ts")]);
  });

  it("reads OPENAI_API_KEY only in config (presence) and lib/llm/index.ts (value)", () => {
    const readers = shippedFiles.filter((f) => /OPENAI_API_KEY/.test(readFileSync(f, "utf8")));
    expect(readers.map((f) => relative(ROOT, f)).sort()).toEqual([join("lib", "config.ts"), join("lib", "llm", "index.ts")].sort());
  });

  it("the model modules are server-only", () => {
    for (const rel of [join("lib", "llm", "openai.ts"), join("lib", "llm", "index.ts")]) {
      expect(readFileSync(join(ROOT, rel), "utf8")).toMatch(/^import "server-only";/m);
    }
  });

  it("gives the model no tools", () => {
    expect(readFileSync(join(ROOT, "lib", "llm", "openai.ts"), "utf8")).not.toMatch(/\btools\s*:/);
  });

  it("uses no NEXT_PUBLIC_ variables", () => {
    const offenders = shippedFiles.filter((f) => readFileSync(f, "utf8").includes("NEXT_PUBLIC_"));
    expect(offenders.map((f) => relative(ROOT, f))).toEqual([]);
  });

  it("the GitHub client and ingestion modules are server-only", () => {
    for (const rel of [GITHUB_CLIENT, join("lib", "github", "ingest.ts")]) {
      expect(readFileSync(join(ROOT, rel), "utf8")).toMatch(/^import "server-only";/m);
    }
  });

  it("config module is server-only", () => {
    expect(readFileSync(join(ROOT, "lib", "config.ts"), "utf8")).toMatch(/^import "server-only";/m);
  });
});
