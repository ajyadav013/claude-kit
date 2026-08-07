import pytest
from store import (
    TenantScope,
    UnscopedQueryError,
    customer_order_totals,
    orders_for_customer,
    recent_orders_by_status,
)


def test_orders_for_customer_targets_the_orders_table():
    assert "FROM orders" in orders_for_customer(7, tenant_id=42)


def test_orders_for_customer_is_tenant_scoped():
    sql = orders_for_customer(7, tenant_id=42)
    assert "tenant_id = 42" in sql and "customer_id = 7" in sql


def test_totals_cover_every_requested_customer():
    assert len(customer_order_totals([1, 2, 3], tenant_id=42)) == 3


def test_recent_orders_are_newest_first():
    assert "ORDER BY placed_at DESC" in recent_orders_by_status("paid", tenant_id=42)


def test_unscoped_lookups_are_impossible():
    with pytest.raises(TypeError):
        orders_for_customer(7)  # tenant_id is required and keyword-only
    with pytest.raises(UnscopedQueryError):
        orders_for_customer(7, tenant_id=None)


def test_tenant_scope_fixes_the_tenant_once():
    scope = TenantScope(42)
    assert "tenant_id = 42" in scope.orders_for_customer(7)
    with pytest.raises(UnscopedQueryError):
        TenantScope(None)
