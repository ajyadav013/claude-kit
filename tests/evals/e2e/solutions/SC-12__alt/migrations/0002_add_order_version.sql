-- Add the optimistic-lock column to orders.
-- Writers are expected to issue
--   UPDATE orders SET ..., version = version + 1 WHERE id = $1 AND version = $2
-- and treat zero rows affected as a concurrency conflict.
ALTER TABLE orders ADD COLUMN version INTEGER NOT NULL DEFAULT 1;
