import type { GithubFile, GithubPull } from "@/lib/github/map";
import type { PullRequestRef } from "@/lib/pr-url";
import type { NormalizedFile, NormalizedPullRequest } from "@/lib/schemas/normalized-pr";

// Deterministic evidence budgeting (PRODUCT-CONTRACT.md §5). Pure function:
// same GitHub data + same budgets -> identical output. No I/O, no clock, no
// locale-dependent formatting.
//
// "Characters" are JavaScript string length (UTF-16 code units), not bytes or
// tokens.
//
// Order:
//   1. first MAX_FILES files in GitHub API order;
//   2. each patch capped at MAX_PATCH_CHARS;
//   3. body capped at MAX_BODY_CHARS;
//   4. body, then patches in file order, until MAX_TOTAL_CHARS is reached.
//      Files after that keep their metadata with patch = null.
//
// Limitations are server-written. They refer to files by position (#n), never
// by filename, so untrusted PR text never enters trusted text.

export const MAX_FILES = 50;
export const MAX_PATCH_CHARS = 4_000;
export const MAX_BODY_CHARS = 4_000;
export const MAX_TOTAL_CHARS = 60_000;

function fmt(n: number): string {
  return String(n).replace(/\B(?=(\d{3})+(?!\d))/g, ",");
}

// Cuts to at most `max` characters, at the last line break if there is one
// (the partial line is dropped). Without a line break it is a hard cut that
// never leaves half of a surrogate pair.
export function cutAtLineBoundary(text: string, max: number): string {
  if (text.length <= max) return text;
  if (max <= 0) return "";
  const cut = text.slice(0, max);
  const lineBreak = cut.lastIndexOf("\n");
  if (lineBreak > 0) return cut.slice(0, lineBreak);
  const last = cut.charCodeAt(cut.length - 1);
  return last >= 0xd800 && last <= 0xdbff ? cut.slice(0, -1) : cut;
}

export function normalizeEvidence(
  pr: PullRequestRef,
  pull: GithubPull,
  files: readonly GithubFile[],
): NormalizedPullRequest {
  const limitations: string[] = [];
  let truncated = false;

  // 1. File count.
  const considered = files.slice(0, MAX_FILES);
  const filesSeen = Math.max(pull.changedFiles, files.length);
  if (filesSeen > considered.length) {
    truncated = true;
    limitations.push(
      `Only the first ${fmt(considered.length)} of ${fmt(filesSeen)} changed files were considered (limit ${fmt(MAX_FILES)}).`,
    );
  }

  // 3 (before the per-file loop so its limitation is listed first). Body.
  let body = pull.body;
  if (body !== null && body.length > MAX_BODY_CHARS) {
    const original = body.length;
    body = cutAtLineBoundary(body, MAX_BODY_CHARS);
    truncated = true;
    limitations.push(
      `PR description cut from ${fmt(original)} to ${fmt(body.length)} characters (limit ${fmt(MAX_BODY_CHARS)}).`,
    );
  }

  let charsAvailable = pull.body?.length ?? 0;
  let remaining = MAX_TOTAL_CHARS - (body?.length ?? 0);
  const omitted: number[] = [];

  const normalizedFiles: NormalizedFile[] = considered.map((file, index) => {
    const label = `File #${index + 1}`;
    const base = {
      filename: file.filename,
      status: file.status,
      additions: file.additions,
      deletions: file.deletions,
    };

    if (file.patch === undefined) {
      limitations.push(`${label}: GitHub provided no patch (binary file or diff too large); only metadata is included.`);
      return { ...base, patch: null, patch_truncated: false, patch_unavailable_reason: "not_provided_by_github" };
    }

    charsAvailable += file.patch.length;

    // 2. Per-file cap.
    let patch = file.patch;
    let patchTruncated = false;
    if (patch.length > MAX_PATCH_CHARS) {
      patch = cutAtLineBoundary(patch, MAX_PATCH_CHARS);
      patchTruncated = true;
      truncated = true;
      limitations.push(
        `${label}: patch cut from ${fmt(file.patch.length)} to ${fmt(patch.length)} characters (per-file limit ${fmt(MAX_PATCH_CHARS)}).`,
      );
    }

    // 4. Total budget.
    if (patch.length > remaining) {
      const beforeTotalCut = patch.length;
      patch = cutAtLineBoundary(patch, remaining);
      truncated = true;
      if (patch.length === 0) {
        omitted.push(index + 1);
        return { ...base, patch: null, patch_truncated: false, patch_unavailable_reason: "evidence_budget_exhausted" };
      }
      patchTruncated = true;
      limitations.push(
        `${label}: patch cut from ${fmt(beforeTotalCut)} to ${fmt(patch.length)} characters to fit the ${fmt(MAX_TOTAL_CHARS)}-character total evidence limit.`,
      );
    }

    remaining -= patch.length;
    return { ...base, patch, patch_truncated: patchTruncated, patch_unavailable_reason: null };
  });

  if (omitted.length > 0) {
    limitations.push(
      `Total evidence limit of ${fmt(MAX_TOTAL_CHARS)} characters reached: patches for ${fmt(omitted.length)} later file(s) (#${omitted.join(", #")}) were omitted; their metadata is kept.`,
    );
  }

  return {
    pr: { owner: pr.owner, repo: pr.repo, number: pr.number },
    title: pull.title,
    body,
    state: pull.state,
    draft: pull.draft,
    merged: pull.merged,
    base_ref: pull.baseRef,
    head_ref: pull.headRef,
    additions: pull.additions,
    deletions: pull.deletions,
    changed_files: pull.changedFiles,
    files: normalizedFiles,
    coverage: {
      files_total: filesSeen,
      files_considered: considered.length,
      chars_available: charsAvailable,
      chars_included: MAX_TOTAL_CHARS - remaining,
    },
    truncated,
    limitations,
  };
}
