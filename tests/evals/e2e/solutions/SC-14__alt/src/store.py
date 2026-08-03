"""Order lookups. Pure SQL construction so the logic is testable without a live database."""


def orders_for_customer(customer_id: int) -> str:
    return f"SELECT * FROM orders WHERE customer_id = {customer_id}"


def customer_order_totals(customer_ids: list) -> str:
    """Single aggregate query for every requested customer via a VALUES join.

    Replaces the previous one-query-per-customer construction; customers with
    no orders still appear, with a total of 0.
    """
    rows = []
    for cid in customer_ids:
        rows.append(f"({int(cid)})")
    values = ", ".join(rows)
    return (
        "SELECT wanted.customer_id, COALESCE(SUM(o.total_cents), 0) AS total_cents "
        f"FROM (VALUES {values}) AS wanted(customer_id) "
        "LEFT JOIN orders o ON o.customer_id = wanted.customer_id "
        "GROUP BY wanted.customer_id"
    )


def recent_orders_by_status(status: str, limit: int = 100) -> str:
    return (
        "SELECT id, customer_id, total_cents, placed_at FROM orders "
        f"WHERE status = '{status}' ORDER BY placed_at DESC LIMIT {limit}"
    )
