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

describe("source guards", () => {
  it("never uses dangerouslySetInnerHTML", () => {
    const offenders = appFiles.filter((f) => readFileSync(f, "utf8").includes("dangerouslySetInnerHTML"));
    expect(offenders.map((f) => relative(ROOT, f))).toEqual([]);
  });

  it("has no network call in server code (lib/ and app/api/)", () => {
    const serverFiles = appFiles.filter((f) => {
      const rel = relative(ROOT, f);
      return rel.startsWith("lib") || rel.startsWith(join("app", "api"));
    });
    expect(serverFiles.length).toBeGreaterThan(0);
    const offenders = serverFiles.filter((f) => /\bfetch\s*\(|\bhttps?\.request\b|XMLHttpRequest/.test(readFileSync(f, "utf8")));
    expect(offenders.map((f) => relative(ROOT, f))).toEqual([]);
  });

  it("config module is server-only", () => {
    expect(readFileSync(join(ROOT, "lib", "config.ts"), "utf8")).toMatch(/^import "server-only";/m);
  });
});
