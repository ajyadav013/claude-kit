"""Order pricing engine -- table-driven implementation.

All monetary values are integer cents. Rounding is half up (0.5 rounds
away from zero; all amounts here are non-negative), applied exactly where
the pricing rules say and nowhere else.
"""

# (highest unit index in band or None for open-ended, percent of unit price)
_BANDS = (
    (10, 100),   # units 1-10: full price
    (50, 90),    # units 11-50: 90%
    (None, 75),  # units 51+: 75%
)

_TIER_PERCENT = {"standard": 0, "silver": 5, "gold": 10}

# code -> (kind, value, cap_cents_or_None)
_PROMOS = {
    "SAVE15": ("percent", 15, 2000),
    "FLAT500": ("flat", 500, None),
}


def _half_up(numerator, denominator):
    """Round the non-negative rational numerator/denominator half up."""
    return (2 * numerator + denominator) // (2 * denominator)


def _pct_of(amount_cents, percent):
    """percent% of amount_cents, rounded half up to whole cents."""
    return _half_up(amount_cents * percent, 100)


def _graduated_subtotal(quantity, unit_price_cents):
    subtotal = 0
    lower = 0
    for upper, percent in _BANDS:
        top = quantity if upper is None else min(quantity, upper)
        band_units = top - lower
        if band_units <= 0:
            break
        subtotal += _pct_of(band_units * unit_price_cents, percent)
        lower = top
    return subtotal


def price_order(quantity, unit_price_cents, tier="standard", promo_code=None):
    """Price an order per the graduated band / tier / promo rules."""
    if quantity < 1:
        raise ValueError("quantity must be an integer >= 1")
    if unit_price_cents < 0:
        raise ValueError("unit_price_cents must be an integer >= 0")
    if tier not in _TIER_PERCENT:
        raise ValueError("unknown tier: %r" % (tier,))
    if promo_code is not None and promo_code not in _PROMOS:
        raise ValueError("unknown promo_code: %r" % (promo_code,))

    subtotal = _graduated_subtotal(quantity, unit_price_cents)

    if tier == "gold" and promo_code == "SAVE15":
        # Mutually exclusive: apply the single option with the lower total;
        # on a tie the tier option wins.
        tier_option = _pct_of(subtotal, _TIER_PERCENT["gold"])
        promo_option = min(_pct_of(subtotal, 15), 2000)
        if promo_option > tier_option:
            tier_discount, promo_discount = 0, promo_option
        else:
            tier_discount, promo_discount = tier_option, 0
    else:
        tier_discount = _pct_of(subtotal, _TIER_PERCENT[tier])
        remainder = subtotal - tier_discount
        if promo_code is None:
            promo_discount = 0
        else:
            kind, value, cap = _PROMOS[promo_code]
            if kind == "percent":
                promo_discount = _pct_of(remainder, value)
                if cap is not None and promo_discount > cap:
                    promo_discount = cap
            else:
                promo_discount = min(value, remainder)

    return {
        "subtotal_cents": subtotal,
        "tier_discount_cents": tier_discount,
        "promo_discount_cents": promo_discount,
        "total_cents": subtotal - tier_discount - promo_discount,
    }
