# App Factory and Lifespan Patterns

Deep pattern inventory for FastAPI application factory and resource lifecycle management.

## App factory pattern

### Structure

The app factory is a function `get_app() -> FastAPI` in `app/application.py` that:

1. **Creates the FastAPI instance** with configuration parameters
2. **Includes routers** (top-level `api_router` that aggregates versioned routers)
3. **Adds middleware** (CORS, RBAC, telemetry, security headers)
4. **Configures OpenAPI** (conditional docs, custom OpenAPI schema)
5. **Returns the configured app** ready for uvicorn

### FastAPI initialization parameters

Common patterns across repos:

```python
app = FastAPI(
    debug=settings.DEBUG,                    # Enable debug mode in dev
    title="ServiceName",                     # OpenAPI title
    description="Service description",       # Optional OpenAPI description
    default_response_class=ORJSONResponse,  # Use orjson for faster JSON serialization
    lifespan=lifespan,                       # Lifespan context manager for startup/shutdown
    redirect_slashes=False,                  # Don't auto-redirect trailing slashes
    docs_url="/docs" if settings.DEBUG else None,  # Disable docs in prod
    redoc_url="/redoc" if settings.DEBUG else None,
    openapi_url="/swagger.json",             # Custom OpenAPI URL
    root_path=f"/service/{SERVER_TYPE}/...", # Root path for reverse proxy
)
```

### Middleware stack order

Middleware is executed in reverse order of addition (last added = first to process request). Common stack:

1. **Security headers middleware** (innermost, applied to all responses)
2. **RBAC/auth middleware** (gate access before route handler)
3. **Telemetry/tracing middleware** (OpenTelemetry, Prometheus)
4. **CORS middleware** (outermost, handles preflight)

Example:

```python
app.include_router(api_router)
instrument_app(app)  # OpenTelemetry
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-Skip-Cache"],
)

@app.middleware("http")
async def security_headers(request: Request, call_next: object) -> Response:
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Content-Security-Policy"] = "default-src 'self'; ..."
    if settings.COOKIE_SECURE:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response
```

### CORS configuration

**Anti-pattern**: `allow_origins=["*"]` (overly permissive, allows any origin).

**Recommended**: explicit domain list from settings:

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,  # e.g., ["https://app.example.com", "https://admin.example.com"]
    allow_credentials=True,               # Allow cookies/auth headers
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "x-user-data"],  # App-specific headers
)
```

## Lifespan context manager

### Modern pattern (preferred)

Use `@asynccontextmanager` to wrap startup and shutdown logic:

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: initialize resources
    setup_logging()
    ConnectionManager()  # Init DB/Redis pools
    # Could also init: Kafka producer, Temporal client, BigQueryUtils, etc.
    yield
    # Shutdown: close resources
    from app.telemetry import shutdown_telemetry
    shutdown_telemetry()
    await ConnectionManager().close_connections()
```

Pass to FastAPI: `FastAPI(lifespan=lifespan)`.

### Legacy pattern (deprecated)

Older services use `@app.on_event("startup")` and `@app.on_event("shutdown")`:

```python
@app.on_event("startup")
async def _startup() -> None:
    await run_on_startup()

@app.on_event("shutdown")
async def _shutdown() -> None:
    await run_on_exit()
```

**Why deprecated**: FastAPI recommends lifespan for better resource management and testing. The `on_event` hooks don't compose well and are harder to test in isolation.

### What to initialize in lifespan

Common resources initialized on startup:

1. **ConnectionManager** (singleton DB engine + Redis client)
2. **Telemetry** (OpenTelemetry, Sentry, Prometheus)
3. **Kafka producer** (if using Kafka for events)
4. **Temporal client** (if using Temporal for workflows)
5. **BigQuery client** (if using BigQuery for analytics)
6. **Structured logging** (configure logging format/handlers)

Common cleanup on shutdown:

1. **Close DB engine** (`await engine.dispose()`)
2. **Close Redis client** (`await redis.close()`)
3. **Flush telemetry** (`shutdown_telemetry()`)
4. **Close Kafka producer** (`await producer.stop()`)

### Example: lifespan with integrated startup/shutdown

```python
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Startup
    setup_logging()
    ConnectionManager()  # Initializes singleton with DB engine + Redis
    yield
    # Shutdown
    from app.telemetry import shutdown_telemetry
    shutdown_telemetry()
    await ConnectionManager().close_connections()
```

### Example: lifespan with external startup/shutdown

```python
from core.system_lifecycle import run_on_startup, run_on_exit

@asynccontextmanager
async def lifespan(app: FastAPI):
    await run_on_startup()  # Centralizes all startup logic
    yield
    await run_on_exit()     # Centralizes all shutdown logic
```

## Router inclusion

### Three-tier hierarchy

1. **Top-level `api_router`** in `app/router.py`: aggregates health endpoints and versioned routers
2. **Versioned router** (e.g., `<domain>/v1/router.py`): aggregates per-feature routers
3. **Feature routers**: define individual endpoints

Example:

```python
# app/router.py
from app.identity.v1.router import identity_v1_router
from app.access.v1.router import access_v1_router
from app.control.v1.router import control_v1_router

api_router = APIRouter()
api_router.add_api_route("/_healthz", healthz, methods=["GET"], tags=["health"])
api_router.add_api_route("/_readyz", readyz, methods=["GET"], tags=["health"])
api_router.include_router(identity_v1_router, prefix="/v1")
api_router.include_router(access_v1_router, prefix="/v1")
api_router.include_router(control_v1_router, prefix="/v1")

# app/identity/v1/router.py
from app.identity.v1.auth.router import auth_router
from app.identity.v1.user.router import user_router
# ...

identity_v1_router = APIRouter()
identity_v1_router.include_router(auth_router)
identity_v1_router.include_router(user_router)
# ...
```

### Conditional router inclusion

```python
api_router_prefix = APIRouter(prefix="/v1.0")

if loaded_config.SERVER_TYPE == "public":
    api_router_prefix.include_router(shipment_router, tags=["Shipment v1.0"])
    api_router_prefix.include_router(eway_bill_router, tags=["EWay Bill v1.0"])

if loaded_config.SERVER_TYPE == "internal":
    api_router_prefix.include_router(shipment_router, tags=["Shipment v1.0"])
    api_router_prefix.include_router(partner_config_router, tags=["Partner Config v1.0"])

elif loaded_config.SERVER_TYPE == "platform":
    api_router_prefix.include_router(partner_config_router, tags=["Partner Config v1.0"])

api_router.include_router(api_router_prefix)
```

**Use case**: single codebase serving multiple API surfaces (public vs internal vs webhook) differentiated by env var.

## Custom OpenAPI schema

### root_path injection and conditional headers

```python
from fastapi.openapi.utils import get_openapi

def custom_openapi(app: FastAPI):
    openapi_schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )

    # Add URL prefix to paths
    url_prefix = f"/service/{loaded_config.SERVER_TYPE}/{product_path}"
    paths = {}
    for path, path_item in openapi_schema["paths"].items():
        paths[f"{url_prefix}{path}"] = path_item

    # Conditionally add/remove headers per environment
    serviceability_path = f"{url_prefix}/v1.0/shipment/serviceability"
    if serviceability_path in paths and "post" in paths[serviceability_path]:
        if loaded_config.ENV != "local":
            # Remove aggregator-account-id header in non-local envs
            existing_params = paths[serviceability_path]["post"]["parameters"]
            paths[serviceability_path]["post"]["parameters"] = [
                param for param in existing_params if param.get("name") != "aggregator-account-id"
            ]
            # Add account-token header
            paths[serviceability_path]["post"]["parameters"].append({
                "name": "account-token",
                "in": "header",
                "description": "Account token for authentication",
                "required": False,
                "schema": {"type": "string"}
            })

    openapi_schema["paths"] = paths
    return openapi_schema

myservice_app.openapi_schema = custom_openapi(app=myservice_app)
```

**Use cases**:
- Inject root_path for services behind a reverse proxy
- Add/remove auth headers based on environment
- Modify endpoint visibility per deployment

## Summary checklist

When setting up a new FastAPI app:

- [ ] Create `get_app()` factory in `app/application.py`
- [ ] Use `@asynccontextmanager` lifespan in `app/lifetime.py` (not `@app.on_event`)
- [ ] Initialize `ConnectionManager` singleton on startup, close on shutdown
- [ ] Add CORS middleware with explicit `allow_origins` (not `["*"]`)
- [ ] Add security headers middleware (`X-Content-Type-Options`, `X-Frame-Options`, CSP, HSTS)
- [ ] Include top-level `api_router` with health endpoints
- [ ] Set `default_response_class=ORJSONResponse` for faster JSON
- [ ] Disable docs in production (`docs_url=None if not DEBUG`)
- [ ] Use `redirect_slashes=False` to avoid auto-redirects (optional)
- [ ] If behind reverse proxy, set `root_path` and optionally customize OpenAPI
