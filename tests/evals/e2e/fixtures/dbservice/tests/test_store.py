from store import customer_order_totals, orders_for_customer, recent_orders_by_status


def test_orders_for_customer_targets_the_orders_table():
    assert "FROM orders" in orders_for_customer(7)


def test_totals_cover_every_requested_customer():
    assert len(customer_order_totals([1, 2, 3])) == 3


def test_recent_orders_are_newest_first():
    assert "ORDER BY placed_at DESC" in recent_orders_by_status("paid")
