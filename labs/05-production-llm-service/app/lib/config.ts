import "server-only";
import { z } from "zod";
import { SCHEMA_VERSION } from "@/lib/schemas/change-brief";

// Server-only configuration. The "server-only" import makes the build fail if
// a client component ever imports this module.
//
// Secrets are read here for PRESENCE only (GITHUB_TOKEN, OPENAI_API_KEY). Their
// values are never stored here: lib/github/client.ts and lib/llm/index.ts read
// them at call time. The same goes for the Upstash URL and token: their values
// are read only in lib/rate-limit.ts.
//
// Phase 6 rules for where the app runs. "On Vercel" means VERCEL=1, which
// Vercel sets for every deployment, preview and production alike:
//   - Kill switch: SERVICE_ENABLED=true serves analyses, false refuses them
//     before any work. Unset means enabled locally and DISABLED on Vercel, so a
//     deployment never starts spending until someone turns it on.
//   - Rate limits: on Vercel the store must be Upstash; without it analysis
//     fails closed. Locally an in-memory store is used unless Upstash is set.

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

const Limit = z.number().int().min(1).max(100_000);

const RateLimitConfigSchema = z.strictObject({
  backend: z.enum(["upstash", "memory", "not_configured"]),
  limits: z.strictObject({ perIpPerHour: Limit, perIpPerDay: Limit, globalPerDay: Limit }),
});

// Defaults (LEARNING-NOTES Phase 6). Override with the env variables below.
export const DEFAULT_RATE_LIMITS = { perIpPerHour: 10, perIpPerDay: 30, globalPerDay: 200 } as const;

const ConfigSchema = z.strictObject({
  schemaVersion: z.literal(SCHEMA_VERSION),
  // PRODUCT-CONTRACT.md §5: max request body.
  maxRequestBodyBytes: z.number().int().positive().max(2048),
  // Whether GitHub requests carry the optional read-only token. Safe to report.
  githubAuth: z.enum(["token", "anonymous"]),
  llm: LlmConfigSchema,
  onVercel: z.boolean(),
  serviceEnabled: z.boolean(),
  rateLimit: RateLimitConfigSchema,
});

export type AppConfig = Readonly<z.infer<typeof ConfigSchema>>;
export type LlmConfig = z.infer<typeof LlmConfigSchema>;
export type RateLimitConfig = z.infer<typeof RateLimitConfigSchema>;

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

function onVercel(): boolean {
  return (process.env.VERCEL ?? "").trim() === "1";
}

// "true" | "false" | unset. Anything else is invalid (fail closed), not a guess.
function serviceEnabledInput(): unknown {
  const raw = (process.env.SERVICE_ENABLED ?? "").trim().toLowerCase();
  if (raw === "") return !onVercel();
  if (raw === "true") return true;
  if (raw === "false") return false;
  return raw;
}

// Unset means the default; anything that is not a whole number is invalid.
function limitInput(name: string, fallback: number): unknown {
  const raw = (process.env[name] ?? "").trim();
  if (raw === "") return fallback;
  return /^\d{1,6}$/.test(raw) ? Number(raw) : raw;
}

function upstashPresent(): boolean {
  return (
    (present("UPSTASH_REDIS_REST_URL") && present("UPSTASH_REDIS_REST_TOKEN")) ||
    (present("KV_REST_API_URL") && present("KV_REST_API_TOKEN"))
  );
}

function rateLimitInput(): unknown {
  return {
    backend: upstashPresent() ? "upstash" : onVercel() ? "not_configured" : "memory",
    limits: {
      perIpPerHour: limitInput("RATE_LIMIT_PER_IP_PER_HOUR", DEFAULT_RATE_LIMITS.perIpPerHour),
      perIpPerDay: limitInput("RATE_LIMIT_PER_IP_PER_DAY", DEFAULT_RATE_LIMITS.perIpPerDay),
      globalPerDay: limitInput("ANALYSIS_DAILY_CAP", DEFAULT_RATE_LIMITS.globalPerDay),
    },
  };
}

export function getConfig(): ConfigResult {
  const parsed = ConfigSchema.safeParse({
    schemaVersion: SCHEMA_VERSION,
    maxRequestBodyBytes: 2048,
    githubAuth: present("GITHUB_TOKEN") ? "token" : "anonymous",
    llm: llmInput(),
    onVercel: onVercel(),
    serviceEnabled: serviceEnabledInput(),
    rateLimit: rateLimitInput(),
  });
  // Fail closed: an invalid config (for example a malformed OPENAI_MODEL or an
  // unknown reasoning effort) is reported, never silently defaulted.
  return parsed.success ? { ok: true, config: Object.freeze(parsed.data) } : { ok: false };
}
