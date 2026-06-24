# Example Patterns

Code examples illustrating the observability patterns in this skill. All snippets are adapted from production FastAPI services.

## Structlog Configuration

**File**: `config/logging.py`

```python
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
```

## Centralized Request Logging

**File**: `app/routing.py`

```python
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
                # ... log validation_error, return 400
            except HTTPException as exc:
                # ... log http_exception, return exc.status_code
            except Exception as exc:
                logger.exception("unhandled_exception", path=request.url.path, error=str(exc))
                # ... return 500
```

## OpenTelemetry SDK Initialization

**File**: `app/telemetry.py`

```python
def initialize_telemetry() -> None:
    if not settings.OTEL_ENABLED:
        logger.info("telemetry.disabled")
        return

    try:
        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.sdk.resources import Resource, SERVICE_NAME
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

        resource = Resource.create({SERVICE_NAME: settings.OTEL_SERVICE_NAME})
        provider = TracerProvider(resource=resource)
        exporter = OTLPSpanExporter(endpoint=settings.OTEL_EXPORTER_ENDPOINT)
        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)

        logger.info("telemetry.initialized", service=settings.OTEL_SERVICE_NAME, endpoint=settings.OTEL_EXPORTER_ENDPOINT)
    except ImportError:
        logger.warning("telemetry.import_error", msg="OpenTelemetry packages not installed")
```

**Auto-instrumentation functions** (same file):

```python
def instrument_app(app: object) -> None:
    if not settings.OTEL_ENABLED:
        return
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        FastAPIInstrumentor.instrument_app(app)
        logger.info("telemetry.fastapi_instrumented")
    except ImportError:
        logger.warning("telemetry.fastapi_import_error")

def instrument_db() -> None:
    if not settings.OTEL_ENABLED:
        return
    try:
        from opentelemetry.instrumentation.asyncpg import AsyncPGInstrumentor
        AsyncPGInstrumentor().instrument()
        logger.info("telemetry.asyncpg_instrumented")
    except ImportError:
        logger.warning("telemetry.asyncpg_import_error")

def instrument_redis() -> None:
    if not settings.OTEL_ENABLED:
        return
    try:
        from opentelemetry.instrumentation.redis import RedisInstrumentor
        RedisInstrumentor().instrument()
        logger.info("telemetry.redis_instrumented")
    except ImportError:
        logger.warning("telemetry.redis_import_error")
```

## Trace ID Propagation

**File**: `src/middleware/logging.py`

```python
from opentelemetry.trace import get_current_span

class TraceIDMiddleware:
    """Middleware to add trace ID and span ID to response headers."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            span = get_current_span()
            if span and span.is_recording():
                trace_id = format(span.get_span_context().trace_id, "032x")
                span_id = format(span.get_span_context().span_id, "016x")
                scope["trace_id"] = trace_id
                scope["span_id"] = span_id

        async def send_wrapper(message):
            if message["type"] == "http.response.start" and "trace_id" in scope:
                headers = list(message.get("headers", []))
                headers.append([b"x-trace-id", scope["trace_id"].encode()])
                headers.append([b"x-span-id", scope["span_id"].encode()])
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_wrapper)
```

**Usage in application**:

**File**: `src/application.py`

```python
from fastapi import FastAPI
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from src.middleware.logging import TraceIDMiddleware
from src.middleware.prometheus import PrometheusMiddleware

def get_app() -> FastAPI:
    app = FastAPI(...)
    
    # Add Prometheus middleware for metrics collection
    app.add_middleware(PrometheusMiddleware)
    
    # Add trace ID middleware to expose trace/span IDs in response headers
    app.add_middleware(TraceIDMiddleware)
    
    # ... include routers, startup/shutdown hooks
    
    FastAPIInstrumentor.instrument_app(app)
    return app
```

## Sentry Integration

**File**: `sentry_config.py`

```python
import logging
import sentry_sdk
from sentry_sdk.integrations.logging import LoggingIntegration
from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration

def initialize():
    sentry_sdk.init(
        integrations=[
            LoggingIntegration(event_level=logging.ERROR),
            SqlalchemyIntegration(),
        ],
    )
```

## Prometheus Metrics: Custom Registry and Histograms

**File**: `src/metrics/constant.py`

```python
from prometheus_client import CollectorRegistry, Histogram

_metrics_registry = CollectorRegistry()

CUSTOM_HISTOGRAM_BUCKETS = [0.05, 0.1, 0.2, 0.4, 0.8, 1, 2, 5, 7, 10, float("inf")]

HTTP_REQUEST_RECEIVED = Histogram(
    "app_http_request_received",
    "Duration of HTTP requests received",
    ["method", "path", "status_code", "service_name"],
    buckets=CUSTOM_HISTOGRAM_BUCKETS,
    registry=_metrics_registry,
)

KAFKA_MESSAGE_PROCESSED = Histogram(
    "app_consumer_kafka_message_processed",
    "Duration to process a Kafka message",
    ["topic", "partition", "status", "service_name"],
    buckets=CUSTOM_HISTOGRAM_BUCKETS,
    registry=_metrics_registry,
)

WORKER_TASK_EXECUTED = Histogram(
    "app_worker_worker_task_executed",
    "Duration to execute a background worker task",
    ["task_name", "status", "service_name"],
    buckets=CUSTOM_HISTOGRAM_BUCKETS,
    registry=_metrics_registry,
)

CRON_JOB_EXECUTED = Histogram(
    "app_cron_cron_job_executed",
    "Duration to execute a cron job",
    ["job_name", "status", "service_name"],
    buckets=CUSTOM_HISTOGRAM_BUCKETS,
    registry=_metrics_registry,
)

TEMPORAL_WORKFLOW_EXECUTED = Histogram(
    "app_worker_temporal_workflow_executed",
    "Duration to execute a temporal workflow or activity",
    ["workflow_name", "status", "service_name"],
    buckets=CUSTOM_HISTOGRAM_BUCKETS,
    registry=_metrics_registry,
)

def get_metrics_registry() -> CollectorRegistry:
    return _metrics_registry
```

## PrometheusMiddleware: Path Normalization

**File**: `src/middleware/prometheus.py`

```python
import re
import time
from starlette.middleware.base import BaseHTTPMiddleware
from src.metrics.helper import record_http_request_received

UUID_PATTERN = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
NUMERIC_ID_PATTERN = r"/\d+(?=/|$)"
EXCLUDED_PATHS = {"/health", "/docs", "/openapi.json", "/_healthz", "/_readyz", "/metrics"}

class PrometheusMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        start_time = time.time()
        method = request.method
        original_path = request.url.path
        path = self._normalize_path(original_path)

        if original_path in EXCLUDED_PATHS or path in EXCLUDED_PATHS:
            return await call_next(request)

        try:
            response = await call_next(request)
            duration = time.time() - start_time
            record_http_request_received(method, path, response.status_code, duration)
            return response
        except Exception:
            duration = time.time() - start_time
            record_http_request_received(method, path, 500, duration)
            raise

    def _normalize_path(self, path: str) -> str:
        path = re.sub(UUID_PATTERN, "{uuid}", path, flags=re.IGNORECASE)
        path = re.sub(NUMERIC_ID_PATTERN, "/{id}", path)
        path = re.sub(r"/+", "/", path)
        if path != "/" and path.endswith("/"):
            path = path[:-1]
        return path
```

## Metrics Helper: Recording

**File**: `src/metrics/helper.py`

```python
from src.metrics.constant import HTTP_REQUEST_RECEIVED, METRIC_SERVICE_IDENTIFIER

def record_http_request_received(method: str, path: str, status_code: int, duration: float) -> None:
    logger.debug(f"record_http_request_received: Recording {method} {path} - {status_code} - {duration:.3f}s")

    HTTP_REQUEST_RECEIVED.labels(
        method=method, path=path, status_code=str(status_code), service_name=METRIC_SERVICE_IDENTIFIER
    ).observe(duration)

    logger.debug(f"record_http_request_received: Successfully recorded metrics for {method} {path}")
```

## Metrics File Exporter

**File**: `src/metrics/exporter.py`

```python
import asyncio
import os
from pathlib import Path
from prometheus_client import generate_latest
from src.metrics.constant import get_metrics_registry

METRICS_EXPORT_INTERVAL = int(os.environ.get("METRICS_EXPORT_INTERVAL", "30"))
METRICS_DIR = os.environ.get("METRICS_DIR", "/var/data/metrics")
POD_NAME = os.environ.get("K8S_POD_NAME", "local-pod")

if POD_NAME == "local-pod" or not os.path.exists(METRICS_DIR):
    METRICS_DIR = "/tmp/metrics"

Path(METRICS_DIR).mkdir(parents=True, exist_ok=True)
LOG_FILE = f"{METRICS_DIR}/{POD_NAME}.prom"

async def export_metrics():
    try:
        metrics_data = generate_latest(registry=get_metrics_registry()).decode("utf-8")
        if not metrics_data.strip():
            logger.warning("No metrics data to export")
            return

        file_size = len(metrics_data)
        if file_size > 1024 * 1024:
            logger.warning(f"Large metrics file: {file_size} bytes")

        with open(LOG_FILE, "w") as f:  # Overwrite
            f.write(metrics_data)

        logger.debug(f"Exported metrics to {LOG_FILE} ({file_size} bytes)")
    except Exception as e:
        logger.error(f"Error exporting metrics: {e}")

async def start_metrics_exporter():
    logger.info("Starting metrics exporter...")
    while True:
        try:
            await export_metrics()
            await asyncio.sleep(METRICS_EXPORT_INTERVAL)
        except asyncio.CancelledError:
            logger.info("Metrics exporter cancelled")
            break
        except Exception as e:
            logger.error(f"Error in metrics exporter loop: {e}")
            await asyncio.sleep(5)

_metrics_exporter_task = None

async def start_metrics_exporter_task():
    global _metrics_exporter_task
    if _metrics_exporter_task is None:
        _metrics_exporter_task = asyncio.create_task(start_metrics_exporter())
        logger.info("Started metrics exporter background task")

async def stop_metrics_exporter_task():
    global _metrics_exporter_task
    if _metrics_exporter_task:
        _metrics_exporter_task.cancel()
        try:
            await _metrics_exporter_task
        except asyncio.CancelledError:
            pass
        _metrics_exporter_task = None
        logger.info("Stopped metrics exporter background task")
```

## Health Endpoints

### Liveness

**File**: `common/health.py`

```python
async def healthz() -> ResponseData:
    """Return a simple liveness probe response."""
    return ResponseData.ok(message="OK")
```

### Readiness

**File**: `common/health.py`

```python
async def readyz(
    connection_handler: ConnectionHandler = Depends(get_connection_handler),
) -> ResponseData | dict[str, object]:
    """Check database and Redis connectivity for readiness probes."""
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
        content=ResponseData.error(message="Service degraded", errors=[checks]).model_dump(),
    )
```

### Router Registration

**File**: `app/router.py`

```python
from fastapi import APIRouter
from common.health import healthz, readyz

api_router = APIRouter()

api_router.add_api_route("/_healthz", healthz, methods=["GET"], tags=["health"])
api_router.add_api_route("/_readyz", readyz, methods=["GET"], tags=["health"])
```

### Alternative Health Endpoints

**File**: `app/router.py` (alternate pattern)

```python
from fastapi.responses import JSONResponse
from fastapi.routing import APIRouter

async def healthz():
    return JSONResponse(status_code=200, content={"success": True})

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
    endpoint=healthz,  # Same handler
    include_in_schema=False,
    tags=["skip_rbac"],
)
```

## Consumer Tracing Decorator

**File**: `src/config/otel_config.py`

```python
from opentelemetry import trace

def trace_consumer_operation(operation_name: str):
    """Decorator to add OpenTelemetry tracing to consumer operations"""

    def decorator(func):
        async def wrapper(*args, **kwargs):
            tracer = trace.get_tracer("consumer")
            message = args[0] if args else {}
            event_type = message.get("payload", {}).get("event_type", "unknown")
            event_id = message.get("payload", {}).get("event_log_id", "unknown")
            request_id = message.get("meta", {}).get("request_details", {}).get("request_id", "")

            with tracer.start_as_current_span(f"consumer.{operation_name}.{event_type}") as span:
                span.set_attribute("consumer.event_id", event_id)
                span.set_attribute("consumer.event_type", event_type)
                span.set_attribute("consumer.operation_name", operation_name)
                span.set_attribute("consumer.request_id", request_id)
                if message.get("payload", {}).get("operation_type"):
                    span.set_attribute("consumer.operation_type", message["payload"]["operation_type"])
                if message.get("payload", {}).get("file_path"):
                    span.set_attribute("consumer.file_path", message["payload"]["file_path"])

                return await func(*args, **kwargs)

        return wrapper
    return decorator
```

## Notes

- All examples are adapted from production FastAPI services.
- No secrets, credentials, or sensitive configuration included.
- Focus on observability primitives: structured logging, distributed tracing, metrics collection, and health checks.
