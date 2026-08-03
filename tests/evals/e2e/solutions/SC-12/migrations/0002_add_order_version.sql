-- Optimistic concurrency for orders: every row carries a version that
-- conditional updates must match (and bump) or report a conflict.
ALTER TABLE orders ADD COLUMN version INTEGER NOT NULL DEFAULT 1;
