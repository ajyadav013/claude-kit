-- Independent second reference for SC-10: a differently named partial index, created
-- IF NOT EXISTS, so a discriminator pinned to solution A's index name or exact DDL fails here.
CREATE INDEX IF NOT EXISTS orders_lookup_idx
    ON orders (status, placed_at);
