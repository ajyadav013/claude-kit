# Alembic Migrations

Alembic migration setup and patterns for async SQLAlchemy derived from production FastAPI microservices.

## What this skill covers

- **Alembic setup**: `alembic.ini` config, `env.py` async engine pattern, `target_metadata` from Base
- **Async SQLAlchemy migrations**: `async_engine_from_config`, `connection.run_sync`, `asyncio.run`, `postgresql+asyncpg://` URL
- **Migration file patterns**: Revision naming (sequential, timestamp-hash, auto-hash), script.py.mako template, import conventions
- **Autogenerate workflow**: `alembic revision --autogenerate`, `compare_type` flag, `include_object` filtering
- **Multi-tenant migrations**: RLS policy creation, session variable USING clauses, admin bypass patterns
- **Offline vs online modes**: SQL script generation vs direct DB connection

## Source pattern examples

Derived from real-world production Python/FastAPI services:

- Cleanest reference service — async env.py, sequential revision naming (0001, 0002, ...), RLS migration pattern
- Large production service (~110 migrations) — timestamp-hash naming, include_object filtering for heartbeat tables, sync engine pattern
- Multiple async services — async env.py with compare_type, postgresql+asyncpg URL replacement, hash-based revision naming, model wildcard imports

## How to apply

1. **For new projects**: Copy the async env.py pattern from the reference examples; configure `alembic.ini` with empty `sqlalchemy.url`; import all models at top of `env.py`.
2. **For autogenerate**: Run `alembic revision --autogenerate -m "description"`; review generated migration; adjust column types/constraints if needed.
3. **For multi-tenant apps**: Use the RLS migration pattern from the multi-tenant examples for tenant-scoped tables; set session variables in connection handler.
4. **For large teams**: Use timestamp-hash revision naming (large production service pattern) to avoid merge conflicts on `down_revision`.

## Provenance

- **Codebase-derived**: Async env.py pattern (multiple async services), RLS policy USING clause (multi-tenant service), include_object filtering (large production service), compare_type flag (multiple services), revision naming conventions (sequential vs timestamp-hash vs auto-hash), NullPool for migrations (all services).
- **Internet-confirmed**: Alembic async engine documentation (https://alembic.sqlalchemy.org/en/latest/cookbook.html#using-asyncio-with-alembic), PostgreSQL RLS syntax (https://www.postgresql.org/docs/current/sql-createpolicy.html), asyncpg driver URL format (https://github.com/MagicStack/asyncpg).
