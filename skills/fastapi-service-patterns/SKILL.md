---
name: fastapi-service-patterns
description: Encodes production FastAPI conventions covering app factory, lifespan hooks, custom request routing, structured exception handling, dependency injection, middleware stack, and the ResponseData envelope pattern. Use when building a new FastAPI service, adding routes or middleware, implementing structured error handling, or configuring application startup and shutdown.
---

Standardize FastAPI application structure, routing, middleware, and dependency injection following production service patterns.

## When to use

- Scaffolding a new FastAPI service or microservice
- Adding structured exception handling and logging to routes
- Implementing CORS, RBAC, or custom middleware
- Setting up database and Redis connections with proper lifecycle management
- Configuring lifespan startup/shutdown hooks
- Creating a custom route handler for request/response envelope patterns
- Implementing dependency injection for database sessions or auth context
- Building paginated list endpoints with consistent response format
- Adding multi-tenancy support with row-level security or schema isolation
- Migrating from deprecated `@app.on_event` to lifespan context manager

## Core conventions

1. **App factory pattern in `app/application.py`**: define `get_app() -> FastAPI` that creates the app, configures middleware (CORS, telemetry, security headers), includes routers, and returns a ready-to-serve instance. Use `FastAPI(debug=..., lifespan=lifespan, default_response_class=ORJSONResponse)`. Optional: `redirect_slashes=False` to prevent auto-redirects.

2. **Lifespan context manager in `app/lifetime.py`**: use `@asynccontextmanager async def lifespan(app: FastAPI)` to initialize resources (ConnectionManager, Redis, Kafka, Temporal, telemetry) on startup and close them on shutdown. The older `@app.on_event("startup"/"shutdown")` style is deprecated; prefer lifespan.

3. **Custom route handler in `app/routing.py`**: subclass `fastapi.routing.APIRoute` and override `get_route_handler()` to wrap every route with structured logging, timing, x-user-data header parsing into `request.state.user_data`, and exception handling that catches `RequestValidationError`, `HTTPException`, custom app exceptions, and generic `Exception`. Return `ORJSONResponse` with a `ResponseData` envelope.

4. **ResponseData envelope**: all responses use `ResponseData(success: bool, data: List | Dict, errors: List, identifier: str)`. Helpers `ResponseData.ok()` and `ResponseData.error()` construct success/error envelopes. Optional typed wrappers `ListDataResponse` and `DictDataResponse` for OpenAPI schema clarity.

5. **Dependency injection via `Depends`**: the primary dependency is `Depends(get_connection_handler)` which yields a `ConnectionHandler` that lazily provides `session: AsyncSession` and `redis: Redis` properties. Auth dependency `Depends(require_auth)` or `get_current_client` parses x-user-data JWT payload into `TokenData`. No DI container; plain FastAPI Depends.

6. **Router hierarchy**: three-tier structure—`app/router.py` defines `api_router: APIRouter` that includes health endpoints and versioned routers; `<domain>/v1/router.py` aggregates per-feature routers; individual feature routers define endpoints. Mount top-level router via `app.include_router(api_router)`. Optional: conditionally include routers based on `SERVER_TYPE` config.

7. **CORS middleware**: add with `app.add_middleware(CORSMiddleware, allow_origins=..., allow_credentials=True, allow_methods=[...], allow_headers=[...])`. Note the common anti-pattern `allow_origins=["*"]`—prefer explicit allow lists.

8. **Custom middleware stack**: RBAC middleware (`RbacMiddleware`) checks route tags `["skip_rbac"]` or `["public_authenticated"]` to bypass or gate access based on x-user-data role. Other middlewares: `PrometheusMiddleware`, `TraceIDMiddleware`, `TenantMiddleware`, `AuditMiddleware`, `SlowAPI` rate limiter.

9. **Validation error formatting**: in the custom route handler, catch `RequestValidationError` and `ValidationError`, extract `{"field": error["loc"][-1], "msg": error["msg"]}` from `exc.errors()`, and return with `error_code=["AE101"]` for validation errors. Use `HTTP_400_BAD_REQUEST`.

10. **OpenAPI customization**: use `custom_openapi()` to inject `root_path` into OpenAPI paths and conditionally add/remove headers per environment. Set via `app.openapi_schema = custom_openapi(app=app)`.

11. **All handlers are `async def`**: no sync route handlers. Background work is delegated to Temporal or Kafka, not `BackgroundTasks`.

12. **ConnectionHandler lazy session**: `ConnectionHandler` creates session only when `handler.session` is accessed; supports RLS via `set_tenant_context(tenant_id)`, schema switching via `set_schema_context(schema_name)`, and RLS bypass via `set_rls_bypass(enabled=True)`. Yielded via `get_connection_handler()` dependency and closed in finally block.

13. **Security headers middleware**: add response headers `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, `Permissions-Policy`, `Content-Security-Policy`, and conditional `Strict-Transport-Security` via an `@app.middleware("http")` function.

14. **BaseDao pattern for data access**: all domain DAOs inherit from `BaseDao` to get standard CRUD operations, paginated queries (`get_paginated_response`), soft-delete awareness, bulk operations, and automatic rollback on query failure. Each DAO receives `session: AsyncSession` in `__init__` and sets `self.db_model`. Common methods: `create()`, `get_by_id()`, `update()`, `delete()`, `get_paginated_response(query, page, page_size, sort_by)` which returns `(results, pagination_info)` tuple.

15. **Pydantic models for request/response serialization**: define separate `*Create`, `*Update`, `*Out` Pydantic models for input validation and output serialization. Output models use `model_config = ConfigDict(from_attributes=True)` for ORM compatibility. Convert ORM → Pydantic via `Model.model_validate(orm_obj)`, then Pydantic → dict via `.model_dump(mode="json")` before passing to `ResponseData`. Use `Field()` for validation constraints (min_length, max_length, pattern) and `@field_validator` for custom validation.

## Skeleton / example

```python
# app/application.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import ORJSONResponse
from app.lifetime import lifespan
from app.router import api_router
from config.settings import settings

def get_app() -> FastAPI:
    app = FastAPI(
        debug=settings.DEBUG,
        title="MyService",
        lifespan=lifespan,
        default_response_class=ORJSONResponse,
        redirect_slashes=False,
    )
    app.include_router(api_router)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Content-Type", "Authorization", "x-user-data"],
    )
    return app
```

```python
# app/lifetime.py
from contextlib import asynccontextmanager
from fastapi import FastAPI
from app.connection import ConnectionManager

@asynccontextmanager
async def lifespan(app: FastAPI):
    ConnectionManager()  # init DB/Redis pools
    yield
    await ConnectionManager().close_connections()
```

```python
# app/routing.py
import time
from typing import Callable
from fastapi import Request, Response
from fastapi.exceptions import HTTPException, RequestValidationError
from fastapi.responses import ORJSONResponse
from fastapi.routing import APIRoute
from starlette.status import HTTP_400_BAD_REQUEST, HTTP_500_INTERNAL_SERVER_ERROR
from app.utils import ResponseData

class CustomRequestRoute(APIRoute):
    def get_route_handler(self) -> Callable:
        original_route_handler = super().get_route_handler()

        async def custom_route_handler(request: Request) -> Response:
            start_time = time.perf_counter()
            try:
                response: Response = await original_route_handler(request)
                duration = time.perf_counter() - start_time
                logger.info("request_handled", method=request.method, path=request.url.path,
                            status_code=response.status_code, duration=round(duration, 4))
                return response
            except RequestValidationError as exc:
                errors = [f"{e['loc'][-1]}: {e['msg']}" for e in exc.errors()]
                return ORJSONResponse(
                    content=ResponseData.error(errors=errors, message="Validation error").model_dump(),
                    status_code=HTTP_400_BAD_REQUEST,
                )
            except HTTPException as exc:
                return ORJSONResponse(
                    content=ResponseData.error(errors=[exc.detail], message=exc.detail).model_dump(),
                    status_code=exc.status_code,
                )
            except Exception as exc:
                logger.exception("unhandled_exception", error=str(exc))
                return ORJSONResponse(
                    content=ResponseData.error(errors=[str(exc)], message="Internal server error").model_dump(),
                    status_code=HTTP_500_INTERNAL_SERVER_ERROR,
                )
        return custom_route_handler
```

```python
# app/connection.py
from typing import AsyncGenerator, Optional
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_scoped_session
from sqlalchemy.orm import sessionmaker
from redis.asyncio import Redis

class ConnectionManager:
    _instance: Optional["ConnectionManager"] = None
    _db_session_factory: Callable[..., AsyncSession]
    _redis: Redis

    def __new__(cls) -> "ConnectionManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            engine = create_async_engine(settings.DATABASE_URL, pool_pre_ping=True)
            cls._instance._db_session_factory = async_scoped_session(
                sessionmaker(engine, expire_on_commit=False, class_=AsyncSession),
                scopefunc=current_task,
            )
            cls._instance._redis = Redis.from_url(settings.REDIS_URL, decode_responses=True)
        return cls._instance

    async def close_connections(self) -> None:
        await self._db_engine.dispose()
        await self._redis.close()

class ConnectionHandler:
    _session: Optional[AsyncSession]
    _connection_manager: ConnectionManager

    def __init__(self) -> None:
        self._session = None
        self._connection_manager = ConnectionManager()

    @property
    def session(self) -> AsyncSession:
        if not self._session:
            self._session = self._connection_manager.get_session_factory()()
        return self._session

    async def close(self) -> None:
        if self._session:
            await self._session.close()

async def get_connection_handler() -> AsyncGenerator[ConnectionHandler, None]:
    handler = ConnectionHandler()
    try:
        yield handler
    finally:
        await handler.close()
```

```python
# domain/v1/serializers.py (Pydantic models)
from pydantic import BaseModel, ConfigDict, Field, EmailStr
from uuid import UUID
from datetime import datetime

class ItemCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str | None = None

class ItemOut(BaseModel):
    id: UUID
    name: str
    description: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
```

```python
# domain/v1/views.py (endpoint using DI and Pydantic)
from fastapi import Depends, HTTPException
from sqlalchemy import select
from app.connection import ConnectionHandler, get_connection_handler
from app.utils import ResponseData
from .serializers import ItemCreate, ItemOut

async def create_item(
    payload: ItemCreate,
    connection_handler: ConnectionHandler = Depends(get_connection_handler),
) -> ResponseData:
    dao = ItemDAO(connection_handler.session)
    item = await dao.create(**payload.model_dump())
    return ResponseData.ok(data=ItemOut.model_validate(item).model_dump(mode="json"), message="Item created")

async def list_items_paginated(
    page: int = 1,
    page_size: int = 20,
    connection_handler: ConnectionHandler = Depends(get_connection_handler),
) -> ResponseData:
    dao = ItemDAO(connection_handler.session)
    query = select(Item).where(Item.is_active == True)
    results, pagination_info = await dao.get_paginated_response(query, page, page_size, sort_by="created_at")
    return ResponseData.ok(
        data=[ItemOut.model_validate(r).model_dump(mode="json") for r in results],
        message="Items listed",
        pagination=pagination_info,
    )
```

## Anti-patterns to avoid

1. **`allow_origins=["*"]` in CORS**: overly permissive; use explicit domain lists.
2. **Legacy `@app.on_event("startup"/"shutdown")`**: deprecated; migrate to lifespan context manager.
3. **Sync route handlers**: all routes must be `async def` to leverage async DB/Redis.
4. **Using `BackgroundTasks` for long-running work**: delegate to Temporal/Kafka instead of in-process background tasks.
5. **Not catching validation errors in custom route**: wrap `RequestValidationError` and format errors consistently.
6. **Hardcoded connection strings in code**: load from settings/env (e.g., `settings.DATABASE_URL`).
7. **Missing RLS context in multi-tenant apps**: if using RLS, call `set_tenant_context()` or `set_schema_context()` before queries.
8. **Not using BaseDao for data access**: inheriting from `BaseDao` standardizes CRUD operations, pagination, and error handling across all domain DAOs.
9. **Committing inside DAO methods without explicit control**: let the caller (service layer or route handler) control transaction boundaries via `connection_handler.session_commit()` or rely on FastAPI request lifecycle.
10. **Returning ORM models directly from routes**: convert to Pydantic models via `.model_dump()` or `.dict()` to avoid serialization issues and detached instance errors.

## References

- [repo-evidence.md](references/repo-evidence.md) — source file paths and snippets
- [app-factory-and-lifespan.md](references/app-factory-and-lifespan.md) — app factory and lifespan patterns
- [custom-route-and-middleware.md](references/custom-route-and-middleware.md) — custom route handler, middleware stack, ResponseData
- [dependency-injection.md](references/dependency-injection.md) — ConnectionHandler DI, BaseDao pattern with pagination, auth dependencies
- [model-and-serialization-patterns.md](references/model-and-serialization-patterns.md) — Pydantic models, validation, ORM serialization, settings
