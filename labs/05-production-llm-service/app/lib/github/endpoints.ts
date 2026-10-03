import { buildPullApiUrl, type PullRequestRef } from "@/lib/pr-url";

// The only GitHub endpoints V1 calls. Every URL is built here from validated
// parts; nothing user-supplied is ever used as a URL.

export const GITHUB_API_ORIGIN = "https://api.github.com/";
export const FILES_PER_PAGE = 50;

export function pullUrl(pr: PullRequestRef): string {
  return buildPullApiUrl(pr);
}

// The two shapes a PR metadata URL may have:
//   - the one built by pullUrl() (owner/repo already encodeURIComponent-escaped);
//   - the id-based URL GitHub redirects to after a repository rename.
const PULL_URL_SHAPES = [
  /^https:\/\/api\.github\.com\/repos\/[A-Za-z0-9-]{1,39}\/[A-Za-z0-9._-]{1,100}\/pulls\/[1-9][0-9]{0,9}$/,
  /^https:\/\/api\.github\.com\/repositories\/[1-9][0-9]{0,15}\/pulls\/[1-9][0-9]{0,9}$/,
];

// Builds the changed-files URL from the URL the PR metadata was actually served
// from (after at most one redirect), so a renamed repository costs one extra
// request instead of two. Any other shape is refused.
export function filesUrlFor(servedPullUrl: string): string | null {
  if (!PULL_URL_SHAPES.some((shape) => shape.test(servedPullUrl))) return null;
  return `${servedPullUrl}/files?per_page=${FILES_PER_PAGE}&page=1`;
}
