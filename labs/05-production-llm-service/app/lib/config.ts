import "server-only";
import { z } from "zod";
import { SCHEMA_VERSION } from "@/lib/schemas/change-brief";

// Server-only configuration. The "server-only" import makes the build fail if
// a client component ever imports this module.
//
// Phase 1 reads no environment variables. Secrets, model choice, pricing and
// the kill switch are added in the phases that use them (see .env.example).

const ConfigSchema = z.strictObject({
  schemaVersion: z.literal(SCHEMA_VERSION),
  // PRODUCT-CONTRACT.md §5: max request body.
  maxRequestBodyBytes: z.number().int().positive().max(2048),
});

export type AppConfig = Readonly<z.infer<typeof ConfigSchema>>;

export type ConfigResult = { ok: true; config: AppConfig } | { ok: false };

export function getConfig(): ConfigResult {
  const parsed = ConfigSchema.safeParse({
    schemaVersion: SCHEMA_VERSION,
    maxRequestBodyBytes: 2048,
  });
  // Fail closed: an invalid config is reported, never silently defaulted.
  return parsed.success ? { ok: true, config: Object.freeze(parsed.data) } : { ok: false };
}
