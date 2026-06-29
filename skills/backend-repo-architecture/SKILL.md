---
name: backend-repo-architecture
description: Canonical backend repository structure for Python/FastAPI — multi-mode entrypoint, app factory, ConnectionManager, BaseDao, flat vs versioned layout. Use when scaffolding or reorganizing a FastAPI service.
---

# Backend Repository Architecture

A canonical backend archetype for Python/FastAPI services, derived from real-world production systems.

## When to use

- Scaffolding a new FastAPI backend service
- Reorganizing an existing backend to match team conventions
- Understanding the standard service layout and responsibilities
- Choosing between flat vs versioned domain layouts
- Setting up multi-mode deployment (server + workers + consumers)
- Implementing the standard config/connection/routing patterns

## Core conventions

All conventions below are derived from production Python/FastAPI services:
- **Reference service A** (cleanest reference, server-only, SQLAlchemy 2.0, versioned domains)
- **Reference service B** (largest ~48 domain modules, flat layout, MODE dispatcher)
- **Reference service C** (monorepo: apps/ + packages/, MODE dispatcher)
- **Reference service D** (multi-deployment: SERVER_TYPE router gating, MODE dispatcher)

**Entrypoint dispatcher** (used by services B, C, D):
- `entrypoint.py` at repo root dispatches on `MODE` environment variable
- Supported modes: `server`, `consumer`, `temporal_worker`, `worker`, `cron`, `webhook_server`
- `server` mode runs `uvicorn app.application:get_app --factory=True`
- Worker/consumer modes call `asyncio.run(service_main())` on the respective service module
- Each mode may initialize metrics/telemetry before dispatching
- **Note**: Service A is server-only (no entrypoint.py, Dockerfile runs gunicorn directly)

**Application factory** (app/application.py):
- `get_app() -> FastAPI` constructs the app instance
- Sets `debug=settings.DEBUG`, `lifespan=lifespan`, `default_response_class=ORJSONResponse`
- Includes `redirect_slashes=False` to prevent ambiguous routing
- Adds CORS middleware with `allow_origins`, `allow_credentials`, `allow_methods`, `allow_headers`
- Includes `api_router` via `app.include_router(api_router)`
- May mount additional ASGI apps (e.g., `/metrics` for Prometheus)
- Optionally sets `root_path` for multi-deployment routing

**Router aggregation** (app/router.py or src/main.py):
- `api_router = APIRouter()` aggregates all domain routers
- Health checks registered as `/_healthz` and `/_readyz`
- Domain routers included under version prefix (e.g., `/v1`)
- Routers may be conditionally registered based on `DEPLOYMENT_NAME` or `SERVER_TYPE` (multi-deployment variant)
- Uses `include_router(domain_router, prefix="/v1", tags=["Domain"])`

**Custom routing** (app/routing.py):
- `CustomRequestRoute(APIRoute)` provides centralized request/response logging, timing, exception handling
- Wraps all validation/HTTP/unhandled exceptions into a `ResponseData.error()` envelope
- Logs every request with method, path, status_code, duration
- Returns `ORJSONResponse` with consistent error format

**Connection management** (app/connection.py):
- `ConnectionManager` singleton (via `__new__` or Singleton metaclass) manages `AsyncEngine`, scoped session factory, and Redis client
- `async_scoped_session(sessionmaker(engine, expire_on_commit=False, class_=AsyncSession), scopefunc=current_task)`
- `ConnectionHandler` per-request wrapper provides lazy `.session` and `.redis` properties
- Supports RLS via `set_tenant_context(tenant_id)` and schema switching via `set_schema_context(schema_name)`
- `get_connection_handler()` dependency yields a handler and calls `handler.close()` on teardown

**Lifetime hooks** (app/lifetime.py):
- `@asynccontextmanager async def lifespan(app: FastAPI)` manages startup/shutdown
- Startup: `setup_logging()`, `ConnectionManager()`, Kafka producer, Temporal client, Redis
- Shutdown: close ConnectionManager, dispose engine, close Redis, shutdown telemetry

**Base DAO** (app/dao.py):
- `BaseDao` provides `create`, `get_by_pk`, `update_by_pk`, `delete_by_pk`, `get_by_filter`, `get_paginated_response`, `bulk_insert`, `bulk_update`
- Soft-delete aware: checks `is_deleted` and `deleted_at` attributes
- All queries go through `_execute_query(query)` which rolls back on error
- Pagination supports `page_size`, `page_number`, `sort_by`, `order_by` with column validation

**Database base** (app/database.py):
- SQLAlchemy 1.4 repos: `Base = declarative_base()`
- SQLAlchemy 2.0 repos: `class Base(DeclarativeBase): pass`
- All ORM models inherit from `Base`

**Config pattern** (config/settings.py or src/config/docker_config.py):
- `Settings(BaseSettings)` with pydantic-settings for typed environment variables
- Pattern A: single `Settings` class, module-level `settings = Settings()`
- Pattern B: `loaded_config = Settings()` singleton, plus `config_parser.py` for configargparse-based YAML/env merging
- All services consume `DATABASE_URL`, `REDIS_URL`, `DEBUG`, `CORS_ORIGINS`, `KAFKA_BOOTSTRAP_SERVERS`, `TEMPORAL_HOST`, etc.

**Domain layout: flat variant**:
- Top-level `src/<domain>/` for many domain modules
- Each module has `router.py`, `service.py`, `dao.py`, `models.py`, `schemas.py`, `helper.py`, `constant.py`
- Single-file per concern (no subdirectories within a domain)

**Domain layout: versioned variant**:
- `<pkg>/<domain>/v1/{router,service,dao,models,schemas,helper,workflows}.py`
- Allows side-by-side v1/v2 implementations

**Monorepo variant**:
- `apps/` (api, orchestrator, workers, forwarders)
- `packages/` (common, contracts, db, sdk)
- `services/` (infra packages like Kafka, Temporal)
- Each app has its own `application.py`, `router.py`, `lifetime.py`

**Multi-deployment variant**:
- Single codebase, `SERVER_TYPE` env var gates router inclusion (public/internal/platform/webhook)
- `custom_openapi()` rewrites paths with `root_path` like `/service/{SERVER_TYPE}/product/feature`
- Conditional `include_router()` based on `loaded_config.SERVER_TYPE`

## Skeleton / example

```
backend/
├── entrypoint.py              # MODE dispatcher (server/consumer/temporal_worker/cron) — OPTIONAL, omit for server-only
├── alembic/                   # DB migrations
├── alembic.ini
├── pyproject.toml
├── Dockerfile
├── app/                       # (or src/)
│   ├── application.py         # get_app() factory
│   ├── router.py              # api_router aggregation
│   ├── routing.py             # CustomRequestRoute (optional but recommended)
│   ├── connection.py          # ConnectionManager, ConnectionHandler, get_connection_handler
│   ├── dao.py                 # BaseDao
│   ├── database.py            # Base (declarative base)
│   ├── lifetime.py            # lifespan context manager
│   ├── main.py                # uvicorn runner (server mode)
│   ├── telemetry.py           # OpenTelemetry instrumentation (optional)
│   └── utils.py               # ResponseData, helpers
├── config/
│   ├── settings.py            # Settings(BaseSettings), settings singleton (pattern A)
│   ├── docker_config.py       # Settings(BaseSettings), loaded_config singleton (pattern B)
│   ├── config_parser.py       # configargparse (optional, pattern B)
│   └── logging.py             # setup_logging
├── services/                  # Kafka, Temporal config-driven infra (may be at root or under domain package)
│   ├── kafka/
│   │   ├── producer.py
│   │   └── consumer/
│   └── temporal/
└── <domain_pkg>/              # flat: src/<domain>/{router,service,dao,models,schemas}
    └── <domain>/v1/           # versioned: <pkg>/<domain>/v1/{router,service,dao,models,schemas}
```

**Flat domain example**:

```python
# src/product/router.py
from fastapi import APIRouter, Depends
from src.product.service import ProductService
from src.db.connection import get_connection_handler_for_app

product_router = APIRouter()

@product_router.get("/")
async def get_products(connection_handler = Depends(get_connection_handler_for_app)):
    service = ProductService(connection_handler=connection_handler)
    return await service.fetch_products(...)
```

**Versioned domain example**:

```python
# app/identity/v1/router.py
from fastapi import APIRouter
from app.identity.v1.user.router import user_router

identity_v1_router = APIRouter(prefix="/identity")
identity_v1_router.include_router(user_router, prefix="/users")
```

**Entrypoint MODE dispatch**:

```python
MODE = os.environ.get("MODE")

if MODE == "server":
    from src.main import main as server_main
    server_main()  # uvicorn app.application:get_app --factory

elif MODE == "consumer":
    from src.services.kafka.consumer.consumer import main as consumer_main
    asyncio.run(consumer_main())

elif MODE == "temporal_worker":
    from src.temporal.run import worker_main
    asyncio.run(worker_main(worker_mode, temporal_queue))

elif MODE == "cron":
    from src.crons.run import main as cron_main
    asyncio.run(cron_main())
```

**Application factory**:

```python
def get_app() -> FastAPI:
    initialize_telemetry()
    app = FastAPI(
        debug=settings.DEBUG,
        default_response_class=ORJSONResponse,
        lifespan=lifespan,
        docs_url="/docs" if settings.DEBUG else None,
    )
    app.include_router(api_router)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization"],
    )
    return app
```

**ConnectionHandler**:

```python
class ConnectionHandler:
    def __init__(self):
        self._session = None
        self._redis = None
        self._connection_manager = ConnectionManager()

    @property
    def session(self) -> AsyncSession:
        if not self._session:
            self._session = self._connection_manager.get_session_factory()()
        return self._session

    @property
    def redis(self) -> Redis:
        if not self._redis:
            self._redis = self._connection_manager.get_redis()
        return self._redis

    async def close(self):
        if self._session:
            await self._session.close()

async def get_connection_handler() -> AsyncGenerator[ConnectionHandler, None]:
    handler = ConnectionHandler()
    try:
        yield handler
    finally:
        await handler.close()
```

**Lifespan**:

```python
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    setup_logging()
    ConnectionManager()  # init singleton
    yield
    shutdown_telemetry()
    await ConnectionManager().close_connections()
```

**Multi-deployment router gating**:

```python
api_router_prefix = APIRouter(prefix="/v1.0")

if loaded_config.SERVER_TYPE == "public":
    api_router_prefix.include_router(shipment_router, tags=["Shipment v1.0"])

elif loaded_config.SERVER_TYPE == "internal":
    api_router_prefix.include_router(shipment_router, tags=["Shipment v1.0"])
    api_router_prefix.include_router(partner_config_router, tags=["Partner Config v1.0"])

elif loaded_config.SERVER_TYPE == "platform":
    api_router_prefix.include_router(partner_config_router, tags=["Partner Config v1.0"])

elif loaded_config.SERVER_TYPE == "webhook":
    api_router_prefix.include_router(clickpost_router, tags=["Click Post v1.0"])
```

## Anti-patterns to avoid

- **Hard-coding mode logic**: use the MODE env dispatcher pattern (when multi-mode needed), never inline `if` chains in application code
- **Direct session creation in routes**: always inject `ConnectionHandler` via `Depends(get_connection_handler)`
- **Multiple session factories**: one `ConnectionManager` singleton per process, never per-request engine creation
- **Non-lazy ConnectionHandler properties**: session/Redis must be created on first property access, not in `__init__`
- **Missing session close**: always use the `get_connection_handler` dependency generator to guarantee teardown
- **Skipping router prefixing**: domain routers must be included under `/v1` or similar version prefix
- **Custom error formats per route**: use `CustomRequestRoute` + `ResponseData.error()` for consistency
- **Mixing flat and versioned layouts**: pick one layout per service; do not hybrid
- **Application code in entrypoint.py**: entrypoint.py is a dispatcher only; all business logic in domain modules
- **Blocking I/O in async routes**: use async DAO methods, never sync SQLAlchemy or blocking Redis calls in async routes
- **Missing CORS middleware**: always configure explicit `allow_origins`, never use `["*"]` in production
- **Hardcoded connection strings**: always use pydantic-settings for DATABASE_URL, REDIS_URL; never inline credentials
- **Skipping lifespan context manager**: always use `@asynccontextmanager async def lifespan` for startup/shutdown, never global init code
- **Committing in DAO methods**: DAOs execute queries only; let service layer or route handler manage transaction boundaries via `session.commit()`
- **N+1 queries**: use `selectinload()` or `joinedload()` for relationships, profile queries with `DB_ECHO=True`

## References

- [repo-evidence.md](references/repo-evidence.md) — source repo file paths and representative snippets
- [structure-patterns.md](references/structure-patterns.md) — full directory tree skeleton, file responsibilities, flat vs versioned layouts
- [entrypoint-and-config.md](references/entrypoint-and-config.md) — MODE dispatch table, config pattern (docker_config/loaded_config/config_parser chain)
- [deployment-patterns.md](references/deployment-patterns.md) — Dockerfile patterns, Kubernetes deployments, multi-mode/multi-deployment/monorepo scaling, health checks, graceful shutdown
- [troubleshooting.md](references/troubleshooting.md) — common pitfalls, connection issues, routing problems, async gotchas, debugging techniques, performance troubleshooting
