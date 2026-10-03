import { readFileSync } from "node:fs";
import { join } from "node:path";
import { vi, type MockInstance } from "vitest";

// Test-only helpers: a fetch mock that answers from a URL -> response table and
// fails the test on any URL it does not know. No network is ever used.

export const API = "https://api.github.com";

export function fixture(name: string): unknown {
  return JSON.parse(readFileSync(join(__dirname, "..", "fixtures", "github", name), "utf8"));
}

export function json(body: unknown, init: { status?: number; headers?: Record<string, string> } = {}): Response {
  return new Response(JSON.stringify(body), {
    status: init.status ?? 200,
    headers: { "content-type": "application/json", "x-ratelimit-remaining": "59", ...init.headers },
  });
}

export function status(code: number, headers: Record<string, string> = {}, body: string | null = "GITHUB-ERROR-TEXT-MARKER"): Response {
  return new Response(body, { status: code, headers });
}

export function redirect(location: string, code = 301): Response {
  return new Response(null, { status: code, headers: { location } });
}

type Responder = Response | ((init: RequestInit | undefined) => Response | Promise<Response>);

// A fetch implementation answering from a URL -> response table.
export function fetchFrom(routes: Record<string, Responder>): typeof fetch {
  return async (input, init) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    const route = routes[url];
    if (route === undefined) throw new Error(`unexpected fetch in test: ${url}`);
    return typeof route === "function" ? route(init) : route.clone();
  };
}

export function mockFetch(routes: Record<string, Responder>): MockInstance<typeof fetch> {
  return vi.spyOn(globalThis, "fetch").mockImplementation(fetchFrom(routes));
}

export function filesFor(path: string): string {
  return `${API}${path}/files?per_page=50&page=1`;
}

// Synthetic GitHub file entries.
export function makeFiles(count: number, patch: (i: number) => string | undefined = (i) => `@@ -1 +1 @@\n+line ${i}`) {
  return Array.from({ length: count }, (_, i) => {
    const p = patch(i);
    return {
      sha: "f".repeat(40),
      filename: `src/file-${i + 1}.ts`,
      status: "modified",
      additions: 1,
      deletions: 0,
      changes: 1,
      blob_url: `https://github.com/o/r/blob/x/src/file-${i + 1}.ts`,
      ...(p === undefined ? {} : { patch: p }),
    };
  });
}

// N lines of `width` characters each, joined by "\n".
export function lines(n: number, width = 99): string {
  return Array.from({ length: n }, (_, i) => `+${String(i).padStart(width - 1, "x")}`).join("\n");
}
