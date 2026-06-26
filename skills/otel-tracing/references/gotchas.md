# OpenTelemetry + Tempo: highest-leverage failure modes

Most tracing failures are not subtle: the SDK sends to a port or path the backend does not serve, context drops at an async or queue boundary so the trace tree fragments, init runs too late and instrumentation gets a no-op tracer, or a buffer overflows under load and spans vanish silently. This reference catalogs the gotchas that cost the most time — the ones that silently drop traces, fracture distributed trees, or crash startup — each with its fix. It is language-neutral: examples use pseudocode and environment variables, never one stack's API.

> **Sibling boundary.** This skill is the language-neutral *distributed-tracing pipeline + Tempo backend* how-to (OTel data model, the OTLP→Collector→Tempo path, sampling, W3C context propagation, TraceQL, trace↔logs↔metrics correlation). It does **not** cover the app-side observability wiring for one stack — structured logging, PII/secret redaction, error-tracker setup, RED metrics, liveness/readiness probes, and framework auto-instrumentation glue live in the sibling **observability-and-logging**. Tracing LLM/model calls (prompts, tokens, cost) lives in **langfuse-llm-tracing**. The neutral policy is `.claude/rules/devops-observability.md`; the role is the `observability-engineer` agent. This file is the concrete how-to underneath them.

## When to use

- Spans never arrive in Tempo and you suspect an endpoint, port, protocol, or exporter misconfiguration
- A distributed trace fragments into disconnected subtrees across a queue, worker, or async boundary
- Tracing init crashes or blocks your service startup, or the last batch of spans is lost on shutdown
- You can't find a service in Tempo, or trace↔logs↔metrics pivots fail to join
- Trace volume or cost is too high, or span-derived metrics blow up cardinality
- Two tracers (an error tracker and OTel) are both producing spans for the same operations

## Env-var and exporter configuration traps

| Trap | Symptom | Fix |
|------|---------|-----|
| OTLP/HTTP missing the signal path | 404 or silent failure | Set `OTEL_EXPORTER_OTLP_ENDPOINT=http://collector:4318` and let the SDK append `/v1/traces`, **or** set `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT=http://collector:4318/v1/traces` in full. OTLP/gRPC uses **no** path. |
| Protocol/port mismatch | Connection errors or silence | `OTEL_EXPORTER_OTLP_PROTOCOL=grpc` → port **4317**; `http/protobuf` (or `http/json`) → port **4318**. |
| Legacy injected exporter wins | Spans go to the wrong backend | Set `OTEL_TRACES_EXPORTER=otlp`, then `OTEL_EXPORTER_OTLP_ENDPOINT`/`..._TRACES_ENDPOINT`. |
| Signal-specific vs generic vars set inconsistently | Misrouted signals | Use generic `OTEL_EXPORTER_OTLP_ENDPOINT` when all signals share a backend; use `..._TRACES_ENDPOINT` only when fanning out. The signal-specific var overrides the generic one for that signal. |
| `service.name` precedence confusion | Code-set name silently ignored | `OTEL_SERVICE_NAME` overrides `service.name` in `OTEL_RESOURCE_ATTRIBUTES`. Pick one; log the resolved name at init. |

**OTLP endpoint with/without the signal path.** OTLP/HTTP requires the signal-specific suffix (`/v1/traces`, `/v1/metrics`, `/v1/logs`); OTLP/gRPC does not. Some SDKs auto-append the path onto a base endpoint, others require it spelled out. Decide explicitly rather than relying on the default, and verify spans land.

**Protocol-port mismatch.** Port 4317 is OTLP/gRPC; port 4318 is OTLP/HTTP. `http/protobuf` is the recommended default protocol and has the widest backend support; `http/json` and `grpc` are the alternatives. Pointing `http/protobuf` at 4317, or `grpc` at 4318, fails with obscure errors. Tempo's distributor accepts OTLP over gRPC (4317) and HTTP (4318) on their respective ports.

**Legacy exporter override.** A platform chart or sidecar can inject a legacy exporter (a tracing-agent protocol) through env vars or SDK auto-configuration, so your code sets the OTLP endpoint but the exporter-selection var still routes elsewhere. Force the choice with `OTEL_TRACES_EXPORTER=otlp`, then set the endpoint.

**service.name precedence.** When a sidecar sets `OTEL_SERVICE_NAME` and your code sets `service.name` in `OTEL_RESOURCE_ATTRIBUTES`, the env var wins and the code value is dropped. Standardize on one mechanism and emit the resolved service name at startup so mismatches surface immediately.

## Initialization order and fail-safe patterns

**Configure the provider before instrumentation loads.** Instrumentation libraries and framework interceptors capture the global `TracerProvider` when they initialize; if that happens before you configure it, they bind to a no-op tracer and emit zero spans. Build the provider in order — Resource → Exporter → SpanProcessor → TracerProvider — and register it globally **before** any instrumentation or application code runs. In practice this means calling tracing setup as the very first thing in your entry point.

**Never let tracing crash or block startup.** If the exporter cannot reach its endpoint (DNS, network, wrong port) the SDK may raise during init. Tracing is best-effort, never mandatory: wrap setup so that on failure you log a warning and continue with a no-op tracer — the service runs untraced but runs. Sketch (pseudocode):

```
try:
    provider = configure_tracing()   # may fail if exporter init fails
    set_global_tracer_provider(provider)
catch error:
    log.warn("tracing init failed, continuing untraced", error)
    # no provider set -> SDK falls back to a no-op tracer
```

**Flush on shutdown or lose the last batch.** The BatchSpanProcessor buffers spans and exports on a timer (OTel spec defaults: 5 s schedule delay, 512 spans per export, max queue 2048). On exit without a graceful shutdown, whatever is still buffered is lost. Register a shutdown hook that calls the provider's `shutdown()` (which force-flushes) on normal exit, and handle the platform's termination signal so you flush before the orchestrator kills the process. Shutdown is idempotent; call it unconditionally.

## Context propagation across boundaries

**Lost propagation across async/queue/thread boundaries.** A producer enqueues a message (any broker) without serializing the trace context, so the consumer starts a fresh trace and the distributed tree splits into orphaned subtrees. Manually inject the W3C `traceparent` (and, if used, `tracestate`/`baggage`) into the message before send, and extract it after receive to parent the consumer span. Pseudocode:

```
# Producer
carrier = {}
inject(carrier, current_context())          # writes "traceparent" (+ tracestate/baggage)
message.headers["traceparent"] = carrier["traceparent"]
queue.send(message)

# Consumer
carrier = {"traceparent": message.headers["traceparent"]}
ctx = extract(carrier)
with start_span("process_message", context=ctx):
    handle(message)
```

The same inject-before / extract-after pattern applies to every asynchronous boundary: message queues, background workers, scheduled jobs, and cross-process RPC.

**Async context not carried within the runtime.** Runtimes with async execution contexts need a context mechanism (the platform's async-local / context-variable facility) to attach the active span to child operations; without it, async children see no parent. Use the SDK's context manager and confirm the runtime's context integration is enabled rather than disabled. Verify by starting a parent span, launching an async child, and asserting the child carries the parent's span context.

**Configure the propagators.** The W3C standard set is `tracecontext` plus `baggage` (a composite propagator), and it is the OTel default; set `OTEL_PROPAGATORS=tracecontext,baggage` explicitly when a non-standard default might be injected. Baggage rides to every downstream service and is visible in headers, so keep it small, validate it at trust boundaries, and never put PII, credentials, or secrets in it.

## Missing or wrong resource attributes

**Missing service.name.** `service.name` is the single most important attribute for finding traces in Tempo. Unset, the SDK falls back to `unknown_service:<executable name>` — opaque across a fleet. Always set `OTEL_SERVICE_NAME` (or `service.name` in `OTEL_RESOURCE_ATTRIBUTES`) and keep it identical across every instance of a horizontally-scaled service (the service name, not the pod or host name). Verify with `{ resource.service.name = "your-service" }` in Tempo.

**Inconsistent attributes across signals.** When logs, traces, and metrics carry different identifiers for the same service, Grafana's trace-to-logs and trace-to-metrics pivots cannot join. Set the service identity once and reuse it across all three signals: Tempo keys on `resource.service.name`; your logging and metrics backends should carry the same value under their own label schemes. Prefer standard semantic-convention attribute names over custom ones so backends light up dashboards automatically.

## Sampling

**Head sampling drops the errors you need.** Head-based sampling decides at trace start, before status or latency are known, so a 10% ratio blindly discards 90% of traces — including the errors and slow requests you most want. The 2026 production pattern is hybrid: set the SDK sampler to `parentbased_always_on` (it samples everything locally and preserves context for propagation), then make the real decision in the Collector with a `tail_sampling` processor.

**Tail sampling needs whole traces on one instance.** A tail decision must see every span of a TraceId; if spans scatter across Collector replicas, each sees a fragment and decides wrong (dropping an error trace because it only saw the healthy children). Use a two-tier topology: per-host agents forward to gateway replicas via the `loadbalancing` exporter with `routing_key: traceID`, so all spans of a trace hash to the same gateway, where `tail_sampling` runs.

```yaml
# Tier-1 agent (DaemonSet): route whole traces to one gateway
exporters:
  loadbalancing:
    routing_key: traceID
    protocol:
      otlp:
        tls: { insecure: true }
    resolver:
      dns: { hostname: collector-gateway }

# Tier-2 gateway (Deployment): make the decision
processors:
  tail_sampling:
    decision_wait: 10s
    num_traces: 100000
    policies:
      - name: errors
        type: status_code
        status_code: { status_codes: [ERROR] }
      - name: slow
        type: latency
        latency: { threshold_ms: 2000 }
      - name: baseline
        type: probabilistic
        probabilistic: { sampling_percentage: 5 }
```

**decision_wait shorter than trace duration.** `tail_sampling` holds spans for `decision_wait` (default 10s) then evaluates. If p99 trace duration exceeds it, decisions land on incomplete traces and the late error span is missed. Set `decision_wait` to 2–3× p99 trace duration, raise `num_traces` proportionally to hold them, and watch Collector memory — tail sampling is the most common cause of Collector memory growth.

**Over-sampling in production (100% retention).** Keeping every trace in a high-throughput service produces enormous trace volume and storage/query cost in Tempo. Sample: keep 100% of errors and latency outliers and 5–10% of normal traffic via tail sampling. To debug one service, raise its rate temporarily rather than sampling 100% fleet-wide.

## Collector pipeline configuration

**BatchSpanProcessor queue overflow drops spans.** Under load the SDK export queue (spec default max 2048) fills and new spans are dropped silently. Size it for burst: at 1000 spans/sec with a 5s batch timeout you need room for ~5000 spans. Set `OTEL_BSP_MAX_QUEUE_SIZE` and pair it with `OTEL_BSP_MAX_EXPORT_BATCH_SIZE` (4096–8192) and a `OTEL_BSP_SCHEDULE_DELAY` of 5–10s in high-throughput services to avoid tiny, frequent batches. On the Collector side, the `batch` processor (`send_batch_size`, `timeout`, `send_batch_max_size`) plays the same role.

**Missing memory_limiter processor.** High traffic or a slow backend grows Collector memory until the pod OOMKills and drops in-flight spans. Always place `memory_limiter` **first** in the pipeline; set `limit_mib` to ~80% of the container limit and `spike_limit_mib` to a soft fraction that triggers early GC.

```yaml
processors:
  memory_limiter:
    check_interval: 1s
    limit_mib: 512
    spike_limit_mib: 128
service:
  pipelines:
    traces:
      processors: [memory_limiter, <enrichment...>, <tail_sampling>, batch]
```

**Processor order.** Processors run in declaration order. Canonical order: `memory_limiter` → enrichment (`resource`, `attributes`) → filtering (`filter`, `transform`) → `tail_sampling` (if used) → `batch`. `batch` is always last; filter and normalize before sampling so decisions and metric labels see the cleaned attributes.

## Cardinality and cost

**Cardinality blowup from span-derived metric labels.** The metrics-generator span-metrics processor builds RED metrics (e.g. `traces_spanmetrics_calls_total`, `traces_spanmetrics_duration_seconds`) with labels taken from span attributes. If a label like `http.target` carries ids (`/orders/<uuid>`), every distinct URL becomes a new time series and cardinality explodes. Normalize ids and paths **before** they become labels — rewrite `/orders/<id>` with the Collector `transform`/`attributes` processor — and restrict the generated dimensions to a low-cardinality allowlist (method, status, service). Never label on ids, id-bearing paths, tokens, or session ids.

## Double instrumentation and conflicts

**Error tracker + OTel both creating spans.** If an error-tracking/APM SDK auto-instruments HTTP and database calls while OTel also instruments them, both emit spans for the same operations — doubling overhead and producing duplicate, conflicting trees. Let OTel own tracing: disable the error tracker's performance/APM/tracing module (set its trace sample rate to 0) and keep it only for exception capture. If it offers an OTel span processor, route OTel spans through that instead of running two tracers.

## Tempo backend gotchas

- **Default block retention is 14 days.** New installs default to `compactor.block_retention: 336h`; a high-volume service can fill object storage inside that window. Set retention explicitly before production based on your incident-response window.
- **Retention deletion can fail under an object-storage prefix.** In some versions, configured retention does not delete objects when a storage prefix is set, so storage grows unbounded. Add an object-storage lifecycle policy that deletes objects 1–2 days after Tempo's retention window as a safety net, and alert on object-count growth.
- **TraceQL regex is anchored.** `=~` and `!~` anchor at both ends, so `{ span.http.target =~ "/api/orders" }` matches only the exact string. Use `.*` for substring: `{ span.http.target =~ ".*/api/orders.*" }`.
- **Prefer trace-level intrinsics.** Trace-level intrinsics (`trace:duration`, `trace:rootService`) are far more performant than span-level (`span:duration`, `span:status`) because Tempo indexes trace metadata. Query `{ trace:duration > 2s }` rather than scanning spans where possible.
- **Streaming queries require gRPC.** Tempo's streaming search/metrics API uses gRPC; set `stream_over_http_enabled: true` and point the Grafana datasource at Tempo's gRPC port (default 9095), or terminate behind an ingress that supports HTTP/2.

## References

- [instrumentation.md](instrumentation.md) — SDK init order, the env-var contract, resource/semantic conventions, span processors, and auto/manual/framework instrumentation + W3C propagation
- [collector.md](collector.md) — the OTel Collector pipeline, agent/gateway topology, the core processors, the OTLP-to-Tempo exporter, and the loadbalancing exporter
- [sampling.md](sampling.md) — head vs tail sampling, the hybrid production pattern, decision_wait tuning, and the loadbalancing exporter
- [tempo.md](tempo.md) — Tempo architecture, OTLP ingest, storage/retention/compaction, TraceQL, and the metrics-generator
- [correlation.md](correlation.md) — trace-to-logs / trace-to-metrics / metrics-to-traces (exemplars) and service graphs

## Upstream (authoritative)

These notes are re-derived concisely in this kit's idiom from public, authoritative docs: the [OpenTelemetry SDK configuration spec](https://opentelemetry.io/docs/specs/otel/configuration/sdk-environment-variables/), the [OTLP exporter spec](https://opentelemetry.io/docs/specs/otel/protocol/exporter/), the [OTel Collector docs](https://opentelemetry.io/docs/collector/), [context propagation](https://opentelemetry.io/docs/concepts/context-propagation/) and [sampling](https://opentelemetry.io/docs/concepts/sampling/) concepts, the [W3C Trace Context](https://www.w3.org/TR/trace-context/) standard, and the [Grafana Tempo architecture](https://grafana.com/docs/tempo/latest/introduction/architecture/), [configuration](https://grafana.com/docs/tempo/latest/configuration/), [TraceQL](https://grafana.com/docs/tempo/latest/traceql/), and [metrics-generator](https://grafana.com/docs/tempo/latest/metrics-from-traces/metrics-generator/) references. When these notes disagree with upstream OpenTelemetry or Grafana Tempo docs, trust upstream and update this file.

## Related

- Policy: `.claude/rules/devops-observability.md` — the language-neutral observability ruleset these patterns implement
- Role: `observability-engineer` — the agent that applies them
- Sibling **observability-and-logging** — app-side observability for a single stack: structured logging, PII/secret redaction, error-tracker setup, RED metrics, health probes, and framework auto-instrumentation wiring
- Sibling **langfuse-llm-tracing** — tracing LLM/model calls (prompts, tokens, cost)