-- Every order lookup filters on status and orders by placed_at; without this the
-- planner falls back to a sequential scan of orders.
CREATE INDEX idx_orders_status_placed_at ON orders (status, placed_at DESC);
