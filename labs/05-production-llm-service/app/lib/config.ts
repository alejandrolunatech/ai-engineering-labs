import "server-only";
import { z } from "zod";
import { SCHEMA_VERSION } from "@/lib/schemas/change-brief";

// Server-only configuration. The "server-only" import makes the build fail if
// a client component ever imports this module.
//
// Secrets are read here for PRESENCE only (GITHUB_TOKEN, OPENAI_API_KEY). Their
// values are never stored here: lib/github/client.ts and lib/llm/index.ts read
// them at call time. Pricing and the kill switch arrive in later phases.

// Model IDs are short provider identifiers such as "gpt-6-luna" or
// "gpt-5.4-mini-2026-03-17". Anything else is a misconfiguration.
const MODEL_ID = /^[a-z0-9][a-z0-9.\-]{0,99}$/;

// Reasoning tokens count against the 1,500 output-token ceiling, so the default
// is "none". Raise it only with eval evidence that it helps.
export const REASONING_EFFORTS = ["none", "low", "medium", "high"] as const;

const LlmConfigSchema = z.discriminatedUnion("status", [
  z.strictObject({
    status: z.literal("configured"),
    provider: z.literal("openai"),
    model: z.string().regex(MODEL_ID),
    reasoningEffort: z.enum(REASONING_EFFORTS),
  }),
  // Missing key or model: the app runs, analysis fails closed with a
  // controlled provider_unavailable. Health reports it.
  z.strictObject({ status: z.literal("not_configured") }),
]);

const ConfigSchema = z.strictObject({
  schemaVersion: z.literal(SCHEMA_VERSION),
  // PRODUCT-CONTRACT.md §5: max request body.
  maxRequestBodyBytes: z.number().int().positive().max(2048),
  // Whether GitHub requests carry the optional read-only token. Safe to report.
  githubAuth: z.enum(["token", "anonymous"]),
  llm: LlmConfigSchema,
});

export type AppConfig = Readonly<z.infer<typeof ConfigSchema>>;
export type LlmConfig = z.infer<typeof LlmConfigSchema>;

export type ConfigResult = { ok: true; config: AppConfig } | { ok: false };

function present(name: string): boolean {
  return (process.env[name] ?? "").trim() !== "";
}

// An unresolved 1Password reference ("op://...") means the app was started
// without `op run`: the key would only fail at OpenAI with a 401. Treat it as
// missing so health says not_configured instead.
function keyPresent(): boolean {
  return present("OPENAI_API_KEY") && !(process.env.OPENAI_API_KEY ?? "").trim().startsWith("op://");
}

function llmInput(): unknown {
  if (!keyPresent() || !present("OPENAI_MODEL")) {
    return { status: "not_configured" };
  }
  return {
    status: "configured",
    provider: "openai",
    model: (process.env.OPENAI_MODEL ?? "").trim(),
    reasoningEffort: (process.env.OPENAI_REASONING_EFFORT ?? "").trim() || "none",
  };
}

export function getConfig(): ConfigResult {
  const parsed = ConfigSchema.safeParse({
    schemaVersion: SCHEMA_VERSION,
    maxRequestBodyBytes: 2048,
    githubAuth: present("GITHUB_TOKEN") ? "token" : "anonymous",
    llm: llmInput(),
  });
  // Fail closed: an invalid config (for example a malformed OPENAI_MODEL or an
  // unknown reasoning effort) is reported, never silently defaulted.
  return parsed.success ? { ok: true, config: Object.freeze(parsed.data) } : { ok: false };
}
