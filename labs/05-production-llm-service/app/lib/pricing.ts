import type { ModelUsage } from "@/lib/llm/types";

// Dated model pricing for the ESTIMATED cost shown with a brief and recorded in
// telemetry. An estimate is not billing truth: the provider's invoice is.
//
// Rules (CLAUDE.md, Lab 05):
// - A price applies only to the model it names (or a dated snapshot of it,
//   such as "gpt-5.4-mini-2026-03-17"). Any other model has NO price, and its
//   cost is unknown, never zero.
// - Input and output token counts must both be reported. If either is missing
//   the cost is unknown: no estimate from partial usage.
// - Cached input tokens unreported: every input token is priced at the full
//   input rate. That can only over-estimate, never under-estimate.
// - Reasoning tokens are part of output_tokens and billed as output, so they
//   are not added again.
//
// Re-check the sources and bump PRICING_AS_OF whenever a price or the model
// changes. Standard processing, short context, USD per 1M tokens.

export const PRICING_AS_OF = "2026-10-19";
export const PRICING_SOURCES = [
  "https://developers.openai.com/api/docs/models/gpt-6-luna",
  "https://developers.openai.com/api/docs/models/gpt-5.4-mini",
] as const;

export type Price = { input: number; cached_input: number; output: number };

export const MODEL_PRICES: Readonly<Record<string, Price>> = Object.freeze({
  "gpt-6-luna": { input: 0.1, cached_input: 0.01, output: 0.5 },
  "gpt-5.4-mini": { input: 0.75, cached_input: 0.075, output: 4.5 },
});

export function priceFor(model: string, prices: Readonly<Record<string, Price>> = MODEL_PRICES): Price | null {
  // Longest alias that is the model itself or prefixes a dated snapshot of it.
  const alias = Object.keys(prices)
    .filter((a) => model === a || model.startsWith(`${a}-`))
    .sort((a, b) => b.length - a.length)[0];
  return alias === undefined ? null : prices[alias];
}

// USD estimate, or null when it cannot be known. See the rules above.
export function estimateUsd(usage: ModelUsage | null, price: Price | null): number | null {
  if (usage === null || price === null) return null;
  const { input_tokens: input, output_tokens: output } = usage;
  if (input === null || output === null) return null;
  const cached = Math.min(usage.cached_input_tokens ?? 0, input);
  return ((input - cached) * price.input + cached * price.cached_input + output * price.output) / 1_000_000;
}

export type CostEstimate = { usd: number; is_estimate: true; pricing_as_of: string };

export function estimateCost(usage: ModelUsage | null, model: string | null): CostEstimate | null {
  const usd = estimateUsd(usage, model === null ? null : priceFor(model));
  return usd === null ? null : { usd, is_estimate: true, pricing_as_of: PRICING_AS_OF };
}
