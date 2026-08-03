"""Order lookups. Pure SQL construction so the logic is testable without a live database.

Caller-supplied values are bound as parameters rather than interpolated into the
statement text, so the SQL string is constant regardless of the input.
"""


def orders_for_customer(customer_id: int) -> str:
    return "SELECT * FROM orders WHERE customer_id = %s"


def customer_order_totals(customer_ids: list) -> list:
    """One query per customer."""
    return [orders_for_customer(cid) for cid in customer_ids]


def recent_orders_by_status(status: str, limit: int = 100) -> str:
    return (
        "SELECT id, customer_id, total_cents, placed_at FROM orders "
        "WHERE status = %s ORDER BY placed_at DESC LIMIT %s"
    )
