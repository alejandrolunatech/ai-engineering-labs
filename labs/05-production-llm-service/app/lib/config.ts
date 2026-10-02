import "server-only";
import { z } from "zod";
import { SCHEMA_VERSION } from "@/lib/schemas/change-brief";

// Server-only configuration. The "server-only" import makes the build fail if
// a client component ever imports this module.
//
// Phase 2 reads one environment variable, and only its PRESENCE: GITHUB_TOKEN.
// The token value is never stored here; lib/github/client.ts reads it at call
// time. Model choice, pricing and the kill switch arrive in later phases.

const ConfigSchema = z.strictObject({
  schemaVersion: z.literal(SCHEMA_VERSION),
  // PRODUCT-CONTRACT.md §5: max request body.
  maxRequestBodyBytes: z.number().int().positive().max(2048),
  // Whether GitHub requests carry the optional read-only token. Safe to report.
  githubAuth: z.enum(["token", "anonymous"]),
});

export type AppConfig = Readonly<z.infer<typeof ConfigSchema>>;

export type ConfigResult = { ok: true; config: AppConfig } | { ok: false };

export function getConfig(): ConfigResult {
  const parsed = ConfigSchema.safeParse({
    schemaVersion: SCHEMA_VERSION,
    maxRequestBodyBytes: 2048,
    githubAuth: (process.env.GITHUB_TOKEN ?? "").trim() !== "" ? "token" : "anonymous",
  });
  // Fail closed: an invalid config is reported, never silently defaulted.
  return parsed.success ? { ok: true, config: Object.freeze(parsed.data) } : { ok: false };
}
