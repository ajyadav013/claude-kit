# Correlating Logs, Metrics, and Traces

Signals join into one investigation only when they share keys: a latency spike (metric) pivots to an example slow trace, which pivots to the error logs for that exact request. The keys are a propagated `trace_id`/`span_id` and a consistent set of resource attributes. Get those right and the metric→trace→log pivot is one click; get them wrong and every incident becomes three disconnected tools and guesswork.

> **Sibling boundary.** This file is the language-neutral pipeline-and-backend view: how the three signals join through trace context, exemplars, and Tempo's metrics-generator. The app-side wiring for *one* stack — structured logging, PII/secret redaction, error-tracker SDK setup, RED metrics, health probes, and per-library OTel auto-instrumentation — lives in the **observability-and-logging** sibling. Tracing LLM/model calls (prompts, tokens, cost) lives in **langfuse-llm-tracing**. Use this file for the correlation mechanics; reach for a sibling for the concrete app/SDK code.

## When to use

- Wiring `trace_id`/`span_id` into structured logs so Grafana can pivot logs↔traces
- Configuring exemplars so a histogram spike links to an example trace
- Deriving RED metrics and service graphs from spans (Tempo metrics-generator)
- Defining the resource attributes that all three signals must share to join
- Making an error tracker coexist with OpenTelemetry without double-instrumenting traces
- Keeping cardinality bounded when span attributes become metric labels

## The three signals and why correlation matters

| Signal | What it is | Strength | Blind spot |
|--------|-----------|----------|------------|
| **Logs** | Discrete events with full context | Detail, exact error text | No request flow on their own |
| **Metrics** | Aggregated rates/latencies over time | Cheap, alertable, dashboardable | Hide individual outliers |
| **Traces** | The request path across services | Causality, where time went | No exception detail without logs |

Correlation closes each blind spot. An elevated error-rate panel pivots through an **exemplar** to the failing trace, then through that span's `trace_id` to the exception log. A trace showing a slow dependency span pivots to metrics that prove it is systemic, not a one-off. Every signal carries the same join keys, so the manual cross-reference disappears.

## Logs→traces: stamp `trace_id`/`span_id` on every structured log line

The bridge from logs to traces is writing the active `trace_id` and `span_id` as fields on every structured log line. When a log statement runs inside an active span, read the current span context and emit those two fields next to `timestamp`, `level`, and `message`. Use identical field names in every service.

**W3C Trace Context identifiers.** `trace_id` is a 16-byte (32-hex-char) trace identifier; `span_id` is an 8-byte (16-hex-char) span identifier. These are the same values carried in the `traceparent` header and the keys Tempo indexes on. Most OTel logging integrations inject them automatically once a log/trace bridge is enabled; if your stack logs manually, read them from the current span context.

**Grafana Loki↔Tempo pivot.**

- **Trace → logs:** in the Tempo data source, configure *trace-to-logs* — pick the logs data source (Loki, Elasticsearch, Splunk, OpenSearch, Google Cloud Logging, …) and map span/resource attributes to log-query tags via the `__tags` custom variable. A logs button appears on each span.
- **Logs → trace:** in the Loki data source, configure a *derived field* with a regex that extracts `trace_id` from the log line and points it at the Tempo `TraceID` field. A Tempo button appears on matching log lines and opens the full trace.

Example structured log line (format is illustrative; the field names and the two IDs are the load-bearing part):

```json
{
  "timestamp": "2026-06-20T14:32:18.501Z",
  "level": "error",
  "message": "upstream payment provider timeout",
  "trace_id": "a1b2c3d4e5f6789012345678abcdef01",
  "span_id": "1234567890abcdef",
  "service.name": "payment-gateway",
  "http.request.method": "POST",
  "http.route": "/v1/charge"
}
```

The same `service.name` resource attribute appears across logs, metrics, and traces. Consistent resource attributes (below) are what let the three sides join.

## Metrics→traces: exemplars on histogram metrics

An **exemplar** attaches a `trace_id` to a specific bucket observation in a histogram, creating a reverse link from a metric data point to an example trace that produced it. When a high-latency request finishes, the metrics-generator records the histogram bucket increment and stores that request's trace ID as an exemplar. Grafana renders exemplars as dots on a histogram panel; clicking a dot opens the trace in Tempo.

Tempo's **metrics-generator** runs the processors that derive these metrics from spans and a built-in Prometheus Agent that `remote_write`s them to any Prometheus-compatible store (Mimir, Thanos, Grafana Cloud, plain Prometheus). The collection interval is `metrics_generator.registry.collection_interval`.

Example metrics-generator config (Tempo):

```yaml
metrics_generator:
  processors: [span-metrics, service-graphs]
  registry:
    collection_interval: 15s
  storage:
    path: /var/tempo/generator/wal
    remote_write:
      - url: http://prometheus:9090/api/v1/write
        send_exemplars: true
```

`send_exemplars: true` enables exemplar writes on the histograms. With multitenancy, the `X-Scope-OrgID` header is forwarded to `remote_write` unless `remote_write_add_org_id_header: false`. Grafana detects exemplars automatically when the Prometheus data source is linked to Tempo via *trace-to-metrics*.

## Traces→metrics: service graphs and span metrics (RED from spans)

Two metrics-generator processors turn spans into metrics, so you get RED dashboards and a topology view without the application emitting any metrics of its own. Because both read the same spans already sent to Tempo, this is **not** double instrumentation.

**Span metrics** (`span-metrics` processor) emit the classic RED series per service / span name / span kind:

- `traces_spanmetrics_calls_total` — counter
- `traces_spanmetrics_duration_seconds` — histogram (carries exemplars when enabled)

**Service graphs** (`service-graphs` processor) analyze parent↔child span pairs to build a service topology. Each edge is requests from a `client` service to a `server` service, labeled with `connection_type` (`virtual_node` for an uninstrumented external dependency, unset for instrumented peers):

- `traces_service_graph_request_total`
- `traces_service_graph_request_failed_total`
- `traces_service_graph_request_server_seconds` — histogram
- `traces_service_graph_request_client_seconds` — histogram

The gap between the client and server histograms isolates network plus serialization latency. The processor also exposes `traces_service_graph_unpaired_spans_total` and `traces_service_graph_dropped_spans_total`, useful when traces look incomplete.

**Grafana Service Graph view.** The Tempo data source's Service Graph query mode renders these metrics in Explore — nodes are services, edge thickness tracks request rate, color tracks error rate, and clicking an edge filters to the traces between those two services.

**Collector connector caveat.** If you derive span metrics with the OpenTelemetry **Collector** `spanmetrics` connector instead of Tempo's metrics-generator, the duration metric is named `traces_spanmetrics_duration_seconds_*`, which the Grafana Service Graph/APM views do not pick up out of the box — they expect `traces_spanmetrics_latency_*`. Add a `metricstransform` processor to rename it for compatibility.

## Consistent resource attributes across logs/metrics/traces

The join key across all three signals is the **resource** — the entity producing telemetry (service instance, host, container, pod). Resource attributes MUST be identical across the logs, metrics, and traces emitted by the same instance, or queries will not join them in Grafana.

| Attribute | Why it matters |
|-----------|----------------|
| `service.name` | The single most important attribute. If unset, SDKs fall back to `unknown_service:<executable>`, fragmenting one service across many names. Every instance of a horizontally-scaled service MUST share the same value. |
| `service.namespace` | Logical grouping (e.g. `payment`, `inventory`). |
| `service.version` | Compare behavior across releases. |
| `deployment.environment` | `production` / `staging` / `dev`. |
| `service.instance.id` | Unique instance (pod name, container ID). |
| `k8s.pod.name`, `k8s.namespace.name`, `k8s.deployment.name` | Kubernetes filtering. |
| `host.name`, `cloud.provider`, `cloud.region` | Infra context. |

Set these once for the process, in a language-neutral way: `OTEL_SERVICE_NAME` for the name and `OTEL_RESOURCE_ATTRIBUTES` (comma-separated `key=value`) for the rest, or via your SDK's resource builder. `OTEL_SERVICE_NAME` takes precedence over a `service.name` set inside `OTEL_RESOURCE_ATTRIBUTES`. Prefer **semantic-convention** attribute names over custom ones so backends can auto-build dashboards. Inconsistency breaks correlation: if logs say `service.name=payment-api` while traces say `service.name=payment`, nothing joins.

**TraceQL** filters traces by resource attributes with the `resource.` prefix:

```traceql
{ resource.service.name = "payment-gateway" && resource.deployment.environment = "production" }
```

Loki filters logs by the same attributes when they are configured as labels, and Prometheus filters the derived metrics by labels the metrics-generator copies from resource attributes — so the same attribute name works on all three sides.

## Error-tracker + OTel coexistence: disable the error tracker's own tracing (sample 0)

Error-tracking products commonly bundle their own distributed tracing. Running that tracer **and** OpenTelemetry at once produces two overlapping trace trees, confuses Grafana correlation, and doubles ingestion cost.

**Resolution:** set the error tracker's trace sample rate to **0** (or disable its tracing integration entirely) and let OpenTelemetry own distributed tracing. Keep the error tracker for what it is good at — exception capture, grouping, and alerting. To stay correlated, attach the active OTel span's `trace_id`/`span_id` to each captured error event so you can jump from an error group to the trace in Tempo:

- Read the current span context from the OTel API.
- Format the IDs as lower-case hex: `trace_id` to 32 chars, `span_id` to 16 chars.
- Add them as context/tags on the error event (most error SDKs expose a "set context" or "set tag" call).

Keep this vendor- and language-neutral; the concrete SDK init for a specific stack lives in the **observability-and-logging** sibling. Some error trackers ship a first-party OTel integration that links both directions automatically — prefer that when available and consult vendor docs.

## Cardinality discipline when deriving metrics/labels from spans

Span-derived metrics copy span attributes into metric labels. High-cardinality attributes — user IDs, request IDs, session tokens, raw paths with IDs embedded — turn into unbounded label cardinality that exhausts the metric store and slows queries. A million unique `url.path` values become a million time series.

| Approach | Cost / use |
|----------|-----------|
| **Span attribute** (kept in Tempo) | Cheap object-storage bytes; queryable via TraceQL. Put high-cardinality identifiers here. |
| **Metric label** (in Prometheus) | Active series, WAL, query overhead — orders of magnitude pricier. Keep bounded (hundreds of values per label). |

Mitigations, in order:

1. **Normalize before the generator.** Use the Collector `attributes` processor to rewrite IDs into templates (`/users/12345` → `/users/{id}`) and drop tokens/correlation IDs not needed for grouping.
2. **Allowlist dimensions.** Configure `span-metrics` `dimensions` to copy only low-cardinality attributes:

   ```yaml
   metrics_generator:
     processors: [span-metrics]
     processor:
       span_metrics:
         dimensions:
           - name: service.name
           - name: http.request.method
           - name: http.response.status_code
   ```

3. **Filter, don't label.** Store high-cardinality identifiers as span attributes and filter on them in TraceQL; never promote them to metric labels.

**Tempo version note.** The `local-blocks` processor was removed from the metrics-generator in recent Tempo; remove any `local-blocks` config entry or startup fails. Use `span-metrics` and `service-graphs`.

## References

- [instrumentation.md](instrumentation.md) — SDK init order, the env-var contract, resource/semantic conventions, span processors, and auto/manual/framework instrumentation + W3C propagation
- [collector.md](collector.md) — the OTel Collector pipeline, agent/gateway topology, the core processors, the OTLP-to-Tempo exporter, and the loadbalancing exporter
- [sampling.md](sampling.md) — head vs tail sampling, the hybrid production pattern, decision_wait tuning, and the loadbalancing exporter
- [tempo.md](tempo.md) — Tempo architecture, OTLP ingest, storage/retention/compaction, TraceQL, and the metrics-generator
- [gotchas.md](gotchas.md) — the highest-leverage failure modes and their fixes

## Related

- **Rule:** `.claude/rules/devops-observability.md`
- **Agent:** observability-engineer
- **Siblings:** observability-and-logging (app-side logging/redaction/error-tracker/RED-metrics/health for a single stack), langfuse-llm-tracing (LLM/model-call tracing)

---

**Provenance.** Derived from [OpenTelemetry Semantic Conventions](https://opentelemetry.io/docs/specs/semconv/), [OTel Collector processors](https://opentelemetry.io/docs/collector/components/processor/), [Grafana Tempo metrics-generator](https://grafana.com/docs/tempo/latest/metrics-from-traces/metrics-generator/), [Grafana Tempo service graphs](https://grafana.com/docs/tempo/latest/metrics-from-traces/service_graphs/), [Grafana Tempo data source / trace-to-logs](https://grafana.com/docs/grafana/latest/datasources/tempo/configure-tempo-data-source/), and [W3C Trace Context](https://www.w3.org/TR/trace-context/). When upstream docs disagree with this snapshot, trust upstream — it evolves faster than this file.