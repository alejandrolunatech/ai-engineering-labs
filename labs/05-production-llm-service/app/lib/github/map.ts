import { z } from "zod";
import { FILE_STATUSES } from "@/lib/schemas/normalized-pr";

// GitHub JSON -> internal types. z.object (not strictObject) STRIPS unknown
// fields, so user objects, avatars, emails, URLs and _links never get past this
// point. A response that does not match is treated as malformed (unavailable),
// never partially used.

const count = z.number().int().nonnegative();

const GithubPullSchema = z.object({
  title: z.string().max(1024),
  body: z.string().nullable(),
  state: z.enum(["open", "closed"]),
  draft: z.boolean().optional(),
  merged: z.boolean(),
  base: z.object({ ref: z.string().max(1024) }),
  head: z.object({ ref: z.string().max(1024) }),
  additions: count,
  deletions: count,
  changed_files: count,
});

const GithubFileSchema = z.object({
  filename: z.string().max(4096),
  status: z.enum(FILE_STATUSES),
  additions: count,
  deletions: count,
  patch: z.string().optional(),
});

// The files request asks for per_page=50; anything longer is not what we asked for.
const GithubFilesSchema = z.array(GithubFileSchema).max(100);

export type GithubPull = {
  title: string;
  body: string | null;
  state: "open" | "closed";
  draft: boolean;
  merged: boolean;
  baseRef: string;
  headRef: string;
  additions: number;
  deletions: number;
  changedFiles: number;
};

export type GithubFile = z.infer<typeof GithubFileSchema>;

export function mapPull(json: unknown): GithubPull | null {
  const parsed = GithubPullSchema.safeParse(json);
  if (!parsed.success) return null;
  const p = parsed.data;
  return {
    title: p.title,
    body: p.body,
    state: p.state,
    draft: p.draft ?? false,
    merged: p.merged,
    baseRef: p.base.ref,
    headRef: p.head.ref,
    additions: p.additions,
    deletions: p.deletions,
    changedFiles: p.changed_files,
  };
}

export function mapFiles(json: unknown): GithubFile[] | null {
  const parsed = GithubFilesSchema.safeParse(json);
  return parsed.success ? parsed.data : null;
}
