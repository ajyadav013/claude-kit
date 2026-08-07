"""Order lookups. Pure SQL construction so the logic is testable without a live database.

Independent second reference for SC-22: uses named bind parameters and string concatenation
rather than positional placeholders in a single literal, so a discriminator pinned to the
exact text of solution A fails here.
"""

_ORDER_COLUMNS = "id, customer_id, total_cents, placed_at"


def orders_for_customer(customer_id: int) -> str:
    return "SELECT * FROM orders" + " WHERE customer_id = %(customer_id)s"


def customer_order_totals(customer_ids: list) -> list:
    """One query per customer."""
    return [orders_for_customer(cid) for cid in customer_ids]


def recent_orders_by_status(status: str, limit: int = 100) -> str:
    return (
        "SELECT "
        + _ORDER_COLUMNS
        + " FROM orders WHERE status = %(status)s"
        + " ORDER BY placed_at DESC LIMIT %(limit)s"
    )
