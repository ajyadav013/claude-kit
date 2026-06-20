# Health and Readiness Endpoints

Kubernetes liveness and readiness probe patterns for FastAPI backends.

## Liveness Probe (reference service pattern)

Example from a production service (`common/health.py`):

```python
from app.utils import ResponseData

async def healthz() -> ResponseData:
    """Return a simple liveness probe response.
    
    Returns:
        ResponseData with success status.
    """
    return ResponseData.ok(message="OK")
```

**File**: `common/health.py`

### Alternative Pattern

Example from another production service (`app/router.py`):

```python
from fastapi.responses import JSONResponse

async def healthz():
    return JSONResponse(status_code=200, content={"success": True})
```

**File**: `app/router.py`

## Readiness Probe (reference service pattern)

Example from a production service (`common/health.py`):

```python
from fastapi import Depends
from sqlalchemy import text
from app.connection import ConnectionHandler, get_connection_handler
from app.utils import ResponseData

async def readyz(
    connection_handler: ConnectionHandler = Depends(get_connection_handler),
) -> ResponseData | dict[str, object]:
    """Check database and Redis connectivity for readiness probes.
    
    Args:
        connection_handler: Request-scoped DB/Redis handler.
    
    Returns:
        200 ResponseData when all checks pass, or a 503 ORJSONResponse
        when any dependency is degraded.
    """
    checks = {}
    try:
        result = await connection_handler.session.execute(text("SELECT 1"))
        result.scalar()
        checks["database"] = "ok"
    except Exception as e:
        checks["database"] = f"error: {str(e)}"

    try:
        pong = await connection_handler.redis.ping()
        checks["redis"] = "ok" if pong else "error: no pong"
    except Exception as e:
        checks["redis"] = f"error: {str(e)}"

    all_ok = all(v == "ok" for v in checks.values())
    if all_ok:
        return ResponseData.ok(data=checks, message="All systems operational")

    from fastapi.responses import ORJSONResponse

    return ORJSONResponse(
        status_code=503,
        content=ResponseData.error(
            message="Service degraded", errors=[checks]
        ).model_dump(),
    )
```

**File**: `common/health.py`

## Router Registration (reference service pattern)

Example from a production service (`app/router.py`):

```python
from fastapi import APIRouter
from common.health import healthz, readyz

api_router = APIRouter()

api_router.add_api_route("/_healthz", healthz, methods=["GET"], tags=["health"])
api_router.add_api_route("/_readyz", readyz, methods=["GET"], tags=["health"])
```

**File**: `app/router.py`

## Alternative Router Registration

Example from another production service (`app/router.py`):

```python
from fastapi.routing import APIRouter

api_router_healthz = APIRouter()

api_router_healthz.add_api_route(
    "/_healthz",
    methods=["GET"],
    endpoint=healthz,
    include_in_schema=False,
    tags=["skip_rbac"],
)
api_router_healthz.add_api_route(
    "/_readyz",
    methods=["GET"],
    endpoint=healthz,  # Same endpoint, no DB checks
    include_in_schema=False,
    tags=["skip_rbac"],
)

api_router.include_router(api_router_healthz, tags=["Healthz"])
```

**File**: `app/router.py`

**Note**: This pattern uses the same `healthz` handler for both liveness and readiness (no dependency checks). This is simpler but less robust than the reference pattern above.

## Kubernetes Probe Configuration

### Liveness Probe

Checks if the container is alive. Should fail only if the app is deadlocked or crashed.

```yaml
livenessProbe:
  httpGet:
    path: /_healthz
    port: 8000
  initialDelaySeconds: 10
  periodSeconds: 10
  timeoutSeconds: 3
  failureThreshold: 3
```

### Readiness Probe

Checks if the container is ready to accept traffic. Should fail if dependencies (DB, Redis) are unavailable.

```yaml
readinessProbe:
  httpGet:
    path: /_readyz
    port: 8000
  initialDelaySeconds: 5
  periodSeconds: 5
  timeoutSeconds: 3
  failureThreshold: 2
```

## Design Principles

### Liveness Probe

- **Unconditional 200**: Should always succeed unless the app is fundamentally broken (e.g., HTTP server crashed).
- **No dependency checks**: Do NOT check DB/Redis/external APIs; those belong in readiness.
- **Minimal allocation**: Should complete in <100ms; avoid heavy queries or I/O.
- **Purpose**: Kubernetes restarts the pod if liveness fails repeatedly.

### Readiness Probe

- **Check local dependencies**: DB, Redis, in-memory caches — anything the app needs to serve requests.
- **Do NOT check external APIs**: Readiness probes should only check dependencies within your control. External API health belongs in separate synthetic monitors.
- **Fast checks**: Use lightweight queries (`SELECT 1`, `redis.ping()`), not full health diagnostics.
- **503 on failure**: Return HTTP 503 so Kubernetes removes the pod from the load balancer but does NOT restart it.
- **Purpose**: Kubernetes stops routing traffic to the pod until readiness passes again.

## Authentication and RBAC

Always skip authentication on health endpoints:

- Option 1: `tags=["health"]` and configure middleware to skip auth for this tag
- Option 2: `tags=["skip_rbac"]` and configure RBAC middleware to bypass on this tag

## Example: Minimal Readiness Probe

For services that only need DB checks (no Redis):

```python
async def readyz(session: AsyncSession = Depends(get_session)):
    try:
        await session.execute(text("SELECT 1"))
        return {"status": "ok"}
    except Exception as e:
        return JSONResponse(status_code=503, content={"status": "error", "detail": str(e)})
```

## Example: Full Readiness with Multiple Services

For services with DB, Redis, and message queue:

```python
async def readyz(
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
    kafka_producer: AIOKafkaProducer = Depends(get_kafka_producer),
):
    checks = {}

    # DB check
    try:
        await db.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as e:
        checks["database"] = f"error: {str(e)}"

    # Redis check
    try:
        await redis.ping()
        checks["redis"] = "ok"
    except Exception as e:
        checks["redis"] = f"error: {str(e)}"

    # Kafka check
    try:
        if kafka_producer and kafka_producer._sender:
            checks["kafka"] = "ok"
        else:
            checks["kafka"] = "error: producer not initialized"
    except Exception as e:
        checks["kafka"] = f"error: {str(e)}"

    if all(v == "ok" for v in checks.values()):
        return {"status": "healthy", "checks": checks}
    else:
        return JSONResponse(
            status_code=503,
            content={"status": "degraded", "checks": checks}
        )
```
