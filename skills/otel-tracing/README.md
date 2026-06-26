# otel-tracing

Language-neutral distributed tracing: model your system with the OpenTelemetry data model, ship spans through the OTLP/Collector pipeline into Grafana Tempo, sample smartly (head plus tail), propagate W3C context across services and queues, query with TraceQL, and correlate traces with logs and metrics. This skill is the concrete OpenTelemetry-plus-Tempo how-to for turning isolated spans into debuggable distributed request flows, independent of any single language or framework.

> **Boundary.** This skill owns the vendor-neutral tracing *pipeline* and *backend*: the OTel data model, OTLP protocol, Collector topology, sampling, propagation, the Tempo backend, and TraceQL. It does NOT cover app-side observability setup (structured logging, PII/secret redaction, error tracking, application RED metrics, health probes, framework auto-instrumentation wiring) — that is the sibling **observability-and-logging** — nor LLM/model-call tracing (prompts, tokens, cost) — that is **langfuse-llm-tracing**. The neutral policy lives in `.claude/rules/devops-observability.md` and the role is the **observability-engineer** agent; this skill is their concrete OTel+Tempo reference.

## What's inside

| File | Covers |
|------|--------|
| `SKILL.md` | The overview: OTel data model, the standard env-var contract, the signal pipeline, instrumentation principles (env-gated/fail-safe init, auto vs manual vs framework interceptors, one-trace-tree propagation), sampling (head + tail), Tempo essentials, TraceQL, and trace/logs/metrics correlation. |
| `references/instrumentation.md` | The data model and resource semantic conventions, SDK init order (Resource → Exporter → SpanProcessor → TracerProvider), the env-gated/fail-safe/idempotent/shutdown-flush pattern, the full env-var contract, auto vs manual vs framework-interceptor instrumentation, and W3C context propagation across async/queue boundaries. |
| `references/collector.md` | When to run the OTel Collector (and when to export app→Tempo directly), the receiver→processor→exporter pipeline, agent vs gateway topology, the core processors (`memory_limiter`, `batch`, `resource`/`attributes`, `tail_sampling`), the OTLP exporter to Tempo, and the loadbalancing exporter that tail sampling requires. |
| `references/sampling.md` | Head sampling (parent-based + trace-id-ratio in the SDK) vs tail sampling (`tail_sampling` in the Collector), the hybrid production pattern (keep all errors + slow traces + a baseline %), consistent sampling-decision propagation, and the cost of 100% sampling. |
| `references/tempo.md` | Tempo as an object-storage trace backend: native OTLP ingest (4317/4318) and the `/v1/traces` path nuance, the distributor/ingester/querier/compactor roles, deployment modes, retention/compaction, TraceQL query patterns, and the metrics-generator (span metrics + service graphs → Prometheus). |
| `references/correlation.md` | Binding the three signals: `trace_id`/`span_id` on every log line (logs→traces), exemplars (metrics→traces), service graphs and span metrics (traces→metrics), consistent resource attributes so they join, and the error-tracker/OTel coexistence rule (avoid double-tracing). |
| `references/gotchas.md` | The highest-leverage failure modes and fixes: endpoint/port/path traps, a legacy exporter overriding OTLP, fail-safe init, lost context propagation across queues, missing `service.name`, over-sampling cost, batch-queue overflow, cardinality blowups, and double-tracing. |

## Provenance

Re-derived (not vendored) from public, authoritative documentation: OpenTelemetry.io (SDK configuration, OTLP exporter, Collector architecture, semantic conventions, context propagation, sampling), the W3C Trace Context specification, and Grafana Tempo documentation (architecture, TraceQL, metrics-generator, datasource configuration). Vendor-neutral; no proprietary content. When this skill and the upstream docs disagree, trust upstream.

## When to use

- **Designing the pipeline** — where to run the Collector, agent vs gateway topology, how to order receivers/processors/exporters.
- **Debugging missing or fragmented traces** — TracerProvider init order, context propagation across async/queue boundaries, `tail_sampling` without a loadbalancing exporter, endpoint/port/path mismatches.
- **Choosing sampling** — head-based in the SDK, tail-based (error/latency-aware) in the Collector, and the hybrid production pattern: SDKs use `parentbased_always_on` to preserve context, the Collector applies `tail_sampling` (100% errors, 100% latency outliers, low-rate probabilistic for the rest).
- **Configuring Tempo** — OTLP receivers, trace-ID sharding, retention/compaction, object storage, and the metrics-generator (RED metrics, service graphs).
- **Writing TraceQL** — filtering by service, span attribute, duration, status; navigating structure with descendant/ancestor operators; preferring trace-level intrinsics.
- **Correlating signals** — stamping `trace_id`/`span_id` onto log lines, configuring trace-to-logs in Grafana, enabling exemplars, and querying across traces, logs, and metrics.

Do NOT reach here for app-side observability code (that is **observability-and-logging**) or LLM tracing (that is **langfuse-llm-tracing**).

## Boundary vs siblings

| Skill | Owns | Scope |
|-------|------|-------|
| **otel-tracing** (this) | OTel data model, OTLP/Collector/Tempo pipeline, sampling, W3C propagation, TraceQL, signal correlation | Language-neutral, backend-focused |
| **observability-and-logging** | App-side instrumentation: framework/library auto-instrumentation wiring, structured logging, PII/secret redaction, error tracking, application RED metrics, health checks | Stack-specific, app-focused |
| **langfuse-llm-tracing** | LLM observability: prompt/completion/token/cost tracking, model-call hierarchies | Model-call-focused |

When a task crosses the line — for example "add tracing to a service" — **observability-and-logging** wires the app-side auto-instrumentation and sets `OTEL_EXPORTER_OTLP_ENDPOINT`; **otel-tracing** designs the Collector pipeline and Tempo backend that receive the spans. The policy governing all three lives in `.claude/rules/devops-observability.md` (honesty, fail-safe init, reuse-first cluster integration, PII redaction).

## Related

- **Agent:** `observability-engineer` (owns the tracing pipeline, sampling, Tempo, correlation).
- **Rules:** `.claude/rules/devops-observability.md` (policy), `.claude/rules/agent-resilience.md` (fail-safe init).
- **Sibling skills:** `observability-and-logging` (app-side), `langfuse-llm-tracing` (LLM-specific).
- **Deep dive:** `SKILL.md` — the overview, with the six `references/` files above.
