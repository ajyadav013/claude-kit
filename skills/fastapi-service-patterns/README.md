# fastapi-service-patterns

Encodes FastAPI architectural and operational patterns from production services: app factory, lifespan hooks, custom request routing with structured exception handling, dependency injection for database and auth context, middleware stack (CORS, RBAC, telemetry), and the ResponseData response envelope.

## What this skill covers

- App factory pattern (`get_app()`) and application configuration
- Lifespan context manager for startup/shutdown resource management
- Custom `APIRoute` subclass for request logging, exception handling, and response wrapping
- `ResponseData` envelope for consistent API responses (`success`, `data`, `errors`, `identifier`, `pagination`)
- Dependency injection: `Depends(get_connection_handler)` for lazy DB session and Redis access
- `BaseDao` pattern for standardized CRUD operations, pagination, and soft-delete support
- Pydantic models for request validation and ORM serialization (`model_validate`, `model_dump`)
- Middleware stack: CORS, RBAC (tag-based `skip_rbac`/`public_authenticated`), security headers, telemetry
- Three-tier router hierarchy (top-level `api_router` → versioned routers → feature routers)
- OpenAPI customization (root path injection, conditional headers)
- Row-level security (RLS) and schema-switching patterns for multi-tenancy

## Provenance

Derived from real-world production Python/FastAPI services with modern async patterns, multi-tenancy support, and structured error handling.

## How to apply

1. **Scaffold new service**: copy `app/application.py`, `app/lifetime.py`, `app/routing.py`, `app/connection.py` skeletons from SKILL.md into your project.
2. **Replace on_event hooks**: if migrating from legacy `@app.on_event("startup")`, convert to `@asynccontextmanager async def lifespan(app)`.
3. **Wire custom route**: import `CustomRequestRoute` and pass it to routers via `APIRouter(route_class=CustomRequestRoute)` or set globally.
4. **Add middleware**: configure CORS (with explicit origins), RBAC (if needed), security headers.
5. **Use dependency injection**: inject `ConnectionHandler` via `Depends(get_connection_handler)` into handlers; access `handler.session` or `handler.redis`.
6. **Return ResponseData**: all endpoints return `ResponseData.ok(data=..., message=...)` or `ResponseData.error(errors=..., message=...)`.

## Provenance

- **Codebase-derived**: app factory structure, lifespan pattern, CustomRequestRoute exception handling, ConnectionHandler singleton+lazy session, BaseDao CRUD+pagination pattern, ResponseData schema, RBAC middleware tag logic, x-user-data header parsing, router hierarchy, OpenAPI customization.
- **Internet-confirmed**: none (all patterns are project-specific conventions).
