import "server-only";
import type { LlmConfig } from "@/lib/config";
import { createOpenAIBriefModel } from "@/lib/llm/openai";
import type { BriefModel } from "@/lib/llm/types";

// The only place OPENAI_API_KEY's VALUE is read; config.ts checks presence.

// The configured BriefModel, or null when no model is configured.
export function getBriefModel(llm: LlmConfig): BriefModel | null {
  if (llm.status !== "configured") return null;
  return briefModelFor(llm.model, llm.reasoningEffort);
}

// A BriefModel for an explicit model ID, for the local comparison script
// (scripts/brief-pr.ts). null when no API key is set.
export function briefModelFor(
  model: string,
  reasoningEffort: Extract<LlmConfig, { status: "configured" }>["reasoningEffort"],
): BriefModel | null {
  const apiKey = (process.env.OPENAI_API_KEY ?? "").trim();
  // Same rule as config.ts: an unresolved op:// reference is no key.
  if (apiKey === "" || apiKey.startsWith("op://")) return null;
  return createOpenAIBriefModel({ apiKey, model, reasoningEffort });
}
