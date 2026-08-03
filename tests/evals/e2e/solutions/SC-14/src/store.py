"""Order lookups. Pure SQL construction so the logic is testable without a live database."""


def orders_for_customer(customer_id: int) -> str:
    return f"SELECT * FROM orders WHERE customer_id = {customer_id}"


def customer_order_totals(customer_ids: list) -> str:
    """One batched query for all requested customers (was one round trip per customer)."""
    ids = ", ".join(str(int(cid)) for cid in customer_ids)
    return (
        "SELECT customer_id, SUM(total_cents) AS total_cents FROM orders "
        f"WHERE customer_id IN ({ids}) GROUP BY customer_id"
    )


def recent_orders_by_status(status: str, limit: int = 100) -> str:
    return (
        "SELECT id, customer_id, total_cents, placed_at FROM orders "
        f"WHERE status = '{status}' ORDER BY placed_at DESC LIMIT {limit}"
    )
