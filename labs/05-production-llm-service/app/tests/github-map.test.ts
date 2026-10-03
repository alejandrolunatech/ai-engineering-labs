import { describe, expect, it } from "vitest";
import { mapFiles, mapPull } from "@/lib/github/map";
import { fixture, makeFiles } from "./helpers/github";

describe("mapPull", () => {
  it("keeps only the allowlisted fields", () => {
    expect(mapPull(fixture("pull-small.json"))).toEqual({
      title: "Add retry jitter to webhook sender",
      body: "Adds jitter to webhook retries.\n\n## Testing\n- unit tests added",
      state: "open",
      draft: false,
      merged: false,
      baseRef: "main",
      headRef: "retry-jitter",
      additions: 14,
      deletions: 3,
      changedFiles: 3,
    });
  });

  it("drops extra unknown fields, including injected ones", () => {
    const raw = { ...(fixture("pull-small.json") as object), surprise: { email: "x@example.invalid" }, __proto__x: 1 };
    const text = JSON.stringify(mapPull(raw));
    expect(text).not.toContain("surprise");
    expect(text).not.toContain("example.invalid");
  });

  it("accepts over-long title and refs (the normalizer truncates them)", () => {
    const raw = { ...(fixture("pull-small.json") as object), title: "t".repeat(5000), base: { ref: "b".repeat(5000) } };
    expect(mapPull(raw)).toMatchObject({ title: "t".repeat(5000), baseRef: "b".repeat(5000) });
  });

  it("defaults a missing draft flag to false", () => {
    const raw = { ...(fixture("pull-small.json") as Record<string, unknown>) };
    delete raw.draft;
    expect(mapPull(raw)?.draft).toBe(false);
  });

  it.each([
    ["null", null],
    ["array", []],
    ["missing title", { ...(fixture("pull-small.json") as object), title: undefined }],
    ["bad state", { ...(fixture("pull-small.json") as object), state: "weird" }],
    ["negative count", { ...(fixture("pull-small.json") as object), changed_files: -1 }],
  ])("rejects %s", (_label, raw) => {
    expect(mapPull(raw)).toBeNull();
  });
});

describe("mapFiles", () => {
  it("keeps filename/status/additions/deletions/patch only", () => {
    const files = mapFiles(fixture("files-small.json"))!;
    expect(Object.keys(files[0]).sort()).toEqual(["additions", "deletions", "filename", "patch", "status"]);
    expect(Object.keys(files[2]).sort()).toEqual(["additions", "deletions", "filename", "status"]);
  });

  it("accepts an over-long filename (the normalizer truncates it)", () => {
    const files = mapFiles([{ filename: "f".repeat(4096), status: "added", additions: 1, deletions: 0 }]);
    expect(files?.[0].filename).toHaveLength(4096);
  });

  it.each([
    ["object instead of array", {}],
    ["unknown status", [{ filename: "a", status: "exploded", additions: 0, deletions: 0 }]],
    ["more than 100 entries", makeFiles(101)],
  ])("rejects %s", (_label, raw) => {
    expect(mapFiles(raw)).toBeNull();
  });
});
