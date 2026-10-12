// ESTIMATED cost for local scripts (brief-pr, evals) from pricing-snapshot.json.
// Not billing truth, and not used by the app (Phase 5 adds dated server-side
// pricing). Unknown usage or an unknown model gives an unknown cost, never zero.

import { readFileSync } from "node:fs";
import type { ModelUsage } from "@/lib/llm/types";

export type Price = { input: number; cached_input: number; output: number };
export type PricingSnapshot = { as_of: string; models: Record<string, Price> };

export function loadPricingSnapshot(): PricingSnapshot {
  return JSON.parse(readFileSync(new URL("./pricing-snapshot.json", import.meta.url), "utf8")) as PricingSnapshot;
}

export function priceFor(snapshot: PricingSnapshot, model: string): Price | null {
  // Served IDs can be dated snapshots ("gpt-5.4-mini-2026-03-17"): match the
  // longest alias that prefixes it.
  const alias = Object.keys(snapshot.models)
    .filter((a) => model === a || model.startsWith(`${a}-`))
    .sort((a, b) => b.length - a.length)[0];
  return alias === undefined ? null : snapshot.models[alias];
}

export function estimateCost(usage: ModelUsage | null, price: Price | null): number | null {
  if (usage === null || price === null) return null;
  const { input_tokens: input, output_tokens: output } = usage;
  if (input === null || output === null) return null;
  const cached = usage.cached_input_tokens ?? 0;
  return ((input - cached) * price.input + cached * price.cached_input + output * price.output) / 1_000_000;
}
