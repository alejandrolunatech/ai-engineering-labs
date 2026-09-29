"""Usage aggregation and cost estimation. Pure, deterministic, Decimal-based.

Rules:
- Usage is adapter-reported evidence. The runtime never invents it.
- Unknown is not zero. A token total exists only if EVERY attempted request
  reported a valid value for that dimension; otherwise it is None.
- A run that provably made zero model requests (enforced request counter)
  has a known zero: status "no_requests", 0 tokens, cost "0".
- Cost is estimated only when usage is complete and valid AND an exact
  (adapter, adapter-reported model) price exists. Otherwise cost is unknown,
  with an explicit reason. There is never a partial cost.
- Estimates are not billing.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal
from pathlib import Path
from typing import Any

from contracts import (
    PROJECT_ROOT,
    ManifestError,
    describe_errors,
    load_yaml_strict,
    parse_json_strict,
)
from model_adapter import ModelInfo, ModelResponse, Usage

PRICING_FILE = "pricing.yaml"
PRICING_SCHEMA_FILE = "platform/pricing.schema.json"
TOKENS_PER_PRICE_UNIT = Decimal(1_000_000)
COST_QUANTUM = Decimal("0.0000000001")  # 10 decimal places, applied once at the end


@dataclass(frozen=True)
class Price:
    adapter: str
    model: str
    input_per_million_tokens: Decimal
    output_per_million_tokens: Decimal


@dataclass(frozen=True)
class Pricing:
    currency: str
    prices: tuple[Price, ...] = ()

    def find(self, adapter: str, model: str | None) -> Price | None:
        for price in self.prices:
            if price.adapter == adapter and price.model == model:
                return price
        return None


def load_pricing(root: Path = PROJECT_ROOT) -> Pricing:
    try:
        raw = load_yaml_strict((root / PRICING_FILE).read_text(encoding="utf-8"))
        schema = parse_json_strict((root / PRICING_SCHEMA_FILE).read_text(encoding="utf-8"))
    except Exception as exc:  # OSError, UnicodeDecodeError, YAMLError, ValueError
        raise ManifestError(f"cannot load {PRICING_FILE}: {type(exc).__name__}") from None
    problems = describe_errors(schema, raw)
    if problems:
        raise ManifestError(f"{PRICING_FILE} violates {PRICING_SCHEMA_FILE}: {problems}")
    keys = [(p["adapter"], p["model"]) for p in raw["prices"]]
    if len(keys) != len(set(keys)):
        raise ManifestError(f"{PRICING_FILE} has duplicate adapter/model prices")
    return Pricing(
        currency=raw["currency"],
        prices=tuple(
            Price(
                adapter=p["adapter"],
                model=p["model"],
                input_per_million_tokens=Decimal(p["input_per_million_tokens"]),
                output_per_million_tokens=Decimal(p["output_per_million_tokens"]),
            )
            for p in raw["prices"]
        ),
    )


def _valid_count(value: Any) -> bool:
    return value is None or (type(value) is int and value >= 0)


@dataclass(frozen=True)
class Attempt:
    """What one attempted model request reported. usage is None when unknown
    (no response) or when the adapter reported something invalid."""

    adapter: str
    reported_model: str | None
    usage: Usage | None
    usage_invalid: bool = False

    @classmethod
    def no_response(cls, adapter: str) -> "Attempt":
        return cls(adapter=adapter, reported_model=None, usage=None)

    @classmethod
    def from_response(cls, adapter: str, response: Any) -> "Attempt":
        if not isinstance(response, ModelResponse):
            return cls(adapter=adapter, reported_model=None, usage=None)
        model = response.model.model if isinstance(response.model, ModelInfo) else None
        usage = response.usage
        if not isinstance(usage, Usage) or not (
            _valid_count(usage.input_tokens) and _valid_count(usage.output_tokens)
        ):
            return cls(adapter=adapter, reported_model=model, usage=None, usage_invalid=True)
        return cls(adapter=adapter, reported_model=model, usage=usage)

    @property
    def usage_status(self) -> str:
        if self.usage_invalid:
            return "invalid_reported"
        if self.usage is None:
            return "unknown"
        known = [v is not None for v in (self.usage.input_tokens, self.usage.output_tokens)]
        return "known" if all(known) else "partial" if any(known) else "unknown"


def _unknown_cost(reason: str) -> dict:
    return {"cost.status": "unknown", "cost.unknown_reason": reason, "cost.currency": None, "cost.estimated": None}


def _format(amount: Decimal) -> str:
    return str(amount.quantize(COST_QUANTUM, rounding=ROUND_HALF_EVEN))


def _attempt_cost(attempt: Attempt, pricing: Pricing) -> tuple[Decimal | None, dict]:
    if attempt.usage_invalid:
        return None, _unknown_cost("invalid_usage")
    price = pricing.find(attempt.adapter, attempt.reported_model)
    if price is None:
        return None, _unknown_cost("no_pricing")
    status = attempt.usage_status
    if status != "known":
        return None, _unknown_cost("usage_unknown" if status == "unknown" else "usage_partial")
    amount = (
        Decimal(attempt.usage.input_tokens) * price.input_per_million_tokens
        + Decimal(attempt.usage.output_tokens) * price.output_per_million_tokens
    ) / TOKENS_PER_PRICE_UNIT
    return amount, {
        "cost.status": "estimated",
        "cost.unknown_reason": None,
        "cost.currency": pricing.currency,
        "cost.estimated": _format(amount),
    }


def attempt_attributes(attempt: Attempt, pricing: Pricing) -> dict:
    """Usage and cost attributes for one model-request span."""
    usage = attempt.usage
    return {
        "usage.status": attempt.usage_status,
        "usage.input_tokens": usage.input_tokens if usage else None,
        "usage.output_tokens": usage.output_tokens if usage else None,
        **_attempt_cost(attempt, pricing)[1],
    }


def run_attributes(attempts: list[Attempt], pricing: Pricing | None) -> dict:
    """Aggregated usage and cost attributes for the root capability span."""
    if not attempts:
        # Known zero: the enforced request counter proves no adapter call happened.
        return {
            "usage.status": "no_requests",
            "usage.input_tokens": 0,
            "usage.output_tokens": 0,
            "cost.status": "no_requests",
            "cost.unknown_reason": None,
            "cost.currency": None,
            "cost.estimated": "0",
        }

    def total(field: str) -> int | None:
        values = [getattr(a.usage, field) if a.usage else None for a in attempts]
        return None if any(v is None for v in values) else sum(values)

    input_total, output_total = total("input_tokens"), total("output_tokens")
    if any(a.usage_invalid for a in attempts):
        status = "invalid_reported"
    elif input_total is not None and output_total is not None:
        status = "known"
    elif all(a.usage_status == "unknown" for a in attempts):
        status = "unknown"
    else:
        status = "partial"
    usage = {"usage.status": status, "usage.input_tokens": input_total, "usage.output_tokens": output_total}

    if pricing is None:  # not expected: pricing loads before any model request
        return {**usage, **_unknown_cost("no_pricing")}
    costs =[_attempt_cost(a, pricing) for a in attempts]
    if all(amount is not None for amount, _ in costs):
        return {
            **usage,
            "cost.status": "estimated",
            "cost.unknown_reason": None,
            "cost.currency": pricing.currency,
            "cost.estimated": _format(sum(amount for amount, _ in costs)),
        }
    reasons = {attrs["cost.unknown_reason"] for _, attrs in costs}
    if "invalid_usage" in reasons:
        reason = "invalid_usage"
    elif "no_pricing" in reasons:
        reason = "no_pricing"
    elif status == "unknown":
        reason = "usage_unknown"
    else:
        reason = "usage_partial"
    return {**usage, **_unknown_cost(reason)}
