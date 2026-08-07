import pytest

from billing import price_order


def test_graduated_band_boundaries():
    assert price_order(quantity=10, unit_price_cents=100)["subtotal_cents"] == 1000
    assert price_order(quantity=11, unit_price_cents=100)["subtotal_cents"] == 1090
    assert price_order(quantity=50, unit_price_cents=100)["subtotal_cents"] == 4600
    assert price_order(quantity=51, unit_price_cents=100)["subtotal_cents"] == 4675
    assert price_order(quantity=60, unit_price_cents=100)["subtotal_cents"] == 5350


def test_band_line_rounds_half_up_per_band():
    # 10*25 + round_half_up(1*25*0.90 = 22.5) = 250 + 23
    assert price_order(quantity=11, unit_price_cents=25)["subtotal_cents"] == 273
    # band line rounds as one line, not per unit: 40*105*0.90 = 3780 exactly
    assert price_order(quantity=50, unit_price_cents=105)["subtotal_cents"] == 4830


def test_tier_discounts():
    silver = price_order(quantity=10, unit_price_cents=101, tier="silver")
    assert silver["tier_discount_cents"] == 51  # 50.5 rounds half up
    assert silver["total_cents"] == 959
    gold = price_order(quantity=10, unit_price_cents=100, tier="gold")
    assert gold["tier_discount_cents"] == 100


def test_save15_applies_after_tier_and_caps():
    r = price_order(quantity=10, unit_price_cents=100, tier="silver", promo_code="SAVE15")
    assert (r["tier_discount_cents"], r["promo_discount_cents"], r["total_cents"]) == (50, 143, 807)
    big = price_order(quantity=200, unit_price_cents=100, promo_code="SAVE15")
    assert big["promo_discount_cents"] == 2000  # capped


def test_gold_save15_exclusive_better_option_tie_goes_to_tier():
    promo_wins = price_order(quantity=10, unit_price_cents=100, tier="gold", promo_code="SAVE15")
    assert (promo_wins["tier_discount_cents"], promo_wins["promo_discount_cents"]) == (0, 150)
    tier_wins = price_order(quantity=10, unit_price_cents=3000, tier="gold", promo_code="SAVE15")
    assert (tier_wins["tier_discount_cents"], tier_wins["promo_discount_cents"]) == (3000, 0)
    tie = price_order(quantity=10, unit_price_cents=2000, tier="gold", promo_code="SAVE15")
    assert (tie["tier_discount_cents"], tie["promo_discount_cents"]) == (2000, 0)


def test_flat500_never_exceeds_remainder():
    r = price_order(quantity=3, unit_price_cents=100, promo_code="FLAT500")
    assert (r["promo_discount_cents"], r["total_cents"]) == (300, 0)


def test_validation():
    with pytest.raises(ValueError):
        price_order(quantity=0, unit_price_cents=100)
    with pytest.raises(ValueError):
        price_order(quantity=1, unit_price_cents=-1)
    with pytest.raises(ValueError):
        price_order(quantity=1, unit_price_cents=100, tier="platinum")
    with pytest.raises(ValueError):
        price_order(quantity=1, unit_price_cents=100, promo_code="save15")
