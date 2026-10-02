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
// Everything that ships or runs outside tests (scripts/ includes .mjs).
const shippedFiles = [
  ...appFiles,
  ...readdirSync(join(ROOT, "scripts"))
    .filter((n) => /\.(ts|mjs)$/.test(n))
    .map((n) => join(ROOT, "scripts", n)),
];

const NETWORK_CALL = /\bfetch\s*\(|\bhttps?\.request\b|\bhttps?\.get\b|XMLHttpRequest|\bnet\.connect\b|WebSocket/;
const GITHUB_CLIENT = join("lib", "github", "client.ts");
// The browser form posts to this app's own API route. It is the only other
// fetch call, and its target is a fixed same-origin path.
const BROWSER_FORM = join("app", "analyze-form.tsx");

describe("source guards", () => {
  it("never uses dangerouslySetInnerHTML", () => {
    const offenders = appFiles.filter((f) => readFileSync(f, "utf8").includes("dangerouslySetInnerHTML"));
    expect(offenders.map((f) => relative(ROOT, f))).toEqual([]);
  });

  it("calls fetch only from lib/github/client.ts", () => {
    expect(shippedFiles.length).toBeGreaterThan(0);
    const callers = shippedFiles.filter((f) => NETWORK_CALL.test(readFileSync(f, "utf8")));
    expect(callers.map((f) => relative(ROOT, f)).sort()).toEqual([BROWSER_FORM, GITHUB_CLIENT].sort());
    const formCalls = readFileSync(join(ROOT, BROWSER_FORM), "utf8").match(/\bfetch\s*\([^,)]*/g);
    expect(formCalls).toEqual(['fetch("/api/analyze"']);
  });

  it("reads GITHUB_TOKEN only in the client (value) and config (presence)", () => {
    const readers = shippedFiles.filter((f) => /GITHUB_TOKEN/.test(readFileSync(f, "utf8")));
    expect(readers.map((f) => relative(ROOT, f)).sort()).toEqual([join("lib", "config.ts"), GITHUB_CLIENT].sort());
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
