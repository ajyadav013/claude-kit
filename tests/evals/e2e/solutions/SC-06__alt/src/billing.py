"""Order pricing rules -- straight-line, branch-driven implementation.

Uses Decimal with ROUND_HALF_UP for every rounding step the rules require.
All public values are integer cents.
"""

from decimal import Decimal, ROUND_HALF_UP

_VALID_TIERS = ("standard", "silver", "gold")
_VALID_PROMOS = ("SAVE15", "FLAT500")

_SAVE15_CAP_CENTS = 2000
_FLAT500_CENTS = 500


def _cents(value):
    """Round a Decimal to whole cents, half up, and return an int."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def price_order(quantity, unit_price_cents, tier="standard", promo_code=None):
    """Compute subtotal, tier discount, promo discount and total in cents."""
    if quantity < 1:
        raise ValueError("quantity must be a positive integer")
    if unit_price_cents < 0:
        raise ValueError("unit_price_cents must not be negative")
    if tier not in _VALID_TIERS:
        raise ValueError("unknown customer tier: " + repr(tier))
    if promo_code is not None and promo_code not in _VALID_PROMOS:
        raise ValueError("unknown promo code: " + repr(promo_code))

    price = Decimal(unit_price_cents)

    # Graduated volume bands, each band line rounded half up on its own.
    full_units = quantity if quantity <= 10 else 10
    mid_units = 0 if quantity <= 10 else (quantity - 10 if quantity <= 50 else 40)
    top_units = 0 if quantity <= 50 else quantity - 50

    subtotal = _cents(full_units * price)
    if mid_units:
        subtotal += _cents(mid_units * price * Decimal("0.90"))
    if top_units:
        subtotal += _cents(top_units * price * Decimal("0.75"))

    tier_discount = 0
    promo_discount = 0

    if tier == "gold" and promo_code == "SAVE15":
        # Not combinable: pick the single better option, tie goes to the tier.
        gold_only = _cents(Decimal(subtotal) * Decimal("0.10"))
        save15_only = _cents(Decimal(subtotal) * Decimal("0.15"))
        if save15_only > _SAVE15_CAP_CENTS:
            save15_only = _SAVE15_CAP_CENTS
        if save15_only > gold_only:
            promo_discount = save15_only
        else:
            tier_discount = gold_only
    else:
        if tier == "silver":
            tier_discount = _cents(Decimal(subtotal) * Decimal("0.05"))
        elif tier == "gold":
            tier_discount = _cents(Decimal(subtotal) * Decimal("0.10"))

        remaining = subtotal - tier_discount
        if promo_code == "SAVE15":
            promo_discount = _cents(Decimal(remaining) * Decimal("0.15"))
            if promo_discount > _SAVE15_CAP_CENTS:
                promo_discount = _SAVE15_CAP_CENTS
        elif promo_code == "FLAT500":
            promo_discount = _FLAT500_CENTS if remaining >= _FLAT500_CENTS else remaining

    return {
        "subtotal_cents": subtotal,
        "tier_discount_cents": tier_discount,
        "promo_discount_cents": promo_discount,
        "total_cents": subtotal - tier_discount - promo_discount,
    }
