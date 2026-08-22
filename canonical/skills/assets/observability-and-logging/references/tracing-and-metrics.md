# Tracing and Metrics

OpenTelemetry distributed tracing and Prometheus RED metrics patterns.

## OpenTelemetry SDK Initialization (reference service pattern)

Example from a production service (`app/telemetry.py`):

```python
import structlog
from config.settings import settings

logger = structlog.get_logger(__name__)

def initialize_telemetry() -> None:
    """Set up the OpenTelemetry SDK with OTLP gRPC exporter."""
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

        logger.info(
            "telemetry.initialized",
            service=settings.OTEL_SERVICE_NAME,
            endpoint=settings.OTEL_EXPORTER_ENDPOINT,
        )
    except ImportError:
        logger.warning("telemetry.import_error", msg="OpenTelemetry packages not installed")
    except Exception as exc:
        logger.warning("telemetry.init_failed", error=str(exc))
```

**File**: `app/telemetry.py`

### Auto-Instrumentation

```python
def instrument_app(app: object) -> None:
    """Apply FastAPI auto-instrumentation to the app."""
    if not settings.OTEL_ENABLED:
        return

    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        FastAPIInstrumentor.instrument_app(app)
        logger.info("telemetry.fastapi_instrumented")
    except ImportError:
        logger.warning("telemetry.fastapi_import_error")

def instrument_db() -> None:
    """Apply asyncpg auto-instrumentation for database tracing."""
    if not settings.OTEL_ENABLED:
        return

    try:
        from opentelemetry.instrumentation.asyncpg import AsyncPGInstrumentor
        AsyncPGInstrumentor().instrument()
        logger.info("telemetry.asyncpg_instrumented")
    except ImportError:
        logger.warning("telemetry.asyncpg_import_error")

def instrument_redis() -> None:
    """Apply Redis auto-instrumentation for cache tracing."""
    if not settings.OTEL_ENABLED:
        return

    try:
        from opentelemetry.instrumentation.redis import RedisInstrumentor
        RedisInstrumentor().instrument()
        logger.info("telemetry.redis_instrumented")
    except ImportError:
        logger.warning("telemetry.redis_import_error")
```

### Shutdown Hook

```python
def shutdown_telemetry() -> None:
    """Flush and shut down the tracer provider."""
    if not settings.OTEL_ENABLED:
        return

    try:
        from opentelemetry import trace
        provider = trace.get_tracer_provider()
        if hasattr(provider, "shutdown"):
            provider.shutdown()
            logger.info("telemetry.shutdown")
    except Exception as exc:
        logger.warning("telemetry.shutdown_failed", error=str(exc))
```

## Trace ID Propagation (production service pattern)

Example from a production service (`src/middleware/logging.py`):

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

**File**: `src/middleware/logging.py`

### Usage in Application

```python
from src.application import get_app
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from src.middleware.logging import TraceIDMiddleware

app = get_app()
app.add_middleware(TraceIDMiddleware)  # Add after OTEL instrumentation
FastAPIInstrumentor.instrument_app(app)
```

**File**: `src/application.py`

## Prometheus Metrics (production service pattern)

### Custom Registry and Histogram Buckets

Example from a production service (`src/metrics/constant.py`):

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

# ... (WORKER_TASK_EXECUTED, CRON_JOB_EXECUTED, TEMPORAL_WORKFLOW_EXECUTED)

def get_metrics_registry() -> CollectorRegistry:
    return _metrics_registry
```

**File**: `src/metrics/constant.py`

### PrometheusMiddleware

Example from a production service (`src/middleware/prometheus.py`):

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

        # Skip excluded paths
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
        """Normalize path to reduce cardinality."""
        # Replace UUIDs with {uuid}
        path = re.sub(UUID_PATTERN, "{uuid}", path, flags=re.IGNORECASE)
        # Replace numeric IDs with {id}
        path = re.sub(NUMERIC_ID_PATTERN, "/{id}", path)
        # Collapse multiple slashes
        path = re.sub(r"/+", "/", path)
        # Remove trailing slash except for root
        if path != "/" and path.endswith("/"):
            path = path[:-1]
        return path
```

**File**: `src/middleware/prometheus.py`

### Recording Helper

Example from a production service (`src/metrics/helper.py`):

```python
def record_http_request_received(method: str, path: str, status_code: int, duration: float) -> None:
    HTTP_REQUEST_RECEIVED.labels(
        method=method, path=path, status_code=str(status_code), service_name=METRIC_SERVICE_IDENTIFIER
    ).observe(duration)
```

**File**: `src/metrics/helper.py`

### Metrics File Exporter

Example from a production service (`src/metrics/exporter.py`):

```python
import asyncio
import os
from pathlib import Path
from prometheus_client import generate_latest
from src.metrics.constant import get_metrics_registry

METRICS_EXPORT_INTERVAL = int(os.environ.get("METRICS_EXPORT_INTERVAL", "30"))  # seconds
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
        if file_size > 1024 * 1024:  # 1MB
            logger.warning(f"Large metrics file: {file_size} bytes")

        with open(LOG_FILE, "w") as f:  # Overwrite, not append
            f.write(metrics_data)
    except Exception as e:
        logger.error(f"Error exporting metrics: {e}")

async def start_metrics_exporter():
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

async def stop_metrics_exporter_task():
    global _metrics_exporter_task
    if _metrics_exporter_task:
        _metrics_exporter_task.cancel()
        try:
            await _metrics_exporter_task
        except asyncio.CancelledError:
            pass
        _metrics_exporter_task = None
```

**File**: `src/metrics/exporter.py`

## Consumer Tracing Decorator (production service pattern)

Example from a production service (`src/config/otel_config.py`):

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
                return await func(*args, **kwargs)

        return wrapper
    return decorator
```

**File**: `src/config/otel_config.py`

### Usage

```python
@trace_consumer_operation("process_webhook")
async def process_webhook_event(message: dict):
    # ... consumer logic
```

## Sentry Integration (production service pattern)

Example from a production service (`sentry_config.py`):

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

**File**: `sentry_config.py`

### Initialization in App

```python
import sentry_config

def create_app():
    if os.getenv("SENTRY_DSN"):
        sentry_config.initialize()
    # ...
```

Sentry DSN is read from the environment by the SDK automatically (`SENTRY_DSN` env var).
