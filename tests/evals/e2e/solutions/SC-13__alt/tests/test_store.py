import pytest

import store


def test_orders_for_customer_targets_the_orders_table():
    assert "FROM orders" in store.orders_for_customer(7, tenant_id=1)


def test_totals_cover_every_requested_customer():
    assert len(store.customer_order_totals([1, 2, 3], tenant_id=1)) == 3


def test_recent_orders_are_newest_first():
    sql = store.recent_orders_by_status("paid", tenant_id=1)
    assert "ORDER BY placed_at DESC" in sql


def test_every_lookup_carries_the_tenant_predicate():
    scope = store.TenantScope(9)
    for sql in [
        scope.orders_for_customer(3),
        scope.recent_orders_by_status("paid"),
        *scope.customer_order_totals([4, 5]),
    ]:
        where_clause = sql.split("WHERE", 1)[1]
        assert "tenant_id = 9" in where_clause


def test_missing_or_none_tenant_is_rejected():
    with pytest.raises(TypeError):
        store.recent_orders_by_status("paid")  # tenant_id is required, keyword-only
    with pytest.raises(store.UnscopedQueryError):
        store.TenantScope(None)
