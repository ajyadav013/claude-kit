# Example Patterns

Representative code patterns from production FastAPI services. All credentials/hosts redacted.

## Reference Service A (cleanest reference)

**SQLAlchemy 2.0 + DeclarativeBase + versioned domains + server-only (no entrypoint.py)**

Key files:
- `app/application.py` — `get_app()` factory, CORS middleware, ORJSONResponse, lifespan
- `app/router.py` — `api_router` aggregation, health checks, versioned domain routers under `/v1`
- `app/routing.py` — `CustomRequestRoute(APIRoute)` for request logging, timing, exception handling
- `app/connection.py` — `ConnectionManager` singleton (via `__new__`), `ConnectionHandler` with `.session`/`.redis` properties, RLS + schema-switching helpers
- `app/dao.py` — `BaseDao` with create/get_by_pk/update_by_pk/delete_by_pk/get_by_filter/get_paginated_response/bulk_insert/bulk_update
- `app/database.py` — `class Base(DeclarativeBase): pass`
- `app/lifetime.py` — `@asynccontextmanager async def lifespan(app: FastAPI)`
- `app/main.py` — uvicorn runner (server-only deployment)
- `config/settings.py` — `Settings(BaseSettings)` with typed env vars, module-level `settings = Settings()`
- `app/identity/v1/router.py` — versioned domain router example
- `app/access/v1/router.py` — versioned domain router example
- `app/services/` — Kafka, Temporal, events, workflows (under domain package, not root)

**Deployment**: Server-only (Dockerfile CMD: `gunicorn app.application:get_app()`). No MODE-based entrypoint.py; consumers/workers would be separate repos if needed.

**Key patterns**: Application factory, ConnectionManager singleton, BaseDao, SQLAlchemy 2.0 DeclarativeBase, versioned domain layout.

---

## Reference Service B (large service, flat domains)

**~48 flat domain modules, configargparse-based config, SQLAlchemy 1.4**

Key files:
- `entrypoint.py` — MODE dispatcher (server/consumer/worker/temporal_worker/cron)
- `config/docker_config.py` — `Settings(BaseSettings)`, `loaded_config = Settings()` singleton, imports `docker_args` from `config_parser`
- `config/config_parser.py` — configargparse-based YAML/env merging (docker_args)
- `src/main.py` — uvicorn runner, router aggregation (equivalent to app/application.py + app/router.py combined)
- `src/db/connection.py` — `ConnectionManager` (Singleton metaclass), `ConnectionHandler`, `get_connection_handler_for_app`
- `src/product/router.py`, `src/category/router.py`, etc. — flat domain modules with `router.py`, `service.py`, `dao.py`, `models.py`, `schemas.py`, `helper.py`, `constant.py`

Snippet from `entrypoint.py`:

```python
MODE = os.environ.get("MODE")

if MODE == "server":
    from src.main import main as server_main
    server_main()

elif MODE == "consumer":
    from services.kafka.consumer.consumer import main as consumer_main
    asyncio.run(execute_mode(consumer_main))

elif MODE == "temporal_worker":
    from temporal.run import worker_main
    worker_mode = loaded_config.WORKER_MODE
    temporal_queue = loaded_config.TEMPORAL_QUEUE
    asyncio.run(execute_mode(worker_main, worker_mode, temporal_queue))
```

Snippet from `config/docker_config.py`:

```python
class Settings(BaseSettings):
    class Config:
        env_file = "../../.env"
        env_file_encoding = "utf-8"
    
    ENV: str = args.ENV
    HOSTNAME: str = args.HOST
    POSTGRES_READ_WRITE: str
    # ... more env vars

loaded_config = Settings()
```

**Key patterns**: Multi-mode entrypoint dispatcher, configargparse integration, flat domain layout (single-file per concern).

---

## Reference Service D (multi-deployment variant)

**SERVER_TYPE-gated routers, root_path rewriting for OpenAPI**

Key files:
- `entrypoint.py` — MODE dispatcher (server/consumer)
- `app/application.py` — `get_app()` with `root_path=f"/service/{loaded_config.SERVER_TYPE}/{product_path}"`, `custom_openapi()` rewrites paths
- `app/router.py` — conditional `include_router()` based on `loaded_config.SERVER_TYPE` (public/internal/platform/webhook)
- `config/docker_config.py` — `loaded_config` singleton, `SERVER_TYPE` env var

Snippet from `app/application.py`:

```python
product_path = "product/feature"

app = FastAPI(
    debug=loaded_config.debug,
    default_response_class=ORJSONResponse,
    lifespan=lifespan,
    root_path=f"/service/{loaded_config.SERVER_TYPE}/{product_path}",
)

def custom_openapi(app: FastAPI):
    openapi_schema = get_openapi(...)
    url_prefix = f"/service/{loaded_config.SERVER_TYPE}/{product_path}"
    paths = {}
    for path, path_item in openapi_schema["paths"].items():
        paths[f"{url_prefix}{path}"] = path_item
    openapi_schema["paths"] = paths
    return openapi_schema
```

Snippet from `app/router.py`:

```python
api_router_prefix = APIRouter(prefix="/v1.0")

if loaded_config.SERVER_TYPE == "public":
    api_router_prefix.include_router(order_router, tags=["Orders v1.0"])

elif loaded_config.SERVER_TYPE == "internal":
    api_router_prefix.include_router(order_router, tags=["Orders v1.0"])
    api_router_prefix.include_router(config_router, tags=["Config v1.0"])

elif loaded_config.SERVER_TYPE == "platform":
    api_router_prefix.include_router(config_router, tags=["Config v1.0"])

elif loaded_config.SERVER_TYPE == "webhook":
    api_router_prefix.include_router(webhook_router, tags=["Webhooks v1.0"])
```

**Key patterns**: Multi-deployment pattern (single codebase, environment-gated routers), root_path for sub-mounted services.

---

## Reference Service C (monorepo variant)

**apps/ + packages/ + services/ monorepo structure**

Key directories:
- `apps/api/` — main API service (application.py, router.py, lifetime.py)
- `apps/orchestrator/` — workflow orchestration service
- `apps/node_workers/` — background task workers
- `apps/signal_forwarder/` — event forwarder
- `packages/common/` — shared utilities
- `packages/contracts/` — API contracts (jsonschemas)
- `packages/db/` — shared database models/alembic
- `packages/sdk/` — internal SDK for service-to-service calls
- `services/` — Kafka, Temporal infra packages

**Key patterns**: Monorepo layout for multi-service codebases sharing common packages; apps/ for deployable units, packages/ for shared libs.

---

## Common patterns across all repos

1. **MODE-based entrypoint**: All repos dispatch on `MODE` env var to run server/consumer/worker/cron in a single Docker image.
2. **ConnectionManager singleton**: All repos use a singleton pattern (via `__new__` or Singleton metaclass) to manage the async engine and session factory.
3. **ConnectionHandler per-request**: All repos yield a handler via FastAPI dependency, close session on teardown.
4. **BaseDao**: All repos provide a base DAO with CRUD, pagination, soft-delete.
5. **pydantic-settings**: All repos use `Settings(BaseSettings)` for typed env vars, module-level singleton `loaded_config` or `settings`.
6. **ORJSONResponse**: All repos set `default_response_class=ORJSONResponse` for performance.
7. **Health checks**: All repos expose `/_healthz` and `/_readyz` endpoints.
8. **CORS middleware**: All repos add `CORSMiddleware` with explicit `allow_origins`, `allow_methods`, `allow_headers`.
