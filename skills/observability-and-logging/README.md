# Observability and Logging

Production-grade observability patterns for FastAPI backends: structured logging, distributed tracing, error tracking, metrics collection, and health endpoints.

## What this skill covers

- **Structured logging with structlog**: JSON/console rendering, processor pipeline, stdlib integration
- **Centralized request logging**: `CustomRequestRoute` pattern for request/exception logging with timing
- **OpenTelemetry distributed tracing**: OTLP export, FastAPI/asyncpg/Redis/Kafka auto-instrumentation, SDK initialization
- **Trace ID propagation**: `TraceIDMiddleware` to inject `X-Trace-ID` / `X-Span-ID` response headers
- **Sentry error tracking**: Integration setup with LoggingIntegration and SqlalchemyIntegration
- **Prometheus RED metrics**: Custom registry, histogram buckets, PrometheusMiddleware, path normalization
- **Inbound HTTP metrics**: `HTTP_REQUEST_RECEIVED` histogram via PrometheusMiddleware
- **Outbound HTTP metrics**: `HTTP_REQUEST_SENT` histogram via `@prometheus_http_outbound` decorator
- **Metrics file exporter**: Background task pattern for `/var/data/metrics/{POD_NAME}.prom` (node exporter textfile collector)
- **Non-HTTP metrics**: Kafka consumers, background workers, cron jobs, Temporal workflows
- **Multi-mode service instrumentation**: Dedicated metrics HTTP servers for consumers/workers/cron on separate ports (8001-8004)
- **Health endpoints**: Liveness (`/_healthz`) and readiness (`/_readyz`) probes with DB/Redis checks

## Provenance

Derived from real-world production Python/FastAPI services implementing structured logging, OpenTelemetry tracing, Prometheus metrics, and health probes.

## How to apply

1. **For new services**: Copy structlog setup (`config/logging.py`), OTEL init (`app/telemetry.py`), and health endpoints (`common/health.py`) from the skeleton examples in this skill.
2. **For centralized logging**: Use `CustomRequestRoute` on your routers to log all requests/exceptions with timing.
3. **For inbound metrics**: Add `PrometheusMiddleware` to your FastAPI app, create a custom registry, and define `HTTP_REQUEST_RECEIVED` histogram.
4. **For outbound metrics**: Decorate HTTP client methods with `@prometheus_http_outbound()` to track external API calls.
5. **For multi-mode services**: Use `init_metrics_for_service(mode)` to start dedicated metrics HTTP servers for consumers/workers/cron on ports 8001-8004.
6. **For trace propagation**: Add `TraceIDMiddleware` after OTEL instrumentation to inject trace/span IDs into response headers.
7. **For file-based metrics**: Use the background task pattern (`metrics/exporter.py`) to write metrics to `/var/data/metrics/{POD_NAME}.prom` for Prometheus node exporter.
