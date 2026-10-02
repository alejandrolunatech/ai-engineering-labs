import type { GithubFile, GithubPull } from "@/lib/github/map";
import type { PullRequestRef } from "@/lib/pr-url";
import type { NormalizedFile, NormalizedPullRequest } from "@/lib/schemas/normalized-pr";

// Deterministic evidence budgeting (PRODUCT-CONTRACT.md §5). Pure function:
// same GitHub data + same budgets -> identical output. No I/O, no clock, no
// locale-dependent formatting.
//
// "Characters" are JavaScript string length (UTF-16 code units), not bytes or
// tokens. EVERY untrusted string in the envelope (title, base/head ref,
// filenames, body, patches) counts toward MAX_TOTAL_CHARS.
//
// Order:
//   1. first MAX_FILES files in GitHub API order;
//   2. title, refs and filenames capped (MAX_TITLE/REF/FILENAME_CHARS);
//   3. each patch capped at MAX_PATCH_CHARS;
//   4. body capped at MAX_BODY_CHARS;
//   5. total: title + refs + filenames first (always fit, see METADATA bound
//      below), then body, then patches in file order until MAX_TOTAL_CHARS.
//      The first patch that does not fit is cut (at a line break) and closes
//      the budget; every later file keeps its metadata with patch = null.
//
// Limitations are server-written. They refer to fields by name and to files by
// position (#n), never by content, so untrusted PR text never enters trusted
// text. Limitation strings themselves are not counted in the total.

export const MAX_FILES = 50;
export const MAX_TITLE_CHARS = 300;
export const MAX_REF_CHARS = 255;
export const MAX_FILENAME_CHARS = 300;
export const MAX_PATCH_CHARS = 4_000;
export const MAX_BODY_CHARS = 4_000;
export const MAX_TOTAL_CHARS = 60_000;

// Worst case for title + 2 refs + filenames + body (15,810 + 4,000). Below the
// total, so these fields are never dropped for budget reasons; only patches are.
const MAX_NON_PATCH_CHARS =
  MAX_TITLE_CHARS + 2 * MAX_REF_CHARS + MAX_FILES * MAX_FILENAME_CHARS + MAX_BODY_CHARS;
if (MAX_NON_PATCH_CHARS > MAX_TOTAL_CHARS) {
  throw new Error("evidence budgets are inconsistent");
}

function fmt(n: number): string {
  return String(n).replace(/\B(?=(\d{3})+(?!\d))/g, ",");
}

// Hard cut to at most `max` characters that never leaves half of a surrogate pair.
export function cutHard(text: string, max: number): string {
  if (text.length <= max) return text;
  if (max <= 0) return "";
  const cut = text.slice(0, max);
  const last = cut.charCodeAt(cut.length - 1);
  return last >= 0xd800 && last <= 0xdbff ? cut.slice(0, -1) : cut;
}

// Cuts to at most `max` characters, at the last line break if there is one
// (the partial line is dropped). Without a line break it is a hard cut.
export function cutAtLineBoundary(text: string, max: number): string {
  if (text.length <= max) return text;
  if (max <= 0) return "";
  const lineBreak = text.slice(0, max).lastIndexOf("\n");
  return lineBreak > 0 ? text.slice(0, lineBreak) : cutHard(text, max);
}

export function normalizeEvidence(
  pr: PullRequestRef,
  pull: GithubPull,
  files: readonly GithubFile[],
): NormalizedPullRequest {
  const limitations: string[] = [];
  let truncated = false;
  let charsAvailable = 0;
  let charsIncluded = 0;

  // Caps a single-line field, records the limitation, and counts it.
  function capField(value: string, max: number, label: string): string {
    charsAvailable += value.length;
    const out = cutHard(value, max);
    if (out.length < value.length) {
      truncated = true;
      limitations.push(`${label} cut from ${fmt(value.length)} to ${fmt(out.length)} characters (limit ${fmt(max)}).`);
    }
    charsIncluded += out.length;
    return out;
  }

  // 1. File count.
  const considered = files.slice(0, MAX_FILES);
  const filesSeen = Math.max(pull.changedFiles, files.length);
  if (filesSeen > considered.length) {
    truncated = true;
    limitations.push(
      `Only the first ${fmt(considered.length)} of ${fmt(filesSeen)} changed files were considered (limit ${fmt(MAX_FILES)}).`,
    );
  }

  // 2. Title, refs, filenames. Counted first; bounded so they always fit.
  const title = capField(pull.title, MAX_TITLE_CHARS, "PR title");
  const baseRef = capField(pull.baseRef, MAX_REF_CHARS, "Base branch name");
  const headRef = capField(pull.headRef, MAX_REF_CHARS, "Head branch name");
  const filenames = considered.map((file, index) =>
    capField(file.filename, MAX_FILENAME_CHARS, `File #${index + 1}: filename`),
  );

  // 4. Body.
  let body = pull.body;
  if (body !== null) {
    charsAvailable += body.length;
    if (body.length > MAX_BODY_CHARS) {
      const original = body.length;
      body = cutAtLineBoundary(body, MAX_BODY_CHARS);
      truncated = true;
      limitations.push(
        `PR description cut from ${fmt(original)} to ${fmt(body.length)} characters (limit ${fmt(MAX_BODY_CHARS)}).`,
      );
    }
    charsIncluded += body.length;
  }

  // 3 + 5. Patches: per-file cap, then whatever is left of the total.
  const omitted: number[] = [];
  // Set by the first patch that is cut to fit the total. Later patches are
  // omitted even if a few characters remain, so no file gets a meaningless
  // fragment of its diff.
  let budgetClosed = false;
  const normalizedFiles: NormalizedFile[] = considered.map((file, index) => {
    const label = `File #${index + 1}`;
    const base = {
      filename: filenames[index],
      status: file.status,
      additions: file.additions,
      deletions: file.deletions,
    };

    if (file.patch === undefined) {
      limitations.push(`${label}: GitHub provided no patch (binary file or diff too large); only metadata is included.`);
      return { ...base, patch: null, patch_truncated: false, patch_unavailable_reason: "not_provided_by_github" };
    }

    charsAvailable += file.patch.length;

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

    const remaining = budgetClosed ? 0 : MAX_TOTAL_CHARS - charsIncluded;
    if (patch.length > remaining) {
      const beforeTotalCut = patch.length;
      patch = cutAtLineBoundary(patch, remaining);
      truncated = true;
      budgetClosed = true;
      if (patch.length === 0) {
        omitted.push(index + 1);
        return { ...base, patch: null, patch_truncated: false, patch_unavailable_reason: "evidence_budget_exhausted" };
      }
      patchTruncated = true;
      limitations.push(
        `${label}: patch cut from ${fmt(beforeTotalCut)} to ${fmt(patch.length)} characters to fit the ${fmt(MAX_TOTAL_CHARS)}-character total evidence limit.`,
      );
    }

    charsIncluded += patch.length;
    return { ...base, patch, patch_truncated: patchTruncated, patch_unavailable_reason: null };
  });

  if (omitted.length > 0) {
    limitations.push(
      `Total evidence limit of ${fmt(MAX_TOTAL_CHARS)} characters reached: patches for ${fmt(omitted.length)} later file(s) (#${omitted.join(", #")}) were omitted; their metadata is kept.`,
    );
  }

  return {
    pr: { owner: pr.owner, repo: pr.repo, number: pr.number },
    title,
    body,
    state: pull.state,
    draft: pull.draft,
    merged: pull.merged,
    base_ref: baseRef,
    head_ref: headRef,
    additions: pull.additions,
    deletions: pull.deletions,
    changed_files: pull.changedFiles,
    files: normalizedFiles,
    coverage: {
      files_total: filesSeen,
      files_considered: considered.length,
      chars_available: charsAvailable,
      chars_included: charsIncluded,
    },
    truncated,
    limitations,
  };
}
