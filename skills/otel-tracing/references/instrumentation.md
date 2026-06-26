# Service Instrumentation and SDK Initialization

Instrumentation is how a service turns work into spans and ships them to the pipeline. Get four things right and everything downstream (sampling, the collector, the trace backend) works: a correct **Resource** (`service.name` above all), the **TracerProvider → exporter → processor** init done in the right order and *before* any instrumented code runs, an **env-gated + fail-safe + idempotent + shutdown-flushed** init wrapper, and disciplined use of the standard OTLP **env-var contract**. This reference is language-neutral: every OTel SDK shares this shape; names and module paths differ.

> **Sibling boundary.** This reference is part of `otel-tracing` — the language-neutral distributed-tracing pipeline and trace-backend skill. It covers the OTel data model, SDK init, the OTLP env contract, and how span sources combine. It does **not** cover app-side observability wiring for a specific stack (structured logging, PII/secret redaction, error-tracking SDKs, RED metrics, health probes, and concrete per-framework auto-instrumentation packages) — that is the sibling `observability-and-logging`. It does **not** cover tracing LLM/model calls (prompts, tokens, cost) — that is `langfuse-llm-tracing`. The neutral policy lives in `.claude/rules/devops-observability.md`; the role is the `observability-engineer` agent.

## When to use

- Standing up tracing in a new service, or onboarding a service to your existing collector/backend
- Deciding Resource attributes and confirming `service.name` is stable across replicas
- Wiring TracerProvider + exporter + span processor in the correct order
- Making init endpoint-agnostic, crash-proof, re-entrant, and flush-on-exit
- Choosing between auto-instrumentation, manual spans, and framework interceptors
- Stitching spans from those three sources into one trace via W3C context propagation

## The OpenTelemetry data model

OpenTelemetry models a distributed request as a tree of spans:

- **Trace**: the full request lifecycle across all services, identified by a 16-byte **TraceId**.
- **Span**: a single operation within a trace (an HTTP request, a DB query, a function call), identified by an 8-byte **SpanId**.
- **SpanContext**: the propagated identifiers — TraceId, SpanId, and **TraceFlags** (a 1-byte bitmap; the low bit is the *sampled* flag) — that maintain trace continuity across process and network boundaries.

Child spans record their parent's SpanId to form the tree; the root span has no parent. The W3C Trace Context standard carries this in the `traceparent` HTTP header with four dash-separated fields: `version-traceid-parentid-traceflags` (e.g. `00-<trace-id>-<parent-id>-<trace-flags>`), where `parentid` is the SpanId of the calling span.

## Resource attributes and semantic conventions

A **Resource** is the entity producing telemetry: the service, host, container, or process. Configure the Resource *before* creating the TracerProvider.

`service.name` is the single most important attribute. If unset, SDKs fall back to `unknown_service:` concatenated with the process executable name, which makes traces effectively unsearchable in any backend. Set it to a stable, human-readable identifier, and keep it **identical across every instance of a horizontally-scaled service** — if each replica reports a different name the backend treats them as separate services and aggregations break.

| Attribute | Purpose | Example |
|-----------|---------|---------|
| `service.name` | Service identifier (required) | `payment-api` |
| `service.namespace` | Logical grouping of services | `backend`, `data-pipeline` |
| `service.version` | Release identifier for version tracking | `1.2.3`, build SHA |
| `deployment.environment` | Environment name | `production`, `staging`, `dev` |
| `service.instance.id` | Unique instance identifier | pod name, hostname, UUID |
| `host.name` | Host name | host identifier |
| `k8s.pod.name` | Kubernetes pod name | pod identifier |
| `k8s.namespace.name` | Kubernetes namespace | namespace identifier |

Use OpenTelemetry **semantic conventions** for attribute names (`http.request.method`, `db.system`, `rpc.service`, and so on). Standard names give you cross-vendor query portability and ready-made backend dashboards; custom attributes work but require manual dashboards and don't transfer across teams.

## SDK initialization order

Initialization order is load-bearing. Instrumentation libraries capture the global TracerProvider when they load, so anything instrumented before the provider is registered gets a no-op tracer and emits zero spans. Configure Resource → exporter → span processor → TracerProvider, register the provider globally, then load instrumentation.

```
# 1. Resource — service identity
resource = Resource.create({
    "service.name":            SERVICE_NAME,
    "service.namespace":       SERVICE_NAMESPACE,
    "service.version":         SERVICE_VERSION,
    "deployment.environment":  ENVIRONMENT,
})

# 2. OTLP exporter — endpoint, protocol, headers
exporter = OTLPSpanExporter(
    endpoint = OTLP_ENDPOINT,        # e.g. "http://collector:4318/v1/traces"
    protocol = "http/protobuf",      # or "grpc"
    headers  = { "Authorization": "Bearer <token>" },
    compression = "gzip",            # optional: reduce egress
)

# 3. Span processor — Batch in production
processor = BatchSpanProcessor(
    exporter,
    max_queue_size        = 8192,
    schedule_delay_millis = 5000,    # 5s
    max_export_batch_size = 4096,
)

# 4. TracerProvider with Resource + processor
provider = TracerProvider(resource = resource)
provider.add_span_processor(processor)

# 5. Register the global provider BEFORE loading instrumentation
set_tracer_provider(provider)

# 6. Now load auto-instrumentation (HTTP server/client, DB, messaging, RPC)
```

Every OpenTelemetry SDK (Go, Java, JavaScript/Node, .NET, Python, Ruby, Rust) shares this shape. Function names and module paths differ; the pipeline does not.

## The env-gated, fail-safe, idempotent, flush-on-exit init pattern

This is the most important operational habit. A service must never crash, block startup, or lose its final batch because of tracing setup. The pattern below is shown as pseudocode — apply the principle in your language's SDK.

**Env-gated** — enable tracing only when an OTLP endpoint is configured, so the same binary points at a local collector, a cluster collector, or a managed receiver by changing env vars alone:

```
function init_tracing():
    endpoint = env("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT") or env("OTEL_EXPORTER_OTLP_ENDPOINT")
    exporter = env("OTEL_TRACES_EXPORTER", default="otlp")

    if endpoint is empty or exporter == "none":
        log.info("tracing disabled: no OTLP endpoint configured")
        return
    ...
```

**Idempotent** — guard against double init (test harnesses, framework reloads, multiple entrypoints) by checking whether a real provider is already registered:

```
    if global_tracer_provider() is already a real TracerProvider:
        log.debug("tracing already initialized")
        return
```

**Fail-safe** — wrap the whole setup; on any failure (network unreachable, bad config, missing dependency), log and continue **untraced**. Observability setup must never take down the service:

```
    try:
        # Resource → exporter → processor → provider
        set_tracer_provider(provider)
        log.info("tracing initialized")
    except error as e:
        log.error("tracing init failed: " + e + " — continuing without tracing")
```

**Flush on exit** — a BatchSpanProcessor buffers spans and exports on a timer or when the batch fills, so a process that exits before the buffer drains loses its last batch. Register a shutdown hook that calls `provider.shutdown()` (which force-flushes), and wire it to your runtime's termination path — process-exit hook plus the container stop signal (commonly `SIGTERM`) so in-flight spans flush during rolling deploys:

```
on_process_exit(  () => provider.shutdown() )
on_terminate_signal( () => { provider.shutdown(); exit(0) } )
```

## The standard OTel env-var contract

Prefer these standard variables over bespoke config keys; they are portable across languages and deployments.

| Variable | Purpose | Default | Example |
|----------|---------|---------|---------|
| `OTEL_EXPORTER_OTLP_ENDPOINT` | Base endpoint for all signals | `http://localhost:4317` | `http://collector:4318` |
| `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` | Traces-only endpoint (overrides base) | (none) | `http://collector:4318/v1/traces` |
| `OTEL_EXPORTER_OTLP_PROTOCOL` | Transport protocol | SDK-dependent | `http/protobuf`, `grpc`, `http/json` |
| `OTEL_TRACES_EXPORTER` | Trace exporter | `otlp` | `otlp`, `jaeger`, `zipkin`, `none` |
| `OTEL_SERVICE_NAME` | Sets `service.name` (wins over resource attrs) | `unknown_service:<exe>` | `payment-api` |
| `OTEL_RESOURCE_ATTRIBUTES` | Comma-separated `key=value` resource attrs | (none) | `service.namespace=backend,deployment.environment=prod,service.version=1.2.3` |
| `OTEL_EXPORTER_OTLP_HEADERS` | Headers on OTLP requests | (none) | `Authorization=Bearer token` |
| `OTEL_EXPORTER_OTLP_TRACES_HEADERS` | Traces-only headers (overrides base) | (none) | tenant header `=tenant-123` |
| `OTEL_EXPORTER_OTLP_COMPRESSION` | Compression | `none` | `gzip` |
| `OTEL_PROPAGATORS` | Propagators | `tracecontext,baggage` | `tracecontext,baggage,b3` |
| `OTEL_TRACES_SAMPLER` | Sampler | `parentbased_always_on` | `parentbased_traceidratio`, `always_off` |
| `OTEL_TRACES_SAMPLER_ARG` | Sampler argument | (none) | `0.1` (10% for `traceidratio`) |
| `OTEL_LOG_LEVEL` | SDK log level | `info` | `debug`, `warn`, `error` |
| `OTEL_SPAN_ATTRIBUTE_VALUE_LENGTH_LIMIT` | Max attribute value length | unlimited | `4096` |
| `OTEL_SPAN_ATTRIBUTE_COUNT_LIMIT` | Max attributes per span | 128 | `256` |
| `OTEL_SPAN_EVENT_COUNT_LIMIT` | Max events per span | 128 | `256` |
| `OTEL_SPAN_LINK_COUNT_LIMIT` | Max links per span | 128 | `256` |

### Endpoint / protocol alignment

OTLP/gRPC defaults to port **4317** and uses no path suffix. OTLP/HTTP defaults to port **4318** and appends signal-specific paths (`/v1/traces`, `/v1/metrics`, `/v1/logs`). The most common misconfiguration is a port/protocol mismatch:

- `grpc` → port **4317**, no path
- `http/protobuf` or `http/json` → port **4318**, append `/v1/traces`

Some SDKs append the path automatically and some don't, so when in doubt set `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` to the full path for HTTP, or the base URL with no path for gRPC. `http/protobuf` has the widest backend compatibility; verify the backend supports your chosen protocol.

### Endpoint and name precedence

`OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` overrides `OTEL_EXPORTER_OTLP_ENDPOINT` for traces — use the signal-specific form only when deliberately routing signals to different backends, and otherwise set one or the other, not both. `OTEL_SERVICE_NAME` takes precedence over a `service.name` set via `OTEL_RESOURCE_ATTRIBUTES`; setting both with different values is a frequent source of misnamed services. Prefer `OTEL_SERVICE_NAME` for clarity.

## BatchSpanProcessor vs SimpleSpanProcessor

Production deployments use **BatchSpanProcessor**; **SimpleSpanProcessor** is for tests only. SimpleSpanProcessor exports each span synchronously on end, blocking the calling path on a network round-trip per span. BatchSpanProcessor buffers spans and exports asynchronously when either the batch size or the schedule delay is hit. When more than one processor is registered, they run in registration order.

| Parameter | Purpose | SDK default | Production |
|-----------|---------|-------------|------------|
| `max_queue_size` | Spans buffered in memory | 2048 | 8192 |
| `schedule_delay_millis` | Max wait before export | 5000ms | 5000–10000ms |
| `max_export_batch_size` | Spans per export | 512 | 4096–8192 |
| `export_timeout_millis` | Export RPC timeout | 30000ms | 30000ms |

Larger batches and longer delays cut CPU and network overhead in high-throughput services. The trade-off is freshness and loss exposure: a longer delay widens the window in which a crash drops un-exported spans. Use shorter delays (1–2s) for live debugging, longer (5–10s) for cost efficiency.

## Auto-instrumentation vs manual spans vs framework interceptors

The three span sources are complementary; production systems use all three.

### Auto-instrumentation

Auto-instrumentation uses language mechanisms (Java bytecode manipulation, Python monkey-patching, .NET runtime hooks) to intercept library and framework calls with no code change. It is enabled at startup and covers:

- HTTP server and HTTP client
- Databases and caches
- Messaging / queues
- RPC (client and server)

**Framework instrumentation** is auto-instrumentation specialized to a particular web framework; it emits deeper, framework-aware span attributes than generic HTTP instrumentation. Its limitation is the same: no business-logic awareness — it emits generic spans (`GET /api/users`) but cannot add domain context like an order or tenant identifier. Treat auto-instrumentation as the baseline HTTP/DB/RPC layer and add manual spans on top for business-critical flows. (The concrete per-framework packages for a given stack belong to the `observability-and-logging` sibling.)

### Manual spans

Manual instrumentation gives precise control over span lifecycle, attributes, status, exceptions, and events. Use it for custom business operations, enriching auto-instrumented spans, and recording failures.

```
tracer = get_tracer(MODULE_NAME)

with tracer.start_as_current_span("process_payment") as span:
    span.set_attribute("payment.method", payment_method)
    span.set_attribute("payment.amount", amount)
    try:
        result = charge(amount)
        span.set_attribute("payment.transaction_id", result.id)
        span.set_status(OK)
    except PaymentDeclined as e:
        span.record_exception(e)
        span.set_status(ERROR, str(e))
        raise
```

Key operations, identical in shape across SDKs:

- `start_as_current_span(name)` — create a span and make it the active parent for children
- `set_attribute(key, value)` — attach searchable metadata (use semantic-convention keys; never put PII or secrets in attributes)
- `set_status(OK | ERROR)` — mark outcome
- `record_exception(error)` — record an exception with stack trace
- `add_event(name, attributes)` — add a timestamped event (`cache_hit`, `retry_attempt`, …)

### Framework interceptors

Some frameworks and orchestration engines ship OpenTelemetry interceptors that emit spans for framework-level operations (workflow/activity engines, task queues, stream processors, GraphQL resolvers). These run at the framework layer and create parent spans; client auto-instrumentation creates child spans for the outbound calls underneath, and the layers combine into one trace via context propagation.

## Combining span sources into one trace tree

All three sources stitch into a single trace through **context propagation**.

### W3C Trace Context

The `traceparent` header (`version-traceid-parentid-traceflags`) carries the active span context. On an inbound request the server SDK extracts it and starts a child of the incoming span; on an outbound request the client SDK injects the current context. In auto-instrumented HTTP servers and clients this is automatic. Manual code must propagate explicitly across async boundaries and queues (below).

### W3C Baggage

Baggage propagates key-value pairs alongside trace context in the `baggage` header, visible to the entire request path:

```
baggage: request_id=...,tenant=...,feature_flag=...
```

Baggage is **not encrypted** and travels in plaintext headers — never put PII, credentials, or secrets in it. Keep it small and validate its size and contents at system entry points. Configure a composite propagator with both Trace Context and Baggage:

```
set_global_propagator(Composite([ W3CTraceContext(), W3CBaggage() ]))
```

or via env var:

```
OTEL_PROPAGATORS=tracecontext,baggage
```

### Across async boundaries

In async runtimes, context must follow the logical request, not the OS thread. SDKs provide language-specific carriers (for example `AsyncLocalStorage` in Node.js, context vars in Python, the equivalent ambient-context primitive elsewhere). Spawning a background task or thread without attaching the current context detaches its spans from the trace; use the SDK helper that captures and re-attaches context for background work.

### Across message queues

Queue boundaries do not propagate context automatically; inject on enqueue and extract on dequeue so consumer spans continue the producer's trace.

```
# Producer — before enqueue
headers = {}
inject(headers)                 # writes traceparent/baggage into carrier
queue.send(message, headers)

# Consumer — after dequeue
ctx   = extract(message.headers)
token = attach(ctx)
try:
    process(message)            # spans here are children of the producer span
finally:
    detach(token)
```

Without this, consumers start fresh traces and the producer→queue→consumer path fragments.

## References

- [collector.md](collector.md) — the OTel Collector pipeline, agent/gateway topology, the core processors, the OTLP-to-Tempo exporter, and the loadbalancing exporter
- [sampling.md](sampling.md) — head vs tail sampling, the hybrid production pattern, decision_wait tuning, and the loadbalancing exporter
- [tempo.md](tempo.md) — Tempo architecture, OTLP ingest, storage/retention/compaction, TraceQL, and the metrics-generator
- [correlation.md](correlation.md) — trace-to-logs / trace-to-metrics / metrics-to-traces (exemplars) and service graphs
- [gotchas.md](gotchas.md) — the highest-leverage failure modes and their fixes

## Provenance and upstream authority

This reference distills the OpenTelemetry specification and SDK configuration docs (opentelemetry.io/docs/specs, opentelemetry.io/docs/languages/sdk-configuration), the OTLP exporter spec (opentelemetry.io/docs/specs/otlp), and the W3C Trace Context and Baggage standards (w3.org/TR/trace-context, w3.org/TR/baggage). OpenTelemetry is an actively developed CNCF project; when upstream documentation disagrees with anything here, trust upstream and verify against your SDK's release notes.

## Related

- `.claude/rules/devops-observability.md` — observability policy (structured logging, metrics, tracing, no PII in telemetry)
- `.claude/rules/agent-resilience.md` — fail-safe init, env-gated startup, graceful degradation
- `observability-engineer` — agent role for the distributed-tracing pipeline and correlation layer
- `observability-and-logging` — sibling skill for stack-specific app-side observability (logging, redaction, error tracking, RED metrics, the concrete per-framework auto-instrumentation packages)
- `langfuse-llm-tracing` — sibling skill for LLM/model tracing (prompts, tokens, cost)
