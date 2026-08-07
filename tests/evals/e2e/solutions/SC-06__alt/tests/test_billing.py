import pytest

import billing


@pytest.mark.parametrize(
    ("quantity", "expected_subtotal"),
    [(1, 100), (10, 1000), (11, 1090), (50, 4600), (51, 4675), (60, 5350)],
)
def test_graduated_subtotal_at_100_cents(quantity, expected_subtotal):
    result = billing.price_order(quantity=quantity, unit_price_cents=100)
    assert result["subtotal_cents"] == expected_subtotal
    assert result["total_cents"] == expected_subtotal


def test_half_up_rounding_on_band_and_tier():
    assert billing.price_order(quantity=11, unit_price_cents=25)["subtotal_cents"] == 273
    silver = billing.price_order(quantity=10, unit_price_cents=101, tier="silver")
    assert silver["tier_discount_cents"] == 51


def test_save15_on_post_tier_remainder_with_cap():
    r = billing.price_order(quantity=10, unit_price_cents=100, tier="silver", promo_code="SAVE15")
    assert r["promo_discount_cents"] == 143  # 15% of 950 = 142.5 -> 143
    capped = billing.price_order(quantity=200, unit_price_cents=100, promo_code="SAVE15")
    assert capped["promo_discount_cents"] == 2000
    assert capped["total_cents"] == 13850


def test_gold_and_save15_are_mutually_exclusive():
    small = billing.price_order(quantity=10, unit_price_cents=100, tier="gold", promo_code="SAVE15")
    assert (small["tier_discount_cents"], small["promo_discount_cents"], small["total_cents"]) == (0, 150, 850)
    large = billing.price_order(quantity=10, unit_price_cents=3000, tier="gold", promo_code="SAVE15")
    assert (large["tier_discount_cents"], large["promo_discount_cents"]) == (3000, 0)
    tied = billing.price_order(quantity=10, unit_price_cents=2000, tier="gold", promo_code="SAVE15")
    assert (tied["tier_discount_cents"], tied["promo_discount_cents"]) == (2000, 0)


def test_flat500_stacks_with_tiers_and_floors_at_zero():
    r = billing.price_order(quantity=10, unit_price_cents=100, tier="gold", promo_code="FLAT500")
    assert (r["tier_discount_cents"], r["promo_discount_cents"], r["total_cents"]) == (100, 500, 400)
    tiny = billing.price_order(quantity=3, unit_price_cents=100, promo_code="FLAT500")
    assert tiny["total_cents"] == 0


@pytest.mark.parametrize(
    "kwargs",
    [
        {"quantity": 0, "unit_price_cents": 100},
        {"quantity": -3, "unit_price_cents": 100},
        {"quantity": 1, "unit_price_cents": -1},
        {"quantity": 1, "unit_price_cents": 100, "tier": "platinum"},
        {"quantity": 1, "unit_price_cents": 100, "promo_code": "BOGUS"},
        {"quantity": 1, "unit_price_cents": 100, "promo_code": "save15"},
    ],
)
def test_invalid_inputs_raise_value_error(kwargs):
    with pytest.raises(ValueError):
        billing.price_order(**kwargs)
