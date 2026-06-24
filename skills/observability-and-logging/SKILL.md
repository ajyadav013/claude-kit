---
name: observability-and-logging
description: Structured logging with structlog, PII/secret redaction processors, OpenTelemetry distributed tracing (OTLP export + FastAPI/asyncpg/Redis/Kafka instrumentation), Sentry error tracking, Prometheus RED metrics (inbound/outbound HTTP + middleware + file exporter), multi-mode service instrumentation (consumers/workers/cron), and liveness/readiness health probes across FastAPI backends. Use when adding observability to new services, instrumenting request/response pipelines, tracking external API calls, redacting PII and secrets from structured logs, implementing audit-log field allowlists, implementing health checks for Kubernetes deployments, setting up metrics for non-FastAPI processes (Kafka consumers, background workers, cron jobs), or configuring distributed tracing and metrics collection for production FastAPI applications.
---

# Observability and Logging

Production observability patterns for FastAPI backends: structured logging, distributed tracing, error tracking, metrics, and health endpoints.

## When to use

- Setting up logging infrastructure for a new FastAPI service
- Implementing distributed tracing across microservices with OpenTelemetry
- Adding Prometheus metrics for RED (Rate, Errors, Duration) monitoring
- Configuring Sentry for error aggregation and alerting
- Implementing Kubernetes liveness/readiness probes
- Exposing trace IDs in response headers for request correlation
- Building centralized request/exception logging middleware
- Exporting metrics to file-based collectors (Prometheus node exporter pattern)
- Tracking outbound HTTP requests to external APIs with metrics
- Instrumenting multi-mode services (consumers, workers, cron, Temporal) with separate metrics endpoints

## Core conventions

### Structured Logging (structlog)

**Processor pipeline**: Configure `structlog.configure()` with processors: `merge_contextvars` → `filter_by_level` → `add_logger_name` → `add_log_level` → `TimeStamper(fmt="iso")` → `StackInfoRenderer()` → `format_exc_info` → `UnicodeDecoder()` → `ProcessorFormatter.wrap_for_formatter`. _(reference service pattern)_

**JSON vs. console rendering**: Use `structlog.dev.ConsoleRenderer()` when `DEBUG=true`, otherwise `structlog.processors.JSONRenderer()` for machine-parseable logs in production. _(reference service pattern)_

**Propagate to stdlib loggers**: Clear handlers on `uvicorn`, `uvicorn.access`, `sqlalchemy.engine` and set `propagate = True` so they flow through the structlog pipeline. _(reference service pattern)_

**Log level from settings**: Read `settings.LOG_LEVEL` (default `INFO`), convert to stdlib constant with `getattr(logging, level.upper(), logging.INFO)`. _(reference service pattern)_

### PII and Secret Redaction (structlog processor)

Structured logging makes it *easy* to log a whole request body, user object, or DB URL — which is
exactly how PII and secrets leak into log aggregators. Redact in the pipeline, not at each call site, so
it can't be forgotten.

**Redaction processor in the pipeline**: Add a `redact_processor` to `structlog.configure(processors=[...])`
**before** the renderer. It walks the event dict and (a) masks values whose **key** is sensitive and
(b) pattern-masks PII inside string values. Because it runs in the pipeline, every log call is covered.
_(reference service pattern)_

**Sensitive-key denylist**: Mask any key matching `password`, `passwd`, `secret`, `token`,
`authorization`, `api_key`/`apikey`, `set-cookie`/`cookie`, `private_key`, `client_secret`,
`x-user-data`, `ssn`, `card`/`card_number`, `cvv`. Replace the value with `"***"` (don't drop the key —
keep the shape for debugging). _(reference service pattern)_

**Pattern masking inside strings**: Mask email local parts, long digit runs (cards/phones), and bearer
tokens in free-text message values via regex (e.g. email → `j***@example.com`, 13–19 digit runs →
`****`). Apply to the rendered `event` message and any string field. _(reference service pattern)_

**Mask DB URLs / connection strings**: Never log a DSN with credentials; rewrite
`postgresql://user:pass@host/db` → `postgresql://user:***@host/db` before logging connector config or
errors. _(reference service pattern)_

**Audit-event field allowlist**: For audit/access logs, **allowlist** the fields you emit
(`user_id`, `user_role`, `tenant_id`, `action`, `resource_id`, `result`) rather than dumping the user
object. Prefer opaque identifiers over `user_email` / `user_name`; if you must include a name/email,
mask it. _(reference service pattern)_

**Truncate large payloads**: Cap logged request/response bodies (e.g. 2 KB) — full bodies both leak data
and blow up log volume. _(reference service pattern)_

### Centralized Request/Exception Logging

**CustomRequestRoute pattern**: Subclass `APIRoute`, override `get_route_handler()`, wrap the original handler to log every request with `method`, `path`, `status_code`, `duration` (via `time.perf_counter()`), and catch validation/HTTP/unhandled exceptions. _(reference service pattern)_

**Validation error normalization**: Extract `[{"field": e["loc"][-1], "msg": e["msg"]}]` from Pydantic errors, log as `validation_error`, return 400 with structured `ResponseData.error()`. _(reference service pattern)_

**Unhandled exception logging**: Log as `unhandled_exception` with `logger.exception(...)` to include traceback, return 500 with masked error message. _(reference service pattern)_

**Usage**: Set `router = APIRouter(route_class=CustomRequestRoute)` on routers that need centralized logging. _(reference service pattern)_

### OpenTelemetry Distributed Tracing

**Initialize SDK first**: Call `initialize_telemetry()` in the app startup hook; create `TracerProvider(resource=Resource({SERVICE_NAME: ...}))`, add `BatchSpanProcessor(OTLPSpanExporter(endpoint=...))`, set global provider with `trace.set_tracer_provider()`. _(reference service pattern)_

**Auto-instrumentation**: After SDK init, call `FastAPIInstrumentor.instrument_app(app)`, `AsyncPGInstrumentor().instrument()`, `RedisInstrumentor().instrument()`. Kafka consumers: `KafkaInstrumentor().instrument()`. _(production services pattern)_

**Graceful degradation**: Wrap all OTEL imports in `try`/`except ImportError` and log warnings when packages are missing; app must still start if OTEL libraries are absent. _(reference service pattern)_

**Shutdown hook**: On app shutdown, call `trace.get_tracer_provider().shutdown()` to flush pending spans. _(reference service pattern)_

**OTEL_ENABLED master switch**: Check `settings.OTEL_ENABLED` before any OTEL calls; no-op if disabled. _(reference service pattern)_

### Trace ID Propagation

**TraceIDMiddleware**: ASGI middleware that extracts `trace_id` and `span_id` from the current span (via `get_current_span().get_span_context()`), formats them as 32-char hex (trace) and 16-char hex (span), and injects `X-Trace-ID` / `X-Span-ID` headers into the response. _(production service pattern)_

**Usage**: Add to app with `app.add_middleware(TraceIDMiddleware)` after OTEL instrumentation so spans are already active. _(production service pattern)_

**Request ID from Kafka messages**: For consumers, extract `request_id` from `message.get("meta", {}).get("request_details", {}).get("request_id", "")` and set as a span attribute. _(production service pattern)_

### Sentry Error Tracking

**Initialization**: Call `sentry_sdk.init(integrations=[LoggingIntegration(event_level=logging.ERROR), SqlalchemyIntegration()])` in app startup. _(production service pattern)_

**DSN from environment**: Read Sentry DSN from `SENTRY_DSN` env var (or settings); only init if present. _(production service pattern)_

**Integration list**: Include `LoggingIntegration` (sends ERROR+ logs as breadcrumbs), `SqlalchemyIntegration()` (DB query tracking), `FastApiIntegration()` if available. _(production service pattern)_

### Prometheus RED Metrics

**Custom registry**: Create `_metrics_registry = CollectorRegistry()` and register all metrics to it (not the default registry) for isolation. _(production service pattern)_

**Histogram buckets**: Define `CUSTOM_HISTOGRAM_BUCKETS = [0.05, 0.1, 0.2, 0.4, 0.8, 1, 2, 5, 7, 10, float("inf")]` optimized for API latency. _(production service pattern)_

**HTTP request received metric**: `Histogram("app_http_request_received", "Duration of HTTP requests received", ["method", "path", "status_code", "service_name"], buckets=..., registry=_metrics_registry)`. _(production service pattern)_

**Path normalization to reduce cardinality**: Replace UUIDs with `{uuid}` (regex `[0-9a-f]{8}-...`), numeric IDs with `{id}` (`/\d+`), collapse consecutive slashes, strip trailing slashes. _(production service pattern)_

**PrometheusMiddleware**: ASGI middleware that wraps `call_next`, measures duration, calls `record_http_request_received(method, path, status_code, duration)` which invokes `HTTP_REQUEST_RECEIVED.labels(...).observe(duration)`. _(production service pattern)_

**Excluded paths**: Skip metrics for `{"/health", "/_healthz", "/_readyz", "/metrics", "/docs", "/openapi.json"}` to avoid noise. _(production service pattern)_

**Error tracking**: If `call_next` raises, record status 500 before re-raising. _(production service pattern)_

### Metrics Exporter (File-Based)

**Background task pattern**: Start an async task on app startup with `asyncio.create_task(start_metrics_exporter())` and cancel on shutdown. _(production service pattern)_

**Periodic file write**: Every `METRICS_EXPORT_INTERVAL` seconds (default 30), call `generate_latest(registry=get_metrics_registry())`, write to `/var/data/metrics/{POD_NAME}.prom` (or `/tmp/metrics/{POD_NAME}.prom` for local dev). _(production service pattern)_

**Overwrite not append**: Open file in `w` mode each time to avoid unbounded growth. _(production service pattern)_

**File size warning**: Log warning if metrics file exceeds 1MB. _(production service pattern)_

**Why file export**: Allows Prometheus to scrape metrics via node exporter textfile collector pattern; decouples scrape from app HTTP endpoint. _(production service pattern)_

### Non-HTTP Metrics

**Kafka consumer**: `KAFKA_MESSAGE_PROCESSED = Histogram("app_consumer_kafka_message_processed", ..., ["topic", "partition", "status", "service_name"])`. _(production service pattern)_

**Background workers**: `WORKER_TASK_EXECUTED = Histogram("app_worker_worker_task_executed", ..., ["task_name", "status", "service_name"])`. _(production service pattern)_

**Cron jobs**: `CRON_JOB_EXECUTED = Histogram("app_cron_cron_job_executed", ..., ["job_name", "status", "service_name"])`. _(production service pattern)_

**Temporal workflows**: `TEMPORAL_WORKFLOW_EXECUTED = Histogram("app_worker_temporal_workflow_executed", ..., ["workflow_name", "status", "service_name"])`. _(production service pattern)_

**Recording pattern**: Call helper `record_<metric_type>(name, status, duration)` which does `.labels(...).observe(duration)`. _(production service pattern)_

### Outbound HTTP Metrics

**HTTP_REQUEST_SENT metric**: `Histogram("app_http_request_sent", "Duration of HTTP requests sent to external services", ["method", "path", "status_code", "service_name"], buckets=..., registry=_metrics_registry)`. _(production service pattern)_

**Decorator pattern**: Use `@prometheus_http_outbound(method_key="method", url_key="raw_url")` on async HTTP client methods; extracts method/URL from `data` dict, measures duration, records metric with status from returned dict's `status_code` or `status` field. _(production service pattern)_

**Path normalization from URL**: Extract path component via `urlparse(url).path`, collapse slashes, strip trailing slash (except root), ignore query params and hostname to reduce cardinality. _(production service pattern)_

### Multi-Mode Service Instrumentation

**Service name per mode**: Build service identifier as `f"{SERVICE_NAME}-{DEPLOYMENT_NAME}-{DEPLOYMENT_TYPE}"` from env vars; each deployment mode (server, consumer, worker, cron, temporal_worker) gets a distinct label. _(production service pattern)_

**Metrics HTTP server for non-FastAPI modes**: Call `start_http_server(port, registry=get_metrics_registry())` to expose `/metrics` endpoint on dedicated ports (8001 for consumer, 8002 for worker, 8003 for cron, 8004 for temporal_worker). FastAPI mode (port 8000) uses PrometheusMiddleware instead. _(production service pattern)_

**Execute mode wrapper**: Wrap service entrypoints with `execute_mode(mode_main_func)` to auto-start/stop the metrics exporter task for clean lifecycle management. _(production service pattern)_

### Health and Readiness Endpoints

**Liveness probe (`/_healthz`)**: Unconditional 200 response with `{"success": True}` or `ResponseData.ok(message="OK")`. No dependency checks. _(reference service pattern)_

**Readiness probe (`/_readyz`)**: Check DB with `session.execute(text("SELECT 1")).scalar()` and Redis with `redis.ping()`; return 200 if all pass, 503 with `{"database": "error: ...", "redis": "ok"}` if any fail. _(reference service pattern)_

**Skip auth and RBAC**: Tag health endpoints with `tags=["health"]` or `tags=["skip_rbac"]` so they bypass authentication middleware. _(reference service pattern)_

**Minimal allocation**: Keep probes lightweight; avoid heavy queries or external API calls. _(reference service pattern)_

## Skeleton / example

```python
# config/logging.py (reference service pattern)
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

    # Propagate uvicorn/sqlalchemy logs through structlog
    for name in ("uvicorn", "uvicorn.access", "sqlalchemy.engine"):
        logging.getLogger(name).handlers.clear()
        logging.getLogger(name).propagate = True

# config/redaction.py (reference service pattern) — add to the processors list BEFORE the renderer
import re

SENSITIVE_KEYS = {
    "password", "passwd", "secret", "token", "access_token", "refresh_token", "session",
    "authorization", "api_key", "apikey", "cookie", "set-cookie", "private_key",
    "client_secret", "x-user-data", "ssn", "card", "card_number", "cvv",
}
_EMAIL = re.compile(r"([A-Za-z0-9._%+-])[A-Za-z0-9._%+-]*(@[A-Za-z0-9.-]+)")
_DIGITS = re.compile(r"\b\d{13,19}\b")                       # card-like runs
_BEARER = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._-]+")
_DSN_CREDS = re.compile(r"(\w+://[^:/\s]*:)([^@/\s]+)(@)")   # creds in a DSN (incl. empty username)

def _mask_str(value: str) -> str:
    value = _EMAIL.sub(r"\1***\2", value)
    value = _DIGITS.sub("****", value)
    value = _BEARER.sub("Bearer ***", value)
    value = _DSN_CREDS.sub(r"\1***\3", value)
    return value

def _redact(value):                              # recurse dicts + lists; mask by key and by content
    if isinstance(value, dict):
        return {k: ("***" if k.lower() in SENSITIVE_KEYS else _redact(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(v) for v in value]
    if isinstance(value, str):
        return _mask_str(value)
    return value

def redact_processor(_logger, _method, event_dict):
    return _redact(event_dict)                   # full-tree: nested objects & arrays are covered too

# In setup_logging(): structlog.configure(processors=[..., redact_processor, <renderer>])

# Audit log: allowlist fields, never dump the whole user object
def audit_log(action: str, *, user_id: str, tenant_id: str, resource_id: str, result: str) -> None:
    logger.info("audit", action=action, user_id=user_id, tenant_id=tenant_id,
                resource_id=resource_id, result=result)   # no email/name/token

# app/telemetry.py (reference service pattern)
import structlog
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.resources import Resource, SERVICE_NAME
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

logger = structlog.get_logger(__name__)

def initialize_telemetry() -> None:
    if not settings.OTEL_ENABLED:
        logger.info("telemetry.disabled")
        return

    try:
        resource = Resource.create({SERVICE_NAME: settings.OTEL_SERVICE_NAME})
        provider = TracerProvider(resource=resource)
        exporter = OTLPSpanExporter(endpoint=settings.OTEL_EXPORTER_ENDPOINT)
        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)
        logger.info("telemetry.initialized", service=settings.OTEL_SERVICE_NAME)
    except ImportError:
        logger.warning("telemetry.import_error", msg="OTEL packages not installed")

def instrument_app(app):
    if not settings.OTEL_ENABLED:
        return
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        FastAPIInstrumentor.instrument_app(app)
        logger.info("telemetry.fastapi_instrumented")
    except ImportError:
        logger.warning("telemetry.fastapi_import_error")

# app/routing.py (reference service pattern)
from fastapi.routing import APIRoute
from fastapi import Request, Response
import time

class CustomRequestRoute(APIRoute):
    def get_route_handler(self) -> Callable:
        original_route_handler = super().get_route_handler()

        async def custom_route_handler(request: Request) -> Response:
            start_time = time.perf_counter()
            try:
                response = await original_route_handler(request)
                duration = time.perf_counter() - start_time
                logger.info(
                    "request_handled",
                    method=request.method,
                    path=request.url.path,
                    status_code=response.status_code,
                    duration=round(duration, 4),
                )
                return response
            except RequestValidationError as exc:
                logger.warning("validation_error", path=request.url.path, errors=exc.errors())
                # ... return 400
            except HTTPException as exc:
                logger.warning("http_exception", path=request.url.path, status=exc.status_code)
                # ... return exc.status_code
            except Exception as exc:
                logger.exception("unhandled_exception", path=request.url.path)
                # ... return 500

        return custom_route_handler

# middleware/logging.py (production service pattern)
from opentelemetry.trace import get_current_span

class TraceIDMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            span = get_current_span()
            if span and span.is_recording():
                scope["trace_id"] = format(span.get_span_context().trace_id, "032x")
                scope["span_id"] = format(span.get_span_context().span_id, "016x")

        async def send_wrapper(message):
            if message["type"] == "http.response.start" and "trace_id" in scope:
                headers = list(message.get("headers", []))
                headers.append([b"x-trace-id", scope["trace_id"].encode()])
                headers.append([b"x-span-id", scope["span_id"].encode()])
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_wrapper)

# middleware/prometheus.py (production service pattern)
import time
import re
from starlette.middleware.base import BaseHTTPMiddleware

UUID_PATTERN = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
NUMERIC_ID_PATTERN = r"/\d+(?=/|$)"
EXCLUDED_PATHS = {"/health", "/_healthz", "/_readyz", "/metrics", "/docs", "/openapi.json"}

class PrometheusMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        original_path = request.url.path
        path = self._normalize_path(original_path)

        if original_path in EXCLUDED_PATHS or path in EXCLUDED_PATHS:
            return await call_next(request)

        start_time = time.time()
        try:
            response = await call_next(request)
            duration = time.time() - start_time
            record_http_request_received(request.method, path, response.status_code, duration)
            return response
        except Exception:
            duration = time.time() - start_time
            record_http_request_received(request.method, path, 500, duration)
            raise

    def _normalize_path(self, path: str) -> str:
        path = re.sub(UUID_PATTERN, "{uuid}", path, flags=re.IGNORECASE)
        path = re.sub(NUMERIC_ID_PATTERN, "/{id}", path)
        path = re.sub(r"/+", "/", path)
        if path != "/" and path.endswith("/"):
            path = path[:-1]
        return path

# metrics/constant.py (production service pattern)
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

# metrics/helper.py
def record_http_request_received(method, path, status_code, duration):
    HTTP_REQUEST_RECEIVED.labels(
        method=method, path=path, status_code=str(status_code), service_name=METRIC_SERVICE_IDENTIFIER
    ).observe(duration)

# metrics/exporter.py (production service pattern)
import asyncio
from prometheus_client import generate_latest

async def start_metrics_exporter():
    while True:
        try:
            metrics_data = generate_latest(registry=get_metrics_registry()).decode("utf-8")
            with open(LOG_FILE, "w") as f:
                f.write(metrics_data)
            await asyncio.sleep(METRICS_EXPORT_INTERVAL)
        except asyncio.CancelledError:
            break

# Health endpoints (reference service pattern)
from sqlalchemy import text

async def healthz():
    return ResponseData.ok(message="OK")

async def readyz(connection_handler=Depends(get_connection_handler)):
    checks = {}
    try:
        await connection_handler.session.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as e:
        checks["database"] = f"error: {str(e)}"

    try:
        pong = await connection_handler.redis.ping()
        checks["redis"] = "ok" if pong else "error: no pong"
    except Exception as e:
        checks["redis"] = f"error: {str(e)}"

    if all(v == "ok" for v in checks.values()):
        return ResponseData.ok(data=checks, message="All systems operational")
    return ORJSONResponse(status_code=503, content=ResponseData.error(message="Service degraded", errors=[checks]).model_dump())

# app router (reference service pattern)
api_router.add_api_route("/_healthz", healthz, methods=["GET"], tags=["health"])
api_router.add_api_route("/_readyz", readyz, methods=["GET"], tags=["health"])
```

## Anti-patterns to avoid

- **Logging secrets or PII** — never log passwords, tokens, API keys, or personally identifiable information (email, phone, address). Redact in a **pipeline processor** (so it can't be forgotten at a call site), not ad hoc; mask DB-URL credentials; allowlist audit-event fields instead of dumping the user object.
- **Logging full request/response bodies** — bodies carry PII and secrets and explode log volume; truncate (e.g. 2 KB) and run them through the redaction processor.
- **Unbounded cardinality in metrics labels** — never use raw user IDs, tenant IDs, or request IDs as Prometheus labels; path normalization is mandatory for both inbound and outbound metrics.
- **Conflating inbound and outbound metrics** — never use the same metric name for requests received and requests sent; use distinct `HTTP_REQUEST_RECEIVED` and `HTTP_REQUEST_SENT` histograms with appropriate labels.
- **Including query params or hostnames in outbound path labels** — strip query strings and extract only the path component from outbound URLs to avoid cardinality explosion.
- **Blocking I/O in logging** — avoid file writes or network calls in log formatters; use async background tasks for remote log shipping.
- **Missing OTEL graceful degradation** — app must start even if OTEL libraries are missing; wrap all imports in `try`/`except ImportError`.
- **Health checks that call external APIs** — probes should only check local dependencies (DB, Redis, in-memory state); external API health belongs in separate synthetic monitors.
- **Forgetting to flush on shutdown** — call `tracer_provider.shutdown()` and cancel metrics exporter tasks in app shutdown hooks to avoid losing spans/metrics.
- **Using default Prometheus registry** — always create a custom `CollectorRegistry()` to isolate your metrics from library-injected defaults.
- **Single metrics endpoint for all service modes** — consumers/workers/cron jobs need separate HTTP servers on different ports; don't assume FastAPI middleware will work for non-HTTP processes.

## References

- [logging-and-structlog.md](./references/logging-and-structlog.md) — Structlog configuration, processor pipeline, stdlib integration
- [pii-redaction.md](./references/pii-redaction.md) — PII/secret redaction processor, sensitive-key denylist, pattern masking, DB-URL credential masking, audit-event field allowlists
- [tracing-and-metrics.md](./references/tracing-and-metrics.md) — OpenTelemetry SDK init, auto-instrumentation, Prometheus middleware, metrics export
- [health-and-readiness.md](./references/health-and-readiness.md) — Liveness and readiness probe patterns, dependency checks
- [outbound-metrics-and-multi-mode.md](./references/outbound-metrics-and-multi-mode.md) — Outbound HTTP metrics decorator, multi-mode service instrumentation (consumers/workers/cron)
- [repo-evidence.md](./references/repo-evidence.md) — Real file paths and code snippets from source repos
