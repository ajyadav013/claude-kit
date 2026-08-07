"""Stock-keeping helpers for a warehouse service."""

REORDER_MULTIPLIER = 3


def needs_restock(stock: int, threshold: int) -> bool:
    """Whether an item must be reordered.

    An item needs restocking once its stock has fallen **to** the reorder
    threshold or below it. Stock exactly equal to the threshold has reached
    the threshold, so it needs restocking.
    """
    return stock <= threshold


def reorder_quantity(stock: int, threshold: int) -> int:
    """How many units to order so stock reaches its target level.

    The target level is ``threshold * REORDER_MULTIPLIER``. Items that do not
    need restocking are ordered in quantity zero.
    """
    if not needs_restock(stock, threshold):
        return 0
    return threshold * REORDER_MULTIPLIER - stock
