# Modernization and Migration

Migration patterns for upgrading legacy Python backends from Pydantic v1 + SQLAlchemy 1.4 to Pydantic v2 + SQLAlchemy 2.0, plus shared-library extraction strategy for duplicated core infrastructure.

## What this skill covers

- **Pydantic v1 → v2**: `@validator` → `@field_validator`, `Config` → `model_config`, `BaseSettings` import move
- **SQLAlchemy 1.4 → 2.0**: `declarative_base` → `DeclarativeBase`, `Column` → `Mapped`/`mapped_column`, `Query` → `select()`
- **Shared library extraction**: Identifying duplicated core infrastructure (BaseDao, ConnectionHandler, routing) across multiple services and extracting to a shared package
- **Golden reference template**: Using a cleanest reference service as the canonical modern service structure

## How to apply

1. **For new services**: Use the reference service as the template. Start with Pydantic v2 + SQLAlchemy 2.0. Do not copy legacy service patterns.
2. **For Pydantic v1→v2 migration**: Follow the reference guide in `references/pydantic-v1-to-v2.md`. Key changes: `@validator` → `@field_validator`, `Config` → `model_config`, `BaseSettings` import.
3. **For SQLAlchemy 1.4→2.0 migration**: Follow `references/sqlalchemy-14-to-20.md`. Key changes: `declarative_base` → `DeclarativeBase`, `Column` → `Mapped`, `session.query()` → `select()`.
4. **For shared library extraction**: Follow `references/shared-internal-library.md`. Extract BaseDao, ConnectionHandler, routing utilities to a shared internal package. Services adopt incrementally.

## Provenance

- **Codebase-derived**: Derived from real-world production Python/FastAPI and React services contrasting legacy patterns (Pydantic v1 `@validator`, `class Config`, SQLAlchemy 1.4 `declarative_base`) against modern patterns (Pydantic v2 `@field_validator`, `model_config = ConfigDict`, SQLAlchemy 2.0 `DeclarativeBase` + `Mapped`). Duplicated core/ files confirmed via code inspection across multiple services.
- **Internet-confirmed**: Pydantic v2 migration guide (official Pydantic docs), SQLAlchemy 2.0 migration guide (official SQLAlchemy docs), Mapped/mapped_column pattern (SQLAlchemy 2.0 declarative style documentation).
- **Honesty caveats**: Shared library extraction is a **recommendation** (not yet implemented in all organizations); the duplication pattern is proven, but adoption varies by organization.
