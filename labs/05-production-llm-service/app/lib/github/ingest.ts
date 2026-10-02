import "server-only";
import { createGithubClient, type GithubFailureReason, type GithubStats } from "@/lib/github/client";
import { filesUrlFor, pullUrl } from "@/lib/github/endpoints";
import { mapFiles, mapPull } from "@/lib/github/map";
import { normalizeEvidence } from "@/lib/normalize/evidence";
import type { PullRequestRef } from "@/lib/pr-url";
import type { NormalizedPullRequest } from "@/lib/schemas/normalized-pr";

// One analysis = one client = at most 3 GitHub requests:
//   GET /repos/{o}/{r}/pulls/{n}                       (1, or 2 with one redirect)
//   GET <served pull URL>/files?per_page=50&page=1     (1)
// No pagination beyond page 1, no raw-file fetches, no clone.

export type IngestFailureReason = GithubFailureReason | "malformed_response";

export type IngestResult =
  | { ok: true; evidence: NormalizedPullRequest; stats: GithubStats }
  | { ok: false; kind: "not_found" | "unavailable"; reason: IngestFailureReason; stats: GithubStats };

export async function ingestPullRequest(pr: PullRequestRef): Promise<IngestResult> {
  const client = createGithubClient();
  const fail = (reason: IngestFailureReason): IngestResult => ({
    ok: false,
    kind: reason === "not_found" ? "not_found" : "unavailable",
    reason,
    stats: client.stats(),
  });

  const pullResponse = await client.getJson(pullUrl(pr));
  if (!pullResponse.ok) return fail(pullResponse.reason);
  const pull = mapPull(pullResponse.json);
  if (pull === null) return fail("malformed_response");

  const filesUrl = filesUrlFor(pullResponse.servedUrl);
  if (filesUrl === null) return fail("bad_redirect");
  const filesResponse = await client.getJson(filesUrl);
  if (!filesResponse.ok) return fail(filesResponse.reason);
  const files = mapFiles(filesResponse.json);
  if (files === null) return fail("malformed_response");

  return { ok: true, evidence: normalizeEvidence(pr, pull, files), stats: client.stats() };
}
