"use client";

import { useState, type FormEvent } from "react";

// Everything shown here is rendered as React text nodes. No server or PR
// content is ever injected as HTML.

type ParsedResult = {
  status: "parsed";
  pr: { owner: string; repo: string; number: number };
  wouldFetch: string;
};

type ErrorResult = {
  status: "error";
  error: { category: string; message: string };
};

type ViewState =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "parsed"; result: ParsedResult }
  | { kind: "error"; category: string; message: string };

export function AnalyzeForm() {
  const [url, setUrl] = useState("");
  const [view, setView] = useState<ViewState>({ kind: "idle" });

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setView({ kind: "loading" });
    try {
      const res = await fetch("/api/analyze", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url }),
      });
      const data = (await res.json()) as ParsedResult | ErrorResult;
      if (data.status === "parsed") {
        setView({ kind: "parsed", result: data });
      } else {
        setView({ kind: "error", category: data.error.category, message: data.error.message });
      }
    } catch {
      setView({ kind: "error", category: "internal_error", message: "The request failed." });
    }
  }

  return (
    <div className="flex w-full flex-col gap-6">
      <form onSubmit={onSubmit} className="flex flex-col gap-3 sm:flex-row">
        <label htmlFor="pr-url" className="sr-only">
          GitHub pull request URL
        </label>
        <input
          id="pr-url"
          name="url"
          type="text"
          inputMode="url"
          autoComplete="off"
          spellCheck={false}
          required
          maxLength={2048}
          placeholder="https://github.com/owner/repo/pull/123"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          className="flex-1 rounded-md border border-zinc-300 bg-white px-3 py-2 font-mono text-sm dark:border-zinc-700 dark:bg-zinc-900"
        />
        <button
          type="submit"
          disabled={view.kind === "loading"}
          className="rounded-md bg-zinc-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-50 dark:bg-zinc-100 dark:text-zinc-900"
        >
          {view.kind === "loading" ? "Checking…" : "Check URL"}
        </button>
      </form>

      <div aria-live="polite">
        {view.kind === "parsed" && (
          <dl className="grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1 text-sm">
            <dt className="text-zinc-500">Owner</dt>
            <dd className="font-mono">{view.result.pr.owner}</dd>
            <dt className="text-zinc-500">Repository</dt>
            <dd className="font-mono">{view.result.pr.repo}</dd>
            <dt className="text-zinc-500">Pull request</dt>
            <dd className="font-mono">#{view.result.pr.number}</dd>
            <dt className="text-zinc-500">Would fetch</dt>
            <dd className="break-all font-mono">{view.result.wouldFetch}</dd>
          </dl>
        )}
        {view.kind === "error" && (
          <p role="alert" className="text-sm text-red-700 dark:text-red-400">
            {view.message}
          </p>
        )}
      </div>
    </div>
  );
}
