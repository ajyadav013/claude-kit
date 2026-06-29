---
name: otel-tracing
description: Vendor-neutral distributed tracing with OpenTelemetry exported to Grafana Tempo (OTel model, Collector pipeline, sampling, TraceQL). Do NOT use for app-side observability setup or LLM call tracing.
---

# Distributed Tracing with OpenTelemetry and Grafana Tempo

Vendor-neutral distributed tracing instruments requests across service boundaries, correlates them with logs and metrics, and exports trace data to Grafana Tempo for querying with TraceQL. The OpenTelemetry SDK captures spans in your service, exports OTLP to an optional Collector for sampling and enrichment, and lands traces in Tempo's object-storage backend. Tempo derives service-graph metrics, links traces to logs via shared identifiers, and surfaces exemplars that pivot from metric spikes to representative traces. This skill covers the OTel data model, the standard env-var contract, the pipeline topology, instrumentation principles, sampling, TraceQL, and the correlation patterns that bind traces to logs and metrics.

> **Sibling boundary:** This skill covers the language-neutral OTLP/Collector/Tempo pipeline and the OTel data model. For app-side observability (structured logging, PII/secret redaction, error tracking, RED metrics, liveness/readiness probes, framework auto-instrumentation wiring), see `observability-and-logging`. For LLM call tracing (prompts, tokens, cost), see `langfuse-llm-tracing`.

## When to use

- You need to trace requests across multiple services and see the full call graph.
- You want to correlate logs with traces by stamping trace IDs onto structured log lines.
- You are adopting OpenTelemetry and need to configure the SDK, Collector, and Tempo backend.
- You need to derive RED metrics (service graphs) from trace spans without instrumenting metrics in application code.
- You want to sample traces intelligently (retain all errors and slow requests, probabilistic sampling for normal traffic) to control ingestion cost.
- You need to query traces by service name, span attributes, duration, or status using TraceQL.
- You are joining a framework or orchestration-engine OTel interceptor with HTTP/RPC auto-instrumentation to build a single trace tree.

## The signal pipeline

```
┌────────────────┐
│  Instrumented  │  service.name, deployment.environment
│    Service     │  (OTel SDK: auto + manual instrumentation)
└────────┬───────┘
         │ OTLP (gRPC :4317 or HTTP :4318)
         ▼
┌────────────────┐  optional but recommended in production
│ OTel Collector │  (batch, tail_sampling, enrichment, redaction)
└────────┬───────┘
         │ OTLP
         ▼
┌────────────────┐  native OTLP receiver (:4317/:4318)
│ Grafana Tempo  │  (distributor → ingester → object storage)
│  (Backend)     │  (metrics-generator → Prometheus, querier, compactor)
└────────┬───────┘
         │ HTTP/gRPC API + TraceQL
         ▼
┌────────────────┐
│     Grafana    │  (Explore, dashboards, trace-to-logs, trace-to-metrics)
└────────────────┘
```

The service exports OTLP either directly to Tempo's distributor or through a Collector. The Collector is optional for simple setups but recommended for buffering, tail sampling, attribute redaction, and fan-out to multiple backends. Tempo's distributor validates spans and shards a trace by hashing its TraceId; the ingester batches spans into blocks and flushes them to object storage (S3/GCS/Azure); the compactor merges blocks and enforces retention; the querier (behind a query-frontend) serves TraceQL. The optional metrics-generator derives RED metrics, and Grafana queries it all.

## The OTel trace data model

| Concept | Definition |
|---------|-----------|
| **Trace** | The full lifecycle of a request as it flows through a distributed system, identified by a 16-byte TraceId. |
| **Span** | A single operation within a trace (an HTTP request, a database query, a function call), identified by an 8-byte SpanId. Child spans record their parent's SpanId to form hierarchies. |
| **SpanContext** | The propagated, immutable identifiers: TraceId, SpanId, and TraceFlags (a 1-byte bitmap carrying the sampling decision). W3C Trace Context carries it in the `traceparent` header. |
| **Attributes** | Key-value pairs describing the span (`http.request.method`, `db.system`, `rpc.service`). Use semantic conventions for cross-vendor portability. |
| **Events** | Timestamped annotations attached to a span (exceptions, state transitions). Capped by `OTEL_SPAN_EVENT_COUNT_LIMIT` (default 128). |
| **Status** | Span outcome: Unset, Ok, or Error. Tail sampling uses status to retain all errors. |
| **Resource** | The entity producing telemetry (service, host, container). Must include `service.name`; if unset, SDKs fall back to `unknown_service:<executable>`. The value should be identical across all instances of a horizontally-scaled service. |
| **Semantic Conventions** | Standard attribute names (`http.response.status_code`, `db.query.text`, `server.address`) that enable cross-backend queries and automatic dashboards. |

## The standard OTel env-var contract

Configure the SDK via environment variables to keep application code endpoint-agnostic. The same binary points at a local collector, a cluster collector, or Tempo's OTLP receiver just by changing the environment.

| Variable | Purpose | Default / Notes |
|----------|---------|-----------------|
| `OTEL_EXPORTER_OTLP_ENDPOINT` | Base endpoint URL for all signals (e.g. `http://collector:4318`). OTLP/HTTP appends `/v1/traces`. | `http://localhost:4317` (gRPC) |
| `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` | Signal-specific traces endpoint; overrides the base endpoint for traces. Use when routing signals to different backends. | Unset |
| `OTEL_EXPORTER_OTLP_PROTOCOL` | Transport: `grpc`, `http/protobuf` (recommended), `http/json`. Verify backend support. | SDK-dependent |
| `OTEL_TRACES_EXPORTER` | Exporter to use: `otlp` (default), `jaeger`, `zipkin`, `none`. Set `none` to disable trace export. | `otlp` |
| `OTEL_SERVICE_NAME` | Sets the `service.name` resource attribute. **Required to find traces in Tempo.** Takes precedence over `OTEL_RESOURCE_ATTRIBUTES`. Use the same value for all instances of one service. | `unknown_service:<executable>` |
| `OTEL_RESOURCE_ATTRIBUTES` | Comma-separated key=value pairs (e.g. `service.namespace=checkout,deployment.environment=production,service.version=1.2.3`). | Empty |
| `OTEL_EXPORTER_OTLP_HEADERS` | Headers sent with OTLP requests (e.g. `Authorization=Bearer token`). For signal-specific headers, use `OTEL_EXPORTER_OTLP_TRACES_HEADERS`. | Empty |
| `OTEL_EXPORTER_OTLP_COMPRESSION` | Compression: `gzip`, `none`. Use `gzip` over public networks to reduce egress. | `none` |
| `OTEL_PROPAGATORS` | Propagators: `tracecontext`, `baggage`, `b3`, `b3multi`, `jaeger`, `xray`, `ottrace`. Comma-separated. | `tracecontext,baggage` (W3C) |
| `OTEL_TRACES_SAMPLER` | Sampler: `always_on`, `always_off`, `traceidratio`, `parentbased_always_on`, `parentbased_always_off`, `parentbased_traceidratio`. | `parentbased_always_on` |
| `OTEL_TRACES_SAMPLER_ARG` | For ratio samplers, a decimal 0.0–1.0 sampling probability (e.g. `0.1` for 10%). | Unset |
| `OTEL_LOG_LEVEL` | SDK log level: `debug`, `info`, `warn`, `error`. Use `debug` to troubleshoot init or export. | `info` |
| `OTEL_SPAN_ATTRIBUTE_VALUE_LENGTH_LIMIT` | Max length of span attribute values (e.g. `4096`). Prevents unbounded attribute sizes. | Unlimited |
| `OTEL_SPAN_ATTRIBUTE_COUNT_LIMIT` | Max attributes per span. | `128` |

**Endpoint pitfall:** Port 4317 is gRPC, 4318 is HTTP. OTLP/HTTP requires `/v1/traces` appended to the endpoint (some libraries append it, some require it in `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT`); OTLP/gRPC uses no path suffix. Verify protocol-port alignment — 4317 with `http/protobuf`, or 4318 with `grpc`, is a common misconfiguration.

**Resource pitfall:** Missing `service.name` is the most common "I can't find my traces" cause. Always set `OTEL_SERVICE_NAME` or include `service.name=your-service` in `OTEL_RESOURCE_ATTRIBUTES`. Setting both can confuse debugging, since `OTEL_SERVICE_NAME` wins.

## Instrumentation principle

**Env-gated + fail-safe + idempotent:**

- Enable tracing only when a standard OTLP endpoint/exporter env var is present (`OTEL_EXPORTER_OTLP_ENDPOINT`, `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT`, or `OTEL_TRACES_EXPORTER` set to a non-`none` value). Otherwise, no-op and log.
- Tracing setup must never crash or block service startup. Wrap initialization in the language's error guard and continue untraced on failure (`.claude/rules/agent-resilience.md`).
- Make initialization idempotent. Flush and shut down the tracer provider on graceful shutdown, or you lose the last batch.

**Auto + manual + framework interceptors:**

- **Auto-instrumentation** uses language mechanisms (Java bytecode manipulation, runtime monkey patching, .NET runtime hooks) to intercept library/framework calls (HTTP, database, RPC). It gives immediate visibility; its limitation is no business-logic awareness.
- **Manual instrumentation** provides precision for custom spans, business operations, and enriched attributes. Production pattern: auto-instrumentation baseline plus manual spans for business-critical flows.
- **Framework interceptors** (web-framework and workflow/orchestration-engine OTel interceptors) emit deeper semantic spans than generic HTTP instrumentation and propagate context to child operations.

**One trace tree via propagation:**

- W3C Trace Context propagation uses the `traceparent` header (version, trace-id, parent span-id, trace-flags). Configure a composite propagator with the W3C trace-context and baggage propagators.
- Context propagation across async boundaries requires the language's context mechanism (e.g. `AsyncLocalStorage` in Node.js, `contextvars` in Python). At queue boundaries, manually inject context into message headers before enqueue and extract it after dequeue to maintain trace continuity.
- Baggage propagates key-value pairs across service boundaries alongside trace context. It is visible to the entire request path; validate at system boundaries, keep it small, and use it only for non-sensitive identifiers (never PII or credentials).

**Initialization order:**

Configure Resource → Exporter → SpanProcessor → TracerProvider, then register the global provider **before** any instrumentation or application code runs. Instrumentation libraries cache the global TracerProvider at import/load time, so late initialization yields no-op tracers and zero spans.

**Span processors:**

- Production deployments use `BatchSpanProcessor` (batches spans before export; OTel spec defaults: 5s schedule delay, 512 max export batch size, 2048 max queue size, 30s export timeout). High-throughput services raise the queue and batch sizes so spans are not dropped under load.
- `SimpleSpanProcessor` (synchronous export per span) is for testing only; it blocks application threads and degrades latency.

See `references/instrumentation.md` for auto-instrumentation setup, manual span creation, and context propagation patterns. See `references/collector.md` for Collector topology and processor pipelines.

## Sampling

**Head-based sampling** makes the decision at span creation time. It is stateless and gives predictable cost control but cannot guarantee capture of errors or latency outliers. SDKs use `parentbased_always_on` (preserve trace context) or `parentbased_traceidratio` (probabilistic).

**Tail-based sampling** defers the decision until the trace completes, enabling outcome-driven selection (errors, high latency, specific attributes). It requires buffering spans in Collector memory, routing all spans of a trace to one instance via the loadbalancing exporter (keyed by TraceId), and careful capacity planning. A missing or misconfigured loadbalancing exporter fragments traces and produces wrong decisions.

**Hybrid sampling pattern (production standard):**

- SDKs use `parentbased_always_on` to preserve trace context across services.
- The Collector applies `tail_sampling` with policies: 100% errors, 100% latency outliers, a low probabilistic rate (e.g. ~5%) for normal traffic.
- Result: every critical trace retained for debugging, normal traffic sampled for cost control.

**Tail sampling pitfalls:** Set `decision_wait` to 2–3× p99 trace duration; if it is shorter, the sampler decides on incomplete traces. Tail sampling buffers whole traces in memory, so monitor Collector memory and always pair `tail_sampling` with the `memory_limiter` processor (first in the pipeline, `batch` last).

See `references/sampling.md` for sampler configuration, tail-sampling policies, and the loadbalancing exporter topology.

## Tempo essentials

Grafana Tempo is a cost-efficient, object-storage-backed trace backend that natively accepts OTLP on the default ports 4317 (gRPC) and 4318 (HTTP) — no special exporter is needed, since the app and Collector already speak OTLP. The **distributor** validates spans and shards a trace by hashing its TraceId. The **ingester** batches spans into blocks and flushes them to object storage (S3/GCS/Azure); recent, not-yet-flushed traces are served from the ingesters. The **querier** (behind a **query-frontend**) reads bloom filters and indexes from object storage to locate traces for TraceQL. The **compactor** merges smaller blocks, deduplicates, and expires data after the retention period (the `compactor.block_retention` default is 336h / 14 days). Tempo runs as a single binary (monolithic) or as independently-scaled microservices; newer versions add an optional Kafka-based ingest path — check your version's docs before assuming it.

**TraceQL:** Tempo's trace query language. It addresses resource attributes (`resource.service.name`, `resource.deployment.environment`), span attributes (`span.http.request.method`, `span.db.system`), and intrinsics (`span:duration`, `span:status`, `span:kind`, `trace:duration`, `trace:rootService`). It supports comparison operators (`=`, `!=`, `>`, `>=`, `<`, `<=`, `=~` regex, `!~` negated regex), logical operators (`&&`, `||`), aggregators (`count`, `avg`, `max`, `min`, `sum`), and structural operators (`>>` descendant, `<<` ancestor, `>` child, `<` parent, `~` sibling). Regex operators are anchored by default — use `.*pattern.*` for unanchored matching. **Trace-level intrinsics** (`trace:duration`, `trace:rootService`) are generally more performant than span-level scans; prefer them when possible.

**Metrics-generator:** Derives RED metrics from spans via the `span-metrics` processor (counter `traces_spanmetrics_calls_total`, histogram `traces_spanmetrics_latency`) and the `service-graphs` processor (request/failed counters and latency histograms per client-server pair). It writes to a Prometheus-compatible `remote_write` endpoint. Enabling many span-metric dimensions sharply increases cardinality and cost — keep the dimension set bounded.

See `references/tempo.md` for deployment modes, retention configuration, and TraceQL query patterns.

## Correlation

**Trace-to-logs:** Stamp the active `trace_id` and `span_id` onto every structured log line. In Grafana, configure the Tempo datasource's trace-to-logs feature pointing at your log store (Loki, Elasticsearch, and others). This lets you pivot a log line to its full trace and back. Use consistent resource attributes (`service.name`, `deployment.environment`) across logs, metrics, and traces so they join.

**Trace-to-metrics:** Grafana's trace-to-metrics links spans to metric queries using span/trace variables (e.g. span name, duration, trace ID), so you can jump from a span to the RED metrics around it.

**Metrics-to-traces (exemplars):** The metrics-generator's span metrics can embed trace IDs as exemplars on Prometheus histograms. In Grafana, clicking an exemplar on a graph jumps to the corresponding trace — the reverse link from a metric spike to a representative trace.

**Service graphs:** The `service-graphs` processor analyzes traces for edges (parent-child span relationships representing requests between services) and produces metrics labelled by `client`, `server`, and connection type. Grafana's Service Graph view renders these edges as a directed graph with RED metrics per edge.

**Cardinality pitfall:** Raw IDs and paths used as span-derived metric labels explode cardinality. Normalize (replace IDs/UUIDs with placeholders) before they become labels. Span attributes in Tempo are cheaper than metric labels, but keep them bounded too.

See `references/correlation.md` for trace_id log injection, exemplar configuration, and service-graph setup.

## References

- `references/instrumentation.md` — Auto-instrumentation setup, manual span creation, context propagation across async/queue boundaries, the standard env-var contract, and TracerProvider initialization order.
- `references/collector.md` — Collector agent-gateway topology, processor pipelines (memory_limiter, batch, tail_sampling, attributes, filter), OTLP exporter configuration, and the loadbalancing exporter for tail sampling.
- `references/sampling.md` — Head-based vs tail-based sampling, sampler configuration (SDK and Collector), tail-sampling policies (error, latency, probabilistic), and the hybrid sampling pattern.
- `references/tempo.md` — Tempo architecture (distributor, ingester, querier, compactor), deployment modes (monolithic vs microservices), retention/compaction configuration, TraceQL query patterns, and metrics-generator setup.
- `references/correlation.md` — Trace-to-logs (trace_id injection, Grafana datasource config), trace-to-metrics, metrics-to-traces (exemplars), and service graphs.
- `references/gotchas.md` — The highest-leverage failure modes and fixes: endpoint/port/path traps, lost context propagation, missing `service.name`, over-sampling cost, batch-queue overflow, cardinality blowups, and double-tracing.

## Provenance

Re-derived from public OpenTelemetry documentation (opentelemetry.io), the W3C Trace Context specification (w3.org/TR/trace-context), and Grafana Tempo documentation (grafana.com/docs/tempo). When upstream documentation disagrees with this skill, trust upstream and update the skill.

## Related

- `.claude/rules/devops-observability.md` — The neutral policy for observability, logging, metrics, and tracing across all stacks.
- `observability-engineer` agent — The role responsible for instrumenting services, configuring the Collector and Tempo, and maintaining correlation patterns.
- `.claude/rules/agent-resilience.md` — Fail-safe principles for instrumentation (never crash, degrade gracefully).
- `observability-and-logging` — App-side observability: structured logging, PII/secret redaction, error tracking, RED metrics, liveness/readiness probes, and framework auto-instrumentation wiring.
- `langfuse-llm-tracing` — LLM call tracing (prompts, tokens, cost) for model observability.
