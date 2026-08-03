"""Order lookups, always scoped to a tenant.

All SQL construction lives inside TenantScope. The private _scoped_where()
composer hard-wires the tenant predicate as the first condition of every
query, so no code path in this module can produce an orders query without a
tenant boundary. The module-level functions are thin conveniences that create
a scope per call; their tenant_id argument is keyword-only and required.
"""


class UnscopedQueryError(Exception):
    """Raised when an order lookup would be built without a tenant boundary."""


class TenantScope:
    """All order lookups for exactly one tenant."""

    def __init__(self, tenant_id):
        if tenant_id is None:
            raise UnscopedQueryError(
                "a tenant is required: order lookups cannot be global"
            )
        self._tenant_id = int(tenant_id)

    def _scoped_where(self, *conditions: str) -> str:
        # The tenant predicate is structurally always condition #1.
        parts = (f"tenant_id = {self._tenant_id}",) + conditions
        return "WHERE " + " AND ".join(parts)

    def orders_for_customer(self, customer_id: int) -> str:
        where = self._scoped_where(f"customer_id = {int(customer_id)}")
        return f"SELECT * FROM orders {where}"

    def customer_order_totals(self, customer_ids: list) -> list:
        """One tenant-scoped query per customer."""
        return [self.orders_for_customer(cid) for cid in customer_ids]

    def recent_orders_by_status(self, status: str, limit: int = 100) -> str:
        where = self._scoped_where(f"status = '{status}'")
        return (
            f"SELECT id, customer_id, total_cents, placed_at FROM orders {where} "
            f"ORDER BY placed_at DESC LIMIT {int(limit)}"
        )


def orders_for_customer(customer_id: int, *, tenant_id: int) -> str:
    return TenantScope(tenant_id).orders_for_customer(customer_id)


def customer_order_totals(customer_ids: list, *, tenant_id: int) -> list:
    return TenantScope(tenant_id).customer_order_totals(customer_ids)


def recent_orders_by_status(status: str, limit: int = 100, *, tenant_id: int) -> str:
    return TenantScope(tenant_id).recent_orders_by_status(status, limit)
