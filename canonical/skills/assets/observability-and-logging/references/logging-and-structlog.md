# Logging and Structlog

How to configure structured logging with `structlog` for FastAPI backends.

## Structlog Configuration (reference service pattern)

Example setup from a production service (`config/logging.py`):

```python
import logging
import structlog
from config.settings import settings

def setup_logging() -> None:
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    log_level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)

    formatter = structlog.stdlib.ProcessorFormatter(
        processor=structlog.dev.ConsoleRenderer() if settings.DEBUG else structlog.processors.JSONRenderer(),
    )

    handler = logging.StreamHandler()
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(log_level)

    for name in ("uvicorn", "uvicorn.access", "sqlalchemy.engine"):
        logging.getLogger(name).handlers.clear()
        logging.getLogger(name).propagate = True

def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)
```

**File**: `config/logging.py`

### Processor Pipeline

1. **`merge_contextvars`**: Merge context variables (set via `structlog.contextvars.bind_contextvars(...)`) into log entries
2. **`filter_by_level`**: Filter logs by configured level
3. **`add_logger_name`**: Add logger name to output
4. **`add_log_level`**: Add log level to output
5. **`TimeStamper(fmt="iso")`**: Add ISO 8601 timestamp
6. **`StackInfoRenderer()`**: Render stack info when `stack_info=True`
7. **`format_exc_info`**: Format exception tracebacks
8. **`UnicodeDecoder()`**: Decode bytes to unicode
9. **`ProcessorFormatter.wrap_for_formatter`**: Bridge to stdlib formatter

### Renderer Selection

- **Development** (`settings.DEBUG=true`): `structlog.dev.ConsoleRenderer()` — colorized, human-readable
- **Production** (`settings.DEBUG=false`): `structlog.processors.JSONRenderer()` — JSON lines for machine parsing

### Stdlib Logger Propagation

Clear handlers on:
- `uvicorn` — Uvicorn server logs
- `uvicorn.access` — HTTP access logs
- `sqlalchemy.engine` — SQLAlchemy query logs

Set `propagate = True` so they flow through the structlog pipeline and get the same JSON/console formatting.

### Log Level from Settings

Read `LOG_LEVEL` from settings (default `INFO`), convert to stdlib constant:

```python
log_level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)
```

## Centralized Request/Exception Logging (reference service pattern)

Example `CustomRequestRoute` pattern from a production service (`app/routing.py`):

```python
import time
from typing import Callable
from fastapi import Request, Response
from fastapi.exceptions import HTTPException, RequestValidationError
from fastapi.routing import APIRoute
from pydantic import ValidationError

logger = get_logger(__name__)

class CustomRequestRoute(APIRoute):
    def get_route_handler(self) -> Callable:
        original_route_handler = super().get_route_handler()

        async def custom_route_handler(request: Request) -> Response:
            start_time = time.perf_counter()
            try:
                response: Response = await original_route_handler(request)
                duration = time.perf_counter() - start_time
                logger.info(
                    "request_handled",
                    method=request.method,
                    path=request.url.path,
                    status_code=response.status_code,
                    duration=round(duration, 4),
                )
                return response
            except (RequestValidationError, ValidationError) as exc:
                raw_errors = [
                    {
                        "field": e["loc"][-1] if e.get("loc") else "unknown",
                        "msg": e["msg"],
                    }
                    for e in exc.errors()
                ]
                logger.warning(
                    "validation_error", path=request.url.path, errors=raw_errors
                )
                errors = [f"{e['field']}: {e['msg']}" for e in raw_errors]
                return ORJSONResponse(
                    content=ResponseData.error(errors=errors, message="Validation error").model_dump(),
                    status_code=HTTP_400_BAD_REQUEST,
                )
            except HTTPException as exc:
                logger.warning(
                    "http_exception",
                    path=request.url.path,
                    status=exc.status_code,
                    detail=exc.detail,
                )
                return ORJSONResponse(
                    content=ResponseData.error(errors=[exc.detail], message=exc.detail).model_dump(),
                    status_code=exc.status_code,
                )
            except Exception as exc:
                logger.exception(
                    "unhandled_exception", path=request.url.path, error=str(exc)
                )
                return ORJSONResponse(
                    content=ResponseData.error(errors=[str(exc)], message="Internal server error").model_dump(),
                    status_code=HTTP_500_INTERNAL_SERVER_ERROR,
                )

        return custom_route_handler
```

**File**: `app/routing.py`

### Usage

Set on routers that need centralized logging:

```python
from app.routing import CustomRequestRoute

router = APIRouter(route_class=CustomRequestRoute)
```

### What It Logs

- **Successful requests**: `request_handled` with method, path, status, duration
- **Validation errors**: `validation_error` with normalized field/msg errors
- **HTTP exceptions**: `http_exception` with status and detail
- **Unhandled exceptions**: `unhandled_exception` with full traceback (via `logger.exception()`)

### Response Wrapping

All error responses use `ResponseData.error(errors=[...], message="...")` for consistent error shape across the API.

## Usage Example

```python
# In app startup (main.py or application.py)
from config.logging import setup_logging

def create_app():
    setup_logging()
    app = FastAPI(...)
    return app

# In request handlers
from config.logging import get_logger

logger = get_logger(__name__)

@router.get("/items/{item_id}")
async def get_item(item_id: int):
    logger.info("item.fetch", item_id=item_id)
    # ...
    logger.info("item.fetched", item_id=item_id, name=item.name)
    return item
```

## Context Variables

Bind request-scoped data to all logs in the request lifecycle:

```python
from structlog.contextvars import bind_contextvars, clear_contextvars

async def log_middleware(request: Request, call_next):
    bind_contextvars(request_id=request.headers.get("X-Request-ID", str(uuid.uuid4())))
    try:
        response = await call_next(request)
        return response
    finally:
        clear_contextvars()
```

All logs within the request will include `request_id` automatically.
