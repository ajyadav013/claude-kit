"""Order lookups. Pure SQL construction so the logic is testable without a live database.

Every lookup is scoped to a single tenant. There is deliberately no code path that
builds an orders query without a tenant predicate: tenant_id is a required
keyword-only argument on every module-level lookup, and a missing (None) tenant
raises UnscopedQueryError instead of falling back to a global query.
"""


class UnscopedQueryError(Exception):
    """Raised when an order lookup would be built without a tenant boundary."""


def _require_tenant(tenant_id):
    if tenant_id is None:
        raise UnscopedQueryError("order lookups must be scoped to a tenant")
    return int(tenant_id)


def orders_for_customer(customer_id: int, *, tenant_id: int) -> str:
    tid = _require_tenant(tenant_id)
    return (
        "SELECT * FROM orders "
        f"WHERE tenant_id = {tid} AND customer_id = {int(customer_id)}"
    )


def customer_order_totals(customer_ids: list, *, tenant_id: int) -> list:
    """One tenant-scoped query per customer."""
    tid = _require_tenant(tenant_id)
    return [orders_for_customer(cid, tenant_id=tid) for cid in customer_ids]


def recent_orders_by_status(status: str, limit: int = 100, *, tenant_id: int) -> str:
    tid = _require_tenant(tenant_id)
    return (
        "SELECT id, customer_id, total_cents, placed_at FROM orders "
        f"WHERE tenant_id = {tid} AND status = '{status}' "
        f"ORDER BY placed_at DESC LIMIT {int(limit)}"
    )


class TenantScope:
    """Ergonomic wrapper: fix the tenant once, then run any lookup against it."""

    def __init__(self, tenant_id):
        self.tenant_id = _require_tenant(tenant_id)

    def orders_for_customer(self, customer_id: int) -> str:
        return orders_for_customer(customer_id, tenant_id=self.tenant_id)

    def customer_order_totals(self, customer_ids: list) -> list:
        return customer_order_totals(customer_ids, tenant_id=self.tenant_id)

    def recent_orders_by_status(self, status: str, limit: int = 100) -> str:
        return recent_orders_by_status(status, limit, tenant_id=self.tenant_id)
