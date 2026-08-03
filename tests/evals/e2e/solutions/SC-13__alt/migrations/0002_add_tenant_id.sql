-- Tenant boundary for orders, applied in the safe three-step shape:
-- add nullable, backfill, then lock down. Tenant ids are issued by the
-- (external) control plane, so no local tenants table is created here.
ALTER TABLE orders ADD COLUMN tenant_id BIGINT;

-- Claim any pre-boundary rows for the default tenant before tightening.
UPDATE orders SET tenant_id = 1 WHERE tenant_id IS NULL;

ALTER TABLE orders ALTER COLUMN tenant_id SET NOT NULL;

CREATE INDEX idx_orders_tenant_id ON orders (tenant_id);
