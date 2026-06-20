# python-dao-and-database

Standard DAO patterns and database session lifecycle for async SQLAlchemy and MongoDB.

## What this skill covers

- **BaseDao abstraction**: shared async data-access base with CRUD, pagination, filtering, sorting, bulk operations, and partition management
- **Session lifecycle**: ConnectionManager (Singleton) / ConnectionHandler patterns with async_scoped_session and FastAPI dependency injection
- **Pagination**: `get_paginated_response` with count queries, sorting, offset/limit, and pagination metadata
- **Bulk operations**: efficient `bulk_add_objects` (add_all), inefficient `bulk_update` (per-row loops)
- **Transactions**: manual commit patterns, minimal rollback usage (anti-pattern), row-level locking, isolation levels
- **SQLAlchemy 1.4 vs 2.0**: side-by-side model and query idioms (declarative_base vs DeclarativeBase, Column vs Mapped/mapped_column)
- **Eager loading**: selectinload, joinedload, subqueryload to prevent N+1 queries
- **Query optimization**: load_only, defer, count optimization, query profiling
- **MongoDB**: static-class DAO with sync pymongo (NOT motor), bulk upsert, index creation on startup
- **Alembic migrations**: schema evolution patterns for production systems

## Source evidence

This skill is derived from real-world production Python/FastAPI services across multiple domains (e-commerce platforms, analytics engines, billing systems, data pipelines). The patterns represent actual battle-tested code from:

- SQLAlchemy 2.0 services with Mapped/mapped_column, typed relationships, and mixin patterns
- FastAPI services using BaseDao with QueryFilter DSL, partition management, and connection pooling
- Services with both optimal (async_scoped_session) and anti-pattern (plain sessionmaker) implementations
- MongoDB-based services using sync pymongo with static-class DAOs and bulk upsert patterns

## How to apply

1. **Read SKILL.md** for the canonical conventions.
2. **Check references/** for deep dives on BaseDao, session lifecycle, SQLAlchemy version differences, eager loading, and MongoDB.
3. **Use the skeleton** to scaffold a new DAO or connection handler.
4. **Review existing DAOs** for the anti-patterns listed (missing async_scoped_session, inefficient bulk_update, no rollback, module-level sessions, N+1 queries).
5. **When migrating SQLAlchemy 1.4 → 2.0**, consult `sqlalchemy-1x-vs-2x.md` for the typed-column migration.
6. **When debugging slow queries**, enable `echo=True` on the engine and check `advanced-query-patterns.md` for eager loading and optimization techniques.
7. **For schema changes**, follow the alembic migration patterns in `advanced-query-patterns.md`.

## Provenance

- **Codebase-derived**: BaseDao method surface, ConnectionManager/ConnectionHandler patterns, pagination implementation, QueryFilter DSL, bulk operations, transaction anti-patterns, MongoDB static-class DAO, exact file paths, SQLAlchemy 1.4/2.0 usage per repo
- **Internet-confirmed**: None (all patterns are directly observed from the codebases)
