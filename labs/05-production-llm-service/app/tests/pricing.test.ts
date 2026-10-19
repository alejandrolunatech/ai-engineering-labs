import { describe, expect, it } from "vitest";
import { MODEL_PRICES, PRICING_AS_OF, estimateCost, estimateUsd, priceFor } from "@/lib/pricing";

// Dated pricing and the cost-estimate rules. No network.

const usage = (input: number | null, cached: number | null, output: number | null) => ({
  input_tokens: input,
  cached_input_tokens: cached,
  output_tokens: output,
  reasoning_tokens: 0,
});

describe("pricing", () => {
  it("is dated and priced per 1M tokens", () => {
    expect(PRICING_AS_OF).toMatch(/^\d{4}-\d{2}-\d{2}$/);
    expect(MODEL_PRICES["gpt-6-luna"]).toEqual({ input: 0.1, cached_input: 0.01, output: 0.5 });
  });

  it("prices an exact model and its dated snapshots, nothing else", () => {
    expect(priceFor("gpt-5.4-mini")).toBe(MODEL_PRICES["gpt-5.4-mini"]);
    expect(priceFor("gpt-5.4-mini-2026-03-17")).toBe(MODEL_PRICES["gpt-5.4-mini"]);
    expect(priceFor("gpt-5.4")).toBeNull();
    expect(priceFor("gpt-6-lunar")).toBeNull();
    expect(priceFor("unknown-model")).toBeNull();
  });

  it("computes the documented formula", () => {
    // 2,483 in (483 cached), 298 out at luna prices:
    // (2000 x 0.10 + 483 x 0.01 + 298 x 0.50) / 1M = 0.00035383
    expect(estimateUsd(usage(2483, 483, 298), priceFor("gpt-6-luna"))).toBeCloseTo(0.00035383, 10);
  });

  it("prices every input token at the full rate when cached is unknown (over-estimate only)", () => {
    expect(estimateUsd(usage(1000, null, 0), priceFor("gpt-6-luna"))).toBeCloseTo(0.0001, 12);
  });

  it("never treats unknown usage or an unpriced model as zero", () => {
    const price = priceFor("gpt-6-luna");
    expect(estimateUsd(null, price)).toBeNull();
    expect(estimateUsd(usage(null, 0, 10), price)).toBeNull();
    expect(estimateUsd(usage(10, 0, null), price)).toBeNull();
    expect(estimateUsd(usage(10, 0, 10), null)).toBeNull();
    expect(estimateCost(usage(10, 0, 10), null)).toBeNull();
    expect(estimateCost(usage(10, 0, 10), "unknown-model")).toBeNull();
  });

  it("labels an estimate with its pricing date", () => {
    expect(estimateCost(usage(1_000_000, 0, 0), "gpt-6-luna")).toEqual({
      usd: 0.1,
      is_estimate: true,
      pricing_as_of: PRICING_AS_OF,
    });
  });
});
