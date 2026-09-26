import pytest

from pricing.discounts import apply_member_discount, apply_percentage_discount


def test_percentage_discount():
    assert apply_percentage_discount(1000, 15) == 850


def test_percentage_discount_rounds_half_up():
    assert apply_percentage_discount(1005, 10) == 905  # 904.5 -> 905


def test_rejects_out_of_range_percent():
    with pytest.raises(ValueError):
        apply_percentage_discount(1000, 120)


@pytest.mark.parametrize(
    "tier, expected", [("silver", 950), ("gold", 900), ("bronze", 1000)]
)
def test_member_discount(tier, expected):
    assert apply_member_discount(1000, tier) == expected


def test_member_discount_rounds_half_up():
    assert apply_member_discount(1005, "gold") == 905
