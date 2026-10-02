"use client";

import { useState, type FormEvent } from "react";
import type { NormalizedResponse } from "@/lib/schemas/normalized-pr";

// Everything shown here is rendered as React text nodes. No server or PR
// content is ever injected as HTML.
//
// Phase 2 development view: shows the normalized evidence envelope (metadata,
// coverage, limitations). Patch and body text are not displayed. Phase 3
// replaces this with the ChangeBrief.

type ErrorResult = {
  status: "error";
  error: { category: string; message: string };
};

type ViewState =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "normalized"; result: NormalizedResponse }
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
      const data = (await res.json()) as NormalizedResponse | ErrorResult;
      if (data.status === "normalized") {
        setView({ kind: "normalized", result: data });
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
          {view.kind === "loading" ? "Fetching…" : "Fetch PR"}
        </button>
      </form>

      <div aria-live="polite">
        {view.kind === "normalized" && <EvidenceView result={view.result} />}
        {view.kind === "error" && (
          <p role="alert" className="text-sm text-red-700 dark:text-red-400">
            {view.message}
          </p>
        )}
      </div>
    </div>
  );
}

function EvidenceView({ result }: { result: NormalizedResponse }) {
  const e = result.evidence;
  return (
    <div className="flex flex-col gap-4 text-sm">
      <dl className="grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1">
        <dt className="text-zinc-500">Pull request</dt>
        <dd className="font-mono">
          {e.pr.owner}/{e.pr.repo}#{e.pr.number}
        </dd>
        <dt className="text-zinc-500">Title</dt>
        <dd className="break-words">{e.title}</dd>
        <dt className="text-zinc-500">State</dt>
        <dd>
          {e.merged ? "merged" : e.state}
          {e.draft ? " (draft)" : ""}
        </dd>
        <dt className="text-zinc-500">Files</dt>
        <dd>
          {e.coverage.files_considered} of {e.coverage.files_total} considered
        </dd>
        <dt className="text-zinc-500">Evidence</dt>
        <dd>
          {e.coverage.chars_included} of {e.coverage.chars_available} characters included
        </dd>
        <dt className="text-zinc-500">Truncated</dt>
        <dd>{e.truncated ? "yes" : "no"}</dd>
      </dl>
      {e.limitations.length > 0 && (
        <ul className="list-disc pl-5 text-zinc-600 dark:text-zinc-400">
          {e.limitations.map((text, i) => (
            <li key={i}>{text}</li>
          ))}
        </ul>
      )}
      <ol className="list-decimal pl-5 font-mono text-xs">
        {e.files.map((file, i) => (
          <li key={i} className="break-all">
            {file.filename} — {file.status}, {file.patch === null ? "no patch" : `${file.patch.length} chars`}
            {file.patch_truncated ? " (truncated)" : ""}
          </li>
        ))}
      </ol>
    </div>
  );
}
