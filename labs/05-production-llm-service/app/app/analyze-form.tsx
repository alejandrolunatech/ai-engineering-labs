"use client";

import { useState, type FormEvent } from "react";
import type { BriefResponse } from "@/lib/schemas/change-brief";

// Everything shown here is rendered as React text nodes. No server or PR
// content is ever injected as HTML.
//
// The validated ChangeBrief. It is always labelled AI-generated, and
// truncation and uncertainty are always shown. Phase 7: example link, loading
// text, one actionable message per error category, and the request reference.

type ErrorResult = {
  status: "error";
  error: { category: string; message: string };
};

type Failure = { message: string; action: string; requestId: string | null };

type ViewState =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "brief"; result: BriefResponse; requestId: string | null }
  | { kind: "error"; failure: Failure };

// A known public PR that makes a short brief (the G0 / smoke-test PR).
const EXAMPLE_URL = "https://github.com/nodejs/node/pull/66442";

// Phase 7: what each server error category means for the person, and what to
// do next. Only fixed text: nothing from the response body is shown except the
// category it names.
function failureFor(category: string, httpStatus: number, retryAfterSec: number | null): Omit<Failure, "requestId"> {
  const later =
    retryAfterSec === null
      ? "Try again later."
      : retryAfterSec < 90
        ? "Try again in a minute."
        : `Try again in about ${Math.ceil(retryAfterSec / 60)} minutes.`;
  switch (category) {
    case "invalid_pr_url":
      return {
        message: "That is not a public GitHub pull request link.",
        action: "Use the form https://github.com/owner/repo/pull/123.",
      };
    case "pr_not_found":
      return httpStatus === 404
        ? {
            message: "That pull request was not found.",
            action: "Check the link. Private repositories are not supported.",
          }
        : { message: "GitHub is not answering right now.", action: "Try again in a minute." };
    case "request_too_large":
      return { message: "The request is too large.", action: "Paste only the pull request link." };
    case "rate_limited":
      return { message: "The request limit has been reached.", action: later };
    case "provider_unavailable":
      return { message: "The AI model is not answering right now.", action: "Try again in a minute." };
    case "output_invalid":
      return {
        message: "The model's answer failed our checks, so it is not shown.",
        action: "Try again. If it happens again, this pull request may be unusual.",
      };
    case "service_disabled":
      return { message: "ChangeBrief is paused for maintenance.", action: later };
    default:
      return { message: "Something went wrong on our side.", action: "Try again in a minute." };
  }
}

function retryAfter(res: Response): number | null {
  const raw = res.headers.get("retry-after");
  if (raw === null || !/^\d{1,6}$/.test(raw)) return null;
  return Number(raw);
}

export function AnalyzeForm() {
  const [url, setUrl] = useState("");
  const [view, setView] = useState<ViewState>({ kind: "idle" });

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setView({ kind: "loading" });
    let res: Response;
    try {
      res = await fetch("/api/analyze", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url: url.trim() }),
      });
    } catch {
      setView({
        kind: "error",
        failure: { message: "Could not reach ChangeBrief.", action: "Check your connection and try again.", requestId: null },
      });
      return;
    }
    const requestId = res.headers.get("x-request-id");
    let data: BriefResponse | ErrorResult | null = null;
    try {
      data = (await res.json()) as BriefResponse | ErrorResult;
    } catch {
      // Not our JSON: a platform error page (paused project, function timeout).
    }
    if (data?.status === "brief") {
      setView({ kind: "brief", result: data, requestId });
    } else {
      const category = data?.status === "error" ? data.error.category : "internal_error";
      setView({ kind: "error", failure: { ...failureFor(category, res.status, retryAfter(res)), requestId } });
    }
  }

  const loading = view.kind === "loading";

  return (
    <div className="flex w-full flex-col gap-6">
      <form onSubmit={onSubmit} className="flex flex-col gap-2">
        <label htmlFor="pr-url" className="text-sm font-medium">
          Public GitHub pull request link
        </label>
        <div className="flex flex-col gap-3 sm:flex-row">
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
            aria-describedby="pr-url-hint"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            className="flex-1 rounded-md border border-zinc-300 bg-white px-3 py-2 font-mono text-sm dark:border-zinc-700 dark:bg-zinc-900"
          />
          <button
            type="submit"
            disabled={loading}
            className="rounded-md bg-zinc-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-50 dark:bg-zinc-100 dark:text-zinc-900"
          >
            {loading ? "Explaining…" : "Explain PR"}
          </button>
        </div>
        <p id="pr-url-hint" className="text-xs text-zinc-500">
          For example{" "}
          <button
            type="button"
            onClick={() => setUrl(EXAMPLE_URL)}
            className="font-mono underline underline-offset-2 hover:text-zinc-700 dark:hover:text-zinc-300"
          >
            {EXAMPLE_URL}
          </button>
        </p>
      </form>

      <div aria-live="polite" aria-busy={loading}>
        {loading && (
          <p className="text-sm text-zinc-600 dark:text-zinc-400">
            Reading the pull request and asking the model. This usually takes 5 to 10 seconds.
          </p>
        )}
        {view.kind === "brief" && <BriefView result={view.result} requestId={view.requestId} />}
        {view.kind === "error" && (
          <div role="alert" className="flex flex-col gap-1 rounded-md border border-red-300 px-3 py-2 text-sm dark:border-red-800">
            <p className="font-medium text-red-800 dark:text-red-300">{view.failure.message}</p>
            <p className="text-zinc-700 dark:text-zinc-300">{view.failure.action}</p>
            {view.failure.requestId !== null && (
              <p className="font-mono text-xs text-zinc-500">Reference: {view.failure.requestId}</p>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function List({ title, items }: { title: string; items: readonly string[] }) {
  return (
    <section className="flex flex-col gap-1">
      <h3 className="font-medium">{title}</h3>
      {items.length === 0 ? (
        <p className="text-zinc-500">Nothing supported by the evidence.</p>
      ) : (
        <ul className="list-disc pl-5">
          {items.map((text, i) => (
            <li key={i}>{text}</li>
          ))}
        </ul>
      )}
    </section>
  );
}

function fmt(n: number | null): string {
  return n === null ? "unknown" : n.toLocaleString("en-US");
}

function seconds(ms: number): string {
  return `${(ms / 1000).toFixed(1)} s`;
}

// Phase 5 engineering transparency: what produced this brief, how long it took
// and what it cost. Unknown values say "unknown", never 0. Cost is always
// labelled as an estimate with the date of the prices it used.
function EngineeringPanel({ result, requestId }: { result: BriefResponse; requestId: string | null }) {
  const b = result.brief;
  const t = result.timing;
  const u = b.usage;
  const rows: [string, string][] = [
    ["Model", b.model],
    ["Model time", seconds(t.llm_ms)],
    ["GitHub time", seconds(t.github_ms)],
    ["Total time", seconds(t.total_ms)],
    [
      "Tokens",
      `${fmt(u?.input_tokens ?? null)} in (${fmt(u?.cached_input_tokens ?? null)} cached) · ${fmt(u?.output_tokens ?? null)} out (${fmt(u?.reasoning_tokens ?? null)} reasoning)`,
    ],
    [
      "Estimated model cost",
      b.estimated_cost === null
        ? "unknown"
        : `~$${b.estimated_cost.usd.toFixed(6)} (estimate from prices as of ${b.estimated_cost.pricing_as_of}, not a bill)`,
    ],
    [
      "Evidence",
      b.truncated
        ? `partial: ${b.files_considered} of ${b.files_total} files, see the note above`
        : `complete: ${b.files_considered} of ${b.files_total} files`,
    ],
    ["Versions", `schema ${b.schema_version} · prompt ${b.prompt_version}`],
    ["Reference", requestId ?? "unknown"],
  ];
  return (
    <section className="flex flex-col gap-1 rounded-md border border-zinc-200 px-3 py-2 text-xs dark:border-zinc-800">
      <h3 className="font-medium">How this brief was made</h3>
      <dl className="grid grid-cols-[max-content_1fr] gap-x-3 gap-y-0.5 text-zinc-600 dark:text-zinc-400">
        {rows.map(([label, value]) => (
          <div key={label} className="contents">
            <dt className="text-zinc-500">{label}</dt>
            <dd className="font-mono">{value}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

function BriefView({ result, requestId }: { result: BriefResponse; requestId: string | null }) {
  const b = result.brief;
  const m = b.brief;
  return (
    <div className="flex flex-col gap-4 text-sm">
      <p className="rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-amber-900 dark:border-amber-700 dark:bg-amber-950 dark:text-amber-200">
        AI-generated by {b.model}. It may be wrong; check it against the pull request.
      </p>
      {b.truncated && (
        <section className="rounded-md border border-zinc-300 px-3 py-2 dark:border-zinc-700">
          <p className="font-medium">
            Partial evidence: {b.files_considered} of {b.files_total} files were considered.
          </p>
          <ul className="list-disc pl-5 text-zinc-600 dark:text-zinc-400">
            {b.truncation_limitations.map((text, i) => (
              <li key={i}>{text}</li>
            ))}
          </ul>
        </section>
      )}
      <p className="font-mono text-xs text-zinc-500">
        {b.pr.owner}/{b.pr.repo}#{b.pr.number}
      </p>
      <section className="flex flex-col gap-1">
        <h3 className="font-medium">Summary</h3>
        <p>{m.summary}</p>
      </section>
      <section className="flex flex-col gap-1">
        <h3 className="font-medium">Why it matters</h3>
        <p>{m.why_it_matters}</p>
      </section>
      <section className="flex flex-col gap-1">
        <h3 className="font-medium">Change risk: {m.risk.level}</h3>
        <List title="Based on" items={m.risk.evidence} />
        <List title="Uncertainty" items={m.risk.uncertainty} />
      </section>
      <List title="User and business impact" items={m.user_impact} />
      <List title="Technical impact" items={m.technical_impact} />
      <List title="Testing signals in the PR" items={m.testing_signals} />
      <List title="Rollout" items={m.rollout_considerations} />
      <List title="Rollback" items={m.rollback_considerations} />
      <List title="Open questions" items={m.open_questions} />
      <List title="Limitations" items={m.limitations} />
      <EngineeringPanel result={result} requestId={requestId} />
    </div>
  );
}
