# Database Performance (PostgreSQL + SQLAlchemy 2.0 async)

Performance rules for the data layer. The dominant failure modes in a multi-tenant async app are **N+1 queries**, **missing composite indexes on tenant-scoped lookups**, and **offset pagination on large tables**. Treat these as defects, not nice-to-haves.

> Overlay rule — installed only when PostgreSQL is selected. Complements the general patterns in
> `.claude/rules/postgres-patterns.md`. Adapted from a portfolio project's database-performance rule.

## N+1 Queries — the #1 offender

```python
# BAD — lazy-loads relationship once per row (N+1)
orgs = (await db.execute(select(Organization))).scalars().all()
for o in orgs:
    print(o.members)            # fires a query each iteration

# GOOD — eager-load in one round trip
stmt = select(Organization).options(selectinload(Organization.members))
orgs = (await db.execute(stmt)).scalars().all()
```

- **`selectinload`** for collections (one-to-many / many-to-many) — second query with `IN (...)`, no row multiplication.
- **`joinedload`** for to-one (many-to-one / one-to-one) — single JOIN.
- Never access a relationship inside a loop without eager-loading it first.
- Watch async lazy-loading: a lazy attribute access outside the session/greenlet raises — eager-load deliberately.

## Indexes — especially tenant-scoped

- Every tenant-scoped table needs a **composite index leading with the tenant key** (e.g. `organization_id`): `Index("ix_<table>_org_<col>", "organization_id", "<filter_or_sort_col>")`. A bare tenant-key index is not enough when you also filter/sort by another column.
- Index foreign keys used in JOINs and columns used in `WHERE`, `ORDER BY`, and `UNIQUE` constraints.
- Unique constraints in a multi-tenant app are usually **per-tenant**: `UniqueConstraint("organization_id", "email")`, not global on `email`.
- Add the index in the **same migration** as the column/query (see the migration patterns in `.claude/rules/postgres-patterns.md`).

## Pagination

- Prefer **keyset (cursor) pagination** for large or hot lists: `WHERE (organization_id = :org) AND (created_at, id) < (:cursor_ts, :cursor_id) ORDER BY created_at DESC, id DESC LIMIT :n`.
- `OFFSET` degrades linearly — acceptable only for small, bounded result sets (admin tables). Never `OFFSET` into the thousands.
- Always `ORDER BY` a unique tiebreaker (e.g. `id`) so pages are stable.

## Query hygiene

- Select only what you need; avoid loading large columns/relationships you won't use. Use `load_only(...)` / `selectinload` selectively.
- **Bulk** insert/update/delete instead of per-row loops (`insert().values([...])`, `update().where(...)`).
- Compute `COUNT` with care — `SELECT count(*)` over a huge filtered set is expensive; cache or approximate where product allows.
- Push filtering/aggregation into SQL; don't pull rows into Python to filter them.
- Wrap a logical unit of work in one transaction; don't open a transaction per row.

## Connection pool (asyncpg)

- Tune `create_async_engine(pool_size=..., max_overflow=..., pool_pre_ping=True, pool_recycle=...)` to fit the DB's `max_connections` and worker count. Default `pool_size=5` is often too small under load and too large × many workers.
- Don't hold a DB session across an external `await` (HTTP call) — you pin a pooled connection while idle.

## How to verify

```sql
EXPLAIN (ANALYZE, BUFFERS) <query>;   -- look for Seq Scan on big tables, high rows, nested loops over many rows
```
- Enable SQLAlchemy echo or query logging in dev to count queries per request — a request firing 30 queries for 10 rows is an N+1.
- Add a regression guard for hot endpoints: assert the query count stays bounded. (See the `load-testing` skill to drive that load.)

## Severity (per `.claude/rules/quality-gates.md`)

- Unbounded N+1 on a list endpoint, or a tenant-scoped query with no supporting index on a large table → **High**.
- `OFFSET` pagination on an unbounded list, missing FK index used in a hot JOIN → **Medium**.
- Over-fetching columns, sub-optimal pool sizing → **Low**.
