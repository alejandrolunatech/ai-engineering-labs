"""Discount calculations. All amounts are integer cents."""

from decimal import ROUND_HALF_UP, Decimal

MEMBER_DISCOUNT_PERCENT = {"silver": 5, "gold": 10}


def _round_to_cents(amount: Decimal) -> int:
    return int(amount.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def apply_percentage_discount(price_cents: int, percent: int) -> int:
    if not 0 <= percent <= 100:
        raise ValueError(f"percent must be between 0 and 100, got {percent}")
    discounted = Decimal(price_cents) * (Decimal(100 - percent) / Decimal(100))
    return _round_to_cents(discounted)


def apply_member_discount(price_cents: int, member_tier: str) -> int:
    percent = MEMBER_DISCOUNT_PERCENT.get(member_tier, 0)
    return apply_percentage_discount(price_cents, percent)
