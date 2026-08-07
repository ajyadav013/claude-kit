-- Initial schema. Applied by hand; there is no migration runner yet.
CREATE TABLE customers (
    id          BIGSERIAL PRIMARY KEY,
    email       TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE orders (
    id           BIGSERIAL PRIMARY KEY,
    customer_id  BIGINT NOT NULL REFERENCES customers(id),
    status       TEXT NOT NULL,
    total_cents  INTEGER NOT NULL,
    placed_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
