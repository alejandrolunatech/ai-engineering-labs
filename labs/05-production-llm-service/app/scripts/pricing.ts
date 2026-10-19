// ESTIMATED cost for local scripts (brief-pr, evals). Not billing truth. The
// prices live in lib/pricing.ts so the app, the scripts and the evals share one
// dated table. Unknown usage or an unknown model gives an unknown cost, never zero.

import type { ModelUsage } from "@/lib/llm/types";
import { MODEL_PRICES, PRICING_AS_OF, estimateUsd, priceFor as priceForModel, type Price } from "@/lib/pricing";

export type { Price };
export type PricingSnapshot = { as_of: string; models: Readonly<Record<string, Price>> };

export function loadPricingSnapshot(): PricingSnapshot {
  return { as_of: PRICING_AS_OF, models: MODEL_PRICES };
}

export function priceFor(snapshot: PricingSnapshot, model: string): Price | null {
  return priceForModel(model, snapshot.models);
}

export function estimateCost(usage: ModelUsage | null, price: Price | null): number | null {
  return estimateUsd(usage, price);
}
