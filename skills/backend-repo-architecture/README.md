# Backend Repository Architecture Skill

Canonical backend repository structure and patterns for Python/FastAPI services.

## What this skill covers

- **Multi-mode entrypoint pattern**: MODE-based dispatcher (server/consumer/temporal_worker/cron/webhook_server)
- **FastAPI application factory**: `get_app()` construction, CORS, router assembly, custom routing
- **Connection management**: `ConnectionManager` singleton, `ConnectionHandler` per-request wrapper, RLS/schema-switching
- **Base DAO pattern**: Standard CRUD operations, pagination, soft-delete awareness, bulk operations
- **Config patterns**: pydantic-settings-based `Settings`, `loaded_config` singleton, configargparse integration
- **Domain layouts**: Flat vs versioned module organization
- **Lifecycle hooks**: lifespan context manager for startup/shutdown
- **Monorepo and multi-deployment variants**: apps + packages structure, SERVER_TYPE gating

## Provenance

Derived from real-world production Python/FastAPI services with variations including:
- A cleanest reference implementation (SQLAlchemy 2.0, DeclarativeBase, versioned domains, server-only)
- A large service with ~48 flat domain modules, MODE dispatcher, configargparse-based config
- A monorepo variant (apps/ + packages/ + services/, MODE dispatcher)
- A multi-deployment variant (SERVER_TYPE-gated routers, root_path rewriting, MODE dispatcher)

## How to apply

1. **Scaffolding a new service**: Copy the skeleton structure from `structure-patterns.md`, adapt `entrypoint.py` to your required modes, implement `application.py` factory.
2. **Reorganizing an existing service**: Align `app/` core files (application, router, routing, connection, dao, database, lifetime), move domain logic into flat or versioned layout.
3. **Understanding archetype**: Read `entrypoint-and-config.md` for MODE dispatch, `repo-evidence.md` for example patterns and signatures.
4. **Choosing domain layout**: Flat for rapid iteration, versioned for API evolution. Do not mix.

## Pattern validation

**Confirmed against external sources**:
- FastAPI application factory pattern: https://fastapi.tiangolo.com/advanced/events/ (lifespan context manager)
- SQLAlchemy async patterns: https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html (async_scoped_session, scopefunc=current_task)
- Pydantic-settings: https://docs.pydantic.dev/latest/concepts/pydantic_settings/ (BaseSettings, env_file)
