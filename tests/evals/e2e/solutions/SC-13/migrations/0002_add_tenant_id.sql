-- Tenant boundary: every order now belongs to exactly one tenant.
CREATE TABLE tenants (
    id          BIGSERIAL PRIMARY KEY,
    name        TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Existing rows (if any) are claimed by a bootstrap tenant so the column
-- can be NOT NULL from day one.
INSERT INTO tenants (name) VALUES ('bootstrap');

ALTER TABLE orders
    ADD COLUMN tenant_id BIGINT NOT NULL DEFAULT 1 REFERENCES tenants(id);

ALTER TABLE orders ALTER COLUMN tenant_id DROP DEFAULT;

CREATE INDEX idx_orders_tenant_id ON orders (tenant_id);
