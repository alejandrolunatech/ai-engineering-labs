// Manual exercise: npm run inspect-pr -- <github PR URL> [--show-evidence]
//
// Runs the SAME parser, GitHub adapter and normalizer as POST /api/analyze and
// prints a summary. By default it prints no patch content and no PR body text;
// --show-evidence prints the full normalized evidence for your own inspection.
// Makes at most 3 GitHub requests (the adapter's ceiling). Never prints the token.

import { getConfig } from "@/lib/config";
import { ingestPullRequest } from "@/lib/github/ingest";
import { parsePrUrl } from "@/lib/pr-url";

// PR text is untrusted: escape C0/C1 control characters so a filename cannot
// inject terminal escape sequences.
function safe(text: string): string {
  return text.replace(/[\u0000-\u001f\u007f-\u009f]/g, (c) => `\\u${c.charCodeAt(0).toString(16).padStart(4, "0")}`);
}

async function main(): Promise<number> {
  const args = process.argv.slice(2);
  const showEvidence = args.includes("--show-evidence");
  const urls = args.filter((a) => a !== "--show-evidence");
  if (urls.length !== 1) {
    console.error("usage: npm run inspect-pr -- <https://github.com/owner/repo/pull/N> [--show-evidence]");
    return 2;
  }

  const parsed = parsePrUrl(urls[0]);
  if (!parsed.ok) {
    console.error(`rejected before any GitHub request: ${parsed.reason}`);
    return 2;
  }

  const config = getConfig();
  const auth = config.ok ? config.config.githubAuth : "config invalid";
  console.log(`PR: ${parsed.pr.owner}/${parsed.pr.repo}#${parsed.pr.number}   GitHub auth: ${auth}`);

  const started = performance.now();
  const result = await ingestPullRequest(parsed.pr);
  const elapsedMs = Math.round(performance.now() - started);

  const { requests, redirects, rateLimitRemaining } = result.stats;
  const fmt = (v: number | null | undefined) => (v === null || v === undefined ? "n/a" : String(v));
  console.log(`GitHub requests: ${requests} (redirects followed: ${redirects})   wall time: ${elapsedMs} ms`);
  console.log(
    `x-ratelimit-remaining after first response: ${fmt(rateLimitRemaining[0])}, ` +
      `after last response: ${fmt(rateLimitRemaining.at(-1))} ` +
      `(the value before the first request is not observed; per response: [${rateLimitRemaining.map(fmt).join(", ")}])`,
  );

  if (!result.ok) {
    console.log(`FAILED: kind=${result.kind} reason=${result.reason}`);
    return 1;
  }

  const e = result.evidence;
  console.log(`state: ${e.state}  draft: ${e.draft}  merged: ${e.merged}  +${e.additions} -${e.deletions}`);
  console.log(`title chars: ${e.title.length}   body chars: ${e.body === null ? "null" : e.body.length}`);
  console.log(`coverage: ${JSON.stringify(e.coverage)}`);
  console.log(`truncated: ${e.truncated}`);
  console.log(`limitations (${e.limitations.length}):`);
  for (const l of e.limitations) console.log(`  - ${l}`);
  console.log("files:");
  e.files.forEach((f, i) => {
    const patch = f.patch === null ? `no patch (${f.patch_unavailable_reason})` : `${f.patch.length} patch chars`;
    console.log(`  #${i + 1} [${f.status}] ${safe(f.filename)}  +${f.additions} -${f.deletions}  ${patch}${f.patch_truncated ? "  TRUNCATED" : ""}`);
  });
  console.log(`total evidence chars included: ${e.coverage.chars_included} of ${e.coverage.chars_available} available`);

  if (showEvidence) {
    console.log("\n--- normalized evidence (untrusted PR content below) ---");
    console.log(JSON.stringify(e, null, 2).split("\n").map(safe).join("\n"));
  }
  return 0;
}

main().then(
  (code) => process.exit(code),
  () => {
    console.error("inspect-pr failed with an unexpected error");
    process.exit(1);
  },
);
