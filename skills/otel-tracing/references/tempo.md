# Grafana Tempo: Object-Storage Trace Backend

Tempo is a horizontally scalable distributed-tracing backend that stores traces in object storage (S3, GCS, Azure Blob) and is cheap because it does **not** index every span attribute. It accepts OTLP natively and is queried with TraceQL. The cost trade-off is explicit: instead of building an Elasticsearch-style inverted index over all attributes, Tempo organizes data by time and trace ID and uses bloom filters plus a columnar block format. Storage cost stays roughly linear with trace volume and you avoid index explosion on high-cardinality systems; in exchange, ad-hoc queries over arbitrary attributes are slower than on a fully-indexed backend, which TraceQL mitigates by pushing predicate evaluation down to block scanning.

> Scope: this is a reference for the **otel-tracing** skill — the language-neutral distributed-tracing pipeline and Tempo backend (OTLP/Collector/Tempo ingest, storage, TraceQL, trace↔logs↔metrics correlation). For the app-side observability setup (structured logging, PII/secret redaction, Sentry, app RED metrics, liveness/readiness, framework OTEL auto-instrumentation) use the sibling **observability-and-logging**. For tracing LLM/model calls (prompts, tokens, cost) use **langfuse-llm-tracing**. The neutral policy is `.claude/rules/devops-observability.md` and the role is the **observability-engineer** agent; this file is the concrete how-to under them.

## When to use

- You need to stand up or wire a trace backend that ingests OTLP from your service or the project's collector.
- You are choosing storage, retention, and compaction settings and want to bound storage cost.
- You are writing TraceQL to find traces by `service.name`, span attributes, duration, or status.
- You want RED metrics and service graphs derived from traces (metrics-generator) with exemplars linking metrics back to traces.
- You are wiring the Grafana Tempo datasource for trace-to-logs / trace-to-metrics pivoting in Explore.
- You want to plug into an existing cluster Tempo/Grafana rather than run a parallel stack.

## Architecture and ingest flow

Tempo's **distributor** exposes OTLP receivers on **4317** (gRPC) and **4318** (HTTP), built on the OpenTelemetry Collector receiver layer, so the protocol your instrumented service or collector speaks is identical to what Tempo expects. The distributor:

1. Validates incoming spans against ingestion limits (attribute size, trace size, rate).
2. Shards by hashing the trace ID so all spans of a trace route to the same downstream partition.
3. Forwards the spans on to the ingesters for block building.

The **ingester** organizes spans into time-windowed blocks and flushes them to object storage; recent, not-yet-flushed traces are served from the ingesters. The **compactor** merges small blocks into larger ones and expires data past retention. The **querier** (behind a **query-frontend**) reads bloom filters and indexes from object storage to locate traces within blocks and evaluates TraceQL predicates against the columnar block format. Newer Tempo versions add an optional Kafka-based ingest path with a dedicated block-builder component for higher-durability ingestion; it is opt-in, so consult your version's docs before relying on it.

## OTLP endpoint and the `/v1/traces` path nuance

Tempo accepts OTLP with no special exporter setup beyond the endpoint. The protocol/port/path contract:

| Protocol | Default port | Path behavior |
|----------|-------------|---------------|
| OTLP/gRPC | 4317 | No path suffix; endpoint is `tempo-distributor:4317` |
| OTLP/HTTP (`http/protobuf`) | 4318 | Requires `/v1/traces`; endpoint is `http://tempo-distributor:4318/v1/traces` |
| OTLP/HTTP (`http/json`) | 4318 | Requires `/v1/traces`; same as above |

OTLP/HTTP multiplexes signals by path: `/v1/traces`, `/v1/metrics`, `/v1/logs` share the port. Get the protocol/port pairing right (4317↔gRPC, 4318↔HTTP); a mismatch is a common cause of silent failure. SDK behavior around the path differs: setting `OTEL_EXPORTER_OTLP_ENDPOINT=http://tempo-distributor:4318` lets the SDK append `/v1/traces` for HTTP, whereas `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` is the full signal-specific URL and is used verbatim — set one or the other, not both. Verify with debug logging.

Collector exporting to Tempo over gRPC:

```yaml
exporters:
  otlp/tempo:
    endpoint: tempo-distributor:4317   # gRPC, no path
    tls:
      insecure: true                   # plain gRPC; common pitfall to omit
processors:
  batch:
    timeout: 10s
service:
  pipelines:
    traces:
      receivers: [otlp]
      processors: [batch]
      exporters: [otlp/tempo]
```

Over HTTP the collector's OTLP exporter appends `/v1/traces` automatically:

```yaml
exporters:
  otlp/tempo:
    endpoint: http://tempo-distributor:4318
    tls:
      insecure: true
```

If Tempo is unreachable, check `tls.insecure: true` for plain gRPC and that the collector can resolve the Tempo hostname.

## Storage, retention, and compaction

Tempo stores traces in **object storage** (S3, GCS, Azure Blob, or local filesystem for development only). The backend is set via `storage.trace.backend`:

| Backend | Key configuration |
|---------|-------------------|
| S3 | `bucket`, `endpoint`, `region`, `access_key`, `secret_key`, `part_size` (default 5MB) |
| GCS | `bucket_name`, `chunk_buffer_size` (default 10MB), `max_retries` (default 3) |
| Azure | `container_name`, `storage_account_name`, `max_buffers` (default 4) |
| Local | `path` (development only; not durable) |

**Retention** controls how long traces are queryable:

- `compaction.block_retention`: default **336h (14 days)**. Blocks older than this are deleted by the compactor.
- `compaction.compacted_block_retention`: default **1h**. Source blocks are kept briefly after compaction for rollback.
- `compaction.empty_tenant_deletion_age`: default **12h**. Tenants with no data are removed after this.

The 14-day default is intentionally short to avoid surprise storage costs on new installs. Define a retention policy before production; 30 days is a reasonable upper bound for post-incident debugging. Long retention with a large block list also raises object-storage listing pressure.

**Compaction** merges small blocks into larger ones to cut object count and improve query performance:

- `compaction.compaction_window`: default **1h**. Blocks in the same window are eligible together.
- `compaction.max_block_bytes`: default ~**100 GB**. Max compacted-block size.
- `compaction.max_input_blocks`: default **4**. Max blocks merged per compaction.
- `compaction.min_input_blocks`: default **2**. Min blocks to trigger compaction.
- `compaction.compaction_cycle`: default **30s**. How often the compactor runs.

| | Issue |
|---|---|
| 🚩 | Retention deletion can fail under some S3 prefix configurations, leaving objects past retention. Set an **object-storage lifecycle policy** that deletes objects 1–2 days after Tempo's retention as the fix. |
| 🚩 | A compactor/ingester crash mid-block can orphan objects Tempo no longer tracks. The same lifecycle policy is the safety net. |
| ✅ | Treat the lifecycle policy as required operational hardening, not optional. |

## TraceQL: querying without full indexing

TraceQL filters on **resource attributes** (`resource.service.name`, `resource.deployment.environment`), **span attributes** (`span.http.method`, `span.db.system`), and **intrinsics** (`duration`, `status`, `kind`).

A query has three parts:

1. **Span selection**: `{ span.http.method = "POST" && span.http.status_code >= 400 }`
2. **Structural operators** (optional): `>>` descendant, `<<` ancestor, `>` child, `<` parent, `~` sibling
3. **Aggregation** (optional): `| count() > 100`, `| avg(span:duration) > 1s`

| Category | Operators | Example |
|----------|-----------|---------|
| Comparison | `=`, `!=`, `>`, `>=`, `<`, `<=` | `span:duration >= 500ms` |
| Regex | `=~`, `!~` (negated) | `resource.service.name =~ ".*-api"` |
| Logical | `&&`, `\|\|` | `span.http.method = "GET" && span.http.status_code = 200` |
| Aggregators | `count`, `avg`, `max`, `min`, `sum`, `rate` | `\| avg(span:duration)` |

| | Note |
|---|---|
| 🚩 | TraceQL regex (`=~`, `!~`) is **anchored at both ends**. `resource.service.name =~ "api"` will NOT match `payment-api`; use `.*api.*` for substring matching. |
| ✅ | Prefer **trace-level** intrinsics over span-level when possible. |

Trace-level intrinsics (`trace:duration`, `trace:rootService`, `trace:rootName`) are significantly faster than span-level (`span:duration`, `span:status`, `span:kind`, `span:name`, `span:id`), which require scanning spans within each trace. Query latency can differ by an order of magnitude:

```traceql
# Fast: trace-level duration filter
{ trace:duration >= 1s }

# Slower: span-level duration filter (scans spans)
{ span:duration >= 500ms }
```

Use span-level intrinsics only for fine-grained span selection (e.g. finding traces where one downstream call is slow).

Examples:

```traceql
# All traces for a service over 1s
{ resource.service.name = "payment-api" && trace:duration >= 1s }

# Any span returned a 5xx
{ span.http.status_code >= 500 }

# A database query took more than 200ms
{ span.db.system = "postgresql" && span:duration >= 200ms }

# A child call to a specific service failed
{ resource.service.name = "order-api" }
  >> { resource.service.name = "inventory-api" && span:status = error }

# Count by status code for a service
{ resource.service.name = "payment-api" } | count() by (span.http.status_code)
```

## Metrics from traces: service graphs and RED metrics

The **metrics-generator** derives metrics from ingested traces, giving RED (Rate, Errors, Duration) dashboards and dependency graphs without adding metric instrumentation to application code. Two processors produce complementary sets.

**Span metrics processor** — per-service RED metrics:

- `traces_spanmetrics_calls_total` (counter): span count, labeled by `service`, `span_name`, `span_kind`, `status_code`.
- `traces_spanmetrics_duration_seconds` (histogram): duration distribution, same labels. Buckets via `metrics_generator.processors.span_metrics.histogram_buckets`.

**Service graphs processor** — analyzes parent/child span relationships (edges = requests between services):

- `traces_service_graph_request_total` (counter): requests between services, labeled `client`, `server`, `connection_type`.
- `traces_service_graph_request_failed_total` (counter): failed requests, same labels.
- `traces_service_graph_request_server_seconds` (histogram): server-side latency.
- `traces_service_graph_request_client_seconds` (histogram): client-side latency (client span start to server span end, includes network).
- Diagnostics: `traces_service_graph_unpaired_spans_total` (no matching parent/child) and `traces_service_graph_dropped_spans_total` (buffer limits).

### Export and exemplars

The metrics-generator runs a **Prometheus Agent** that `remote_write`s to any Prometheus-compatible store (Prometheus, Mimir, Thanos, Cortex):

```yaml
metrics_generator:
  registry:
    collection_interval: 15s
  storage:
    path: /var/tempo/wal
    remote_write:
      - url: http://prometheus:9090/api/v1/write
        send_exemplars: true
```

**Exemplars** embed trace IDs in histogram samples, creating a **metrics-to-traces** link: click an exemplar on a latency graph to jump to an example trace. Requires (1) the metrics-generator to emit exemplars (`send_exemplars: true`), (2) the receiving store to ingest them, and (3) Grafana with both Tempo and Prometheus datasources to resolve the trace ID.

| | Note |
|---|---|
| 🚩 | In multi-tenant setups the metrics-generator forwards `X-Scope-OrgID` to `remote_write` by default. Set `remote_write_add_org_id_header: false` if the backend does not support tenant isolation. |
| 🚩 | OTel Collector's spanmetrics connector emits `traces_spanmetrics_duration_seconds_*`, which some Grafana views expect as `traces_spanmetrics_latency_*`; rename for out-of-box compatibility. |
| 🚩 | High span-metrics cardinality: 100 routes × 10 status codes × 5 kinds = 5,000 series per service. Normalize high-cardinality attributes (replace IDs/UUIDs) before they become labels. |

## Grafana datasource: trace-to-logs and trace-to-metrics

The Grafana Tempo datasource connects traces to logs and metrics for cross-signal pivoting.

| Setting | Value | Notes |
|---------|-------|-------|
| URL | `http://tempo:3200` (self-managed) | HTTP 3200, gRPC 9095 |
| Authentication | Basic auth, forward OAuth, or none | Cloud: `https://tempo-<REGION>.grafana.net/tempo` |
| TLS | Client cert, CA cert, skip verify | Required for external/cloud Tempo |

### Trace-to-logs

Links spans to log lines in Loki (or Elasticsearch, Splunk, OpenSearch, Google Cloud Logging). The datasource injects a `__tags` variable of span attributes that you map to log labels:

1. Select the logs datasource (e.g. Loki).
2. Map tags to labels: `service.name` → `service`, `span.id` → `span_id`.
3. Optionally time-shift the log query ±1 minute around the span to catch adjacent lines.

The resulting link runs a query such as:

```logql
{service="payment-api"} |= "span_id=abc123"
```

This requires your service to stamp `trace_id` and `span_id` onto every structured log line — the app-side setup is the **observability-and-logging** sibling's job; here the datasource wiring completes the circuit. The reverse (logs-to-traces) uses Loki derived fields.

### Trace-to-metrics

Links spans to Prometheus queries via injected variables `__span.name`, `__span.spanId`, `__span.traceId`, `__span.duration`, `__trace.traceId`, `__trace.duration`:

```promql
rate(traces_spanmetrics_calls_total{
  service="payment-api",
  span_name="${__span.name}",
  status_code=~"5.."
}[5m])
```

The reverse, **metrics-to-traces**, uses exemplars (above): Grafana detects the embedded trace ID and renders a "View trace" link.

### Query editor in Explore

| Mode | Use |
|------|-----|
| Search (query builder) | Dropdown filters for service name, span name, duration, status; generates TraceQL under the hood |
| TraceQL (code editor) | Raw TraceQL with autocomplete; complex queries, aggregations, structural operators |
| Service Graph | Visual RED view from service-graph metrics: request rate, error rate, latency between services |

Enable `stream_over_http_enabled: true` in Tempo to stream search results over the gRPC streaming API as they are found, improving perceived latency on large queries. HTTP-only setups do not stream.

## Deployment modes and reuse-first

| Mode | Fit | Architecture | Scaling |
|------|-----|--------------|---------|
| Monolithic | Simple, single-tenant, low–medium volume | Single binary (`-target=all`) | Vertical (more CPU/RAM) |
| Microservices | Large-scale, multi-tenant, high volume | Per-component binaries (`-target=distributor`, `-target=querier`, …) | Horizontal per component |

Classic microservices mode runs the components as independently-scaled binaries that communicate over gRPC; no message queue is required. Newer Tempo versions offer an optional Kafka-based ingest path for higher-durability ingestion — it is opt-in, not a prerequisite for running microservices mode. Check your Tempo version's documentation before assuming either topology.

**Reuse-first**: before deploying a new Tempo instance, check whether your cluster or organization already runs a shared Tempo/Grafana/Prometheus stack. Plugging into the existing stack removes duplicate compactor/querier maintenance and centralizes trace visibility; multi-tenancy (`X-Scope-OrgID`) isolates teams on one instance. If deploying fresh:

1. Start **monolithic** unless you have evidence of scale (sustained high span rate, multi-tenant isolation).
2. Use object storage from day one; local storage is not durable.
3. Set a bucket lifecycle policy deleting objects 1–2 days after retention (orphan safety net).
4. Set `compaction.block_retention` to your debugging need, not "as long as possible."
5. Enable the metrics-generator and wire `remote_write` to your Prometheus store for RED metrics and exemplars.

## References

- [instrumentation.md](instrumentation.md) — SDK init order, the env-var contract, resource/semantic conventions, span processors, and auto/manual/framework instrumentation + W3C propagation
- [collector.md](collector.md) — the OTel Collector pipeline, agent/gateway topology, the core processors, the OTLP-to-Tempo exporter, and the loadbalancing exporter
- [sampling.md](sampling.md) — head vs tail sampling, the hybrid production pattern, decision_wait tuning, and the loadbalancing exporter
- [correlation.md](correlation.md) — trace-to-logs / trace-to-metrics / metrics-to-traces (exemplars) and service graphs
- [gotchas.md](gotchas.md) — the highest-leverage failure modes and their fixes

## Provenance

Derived from the Grafana Tempo docs (grafana.com/docs/tempo), the Grafana datasource docs (grafana.com/docs/grafana), the OpenTelemetry docs (opentelemetry.io/docs), the OTLP specification, and the W3C Trace Context specification. This is a point-in-time snapshot; protocols, defaults, and best practices change. When upstream documentation disagrees with this file, trust upstream.

## Related

- `.claude/rules/devops-observability.md` — observability policy: structured logs, PII/secret redaction, metric/trace correlation, `service.name` requirement, sampling strategy, retention bounds.
- **observability-engineer** — agent role: ingest-pipeline setup, TraceQL query optimization, trace-to-logs/metrics wiring, retention/compaction tuning.
- **observability-and-logging** — sibling skill: app-side observability (structured logging, redaction, error tracking, app RED metrics, probes, framework OTEL auto-instrumentation). Use for instrumented-app config; this file covers the collector and Tempo backend.
- **langfuse-llm-tracing** — sibling skill: LLM/model-call tracing (prompts, tokens, cost). Use for AI/ML observability; this file covers distributed application tracing.