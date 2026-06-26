# The OpenTelemetry Collector

The Collector is a vendor-agnostic proxy that receives, processes, and exports telemetry. Put one between your services and the trace backend when you need buffering, enrichment, redaction, tail sampling, fan-out, or protocol translation in a single place that you can change without touching application code. Any OTLP-emitting service (any language) talks to it the same way; the wiring below is config, not code.

> **Sibling boundary.** This skill is the language-neutral tracing *pipeline* and Tempo *backend*: the OTLP -> Collector -> Tempo path, sampling, W3C context propagation, TraceQL, and trace<->logs<->metrics correlation. It does **not** cover the app-side observability setup (structured logging, PII/secret redaction in app code, Sentry, app RED metrics, liveness/readiness, and per-framework OTEL auto-instrumentation wiring) — that is `observability-and-logging`. It does **not** cover tracing LLM/model calls (prompts, tokens, cost) — that is `langfuse-llm-tracing`. The neutral policy lives in `.claude/rules/devops-observability.md` and the role is the `observability-engineer` agent; this is the concrete OTEL+Tempo how-to under them.

## When to use

- You want to swap or add a trace backend without redeploying services (decouple app from backend).
- Backends are sometimes slow or down and you need a queue + retry in front of them (buffer/retry).
- You need to add resource attributes (cluster, region, version) or strip sensitive ones (PII, secrets, SQL) before export (enrich/redact).
- You need tail-based sampling (keep all errors and slow traces, sample the rest) after traces complete.
- You need to fan out the same traces to multiple backends, or translate OTLP to a legacy protocol.

### When you can skip it

For a single backend with low volume, a service can export OTLP straight to Tempo's OTLP endpoint (4317 gRPC / 4318 HTTP) — one fewer hop and less to operate. Skip the Collector when **all** of these hold:

- One backend, no fan-out, no protocol translation.
- No tail sampling (parent-based head sampling in the SDK is enough).
- No central enrichment/redaction (resource attributes set in each service).
- Low span volume with a backend that tolerates bursts.

You can insert a Collector later without changing application code: the service still exports OTLP, now pointed at the Collector instead of Tempo.

## Pipeline model

The Collector moves telemetry through three stages:

```
receivers -> processors -> exporters
```

- **Receivers** ingest telemetry (OTLP, Jaeger, Zipkin, Prometheus).
- **Processors** transform, enrich, filter, or sample (memory_limiter, batch, resource, attributes, tail_sampling).
- **Exporters** send to backends (OTLP to Tempo, Prometheus remote_write, Jaeger).

A service pipeline wires them together:

```yaml
service:
  pipelines:
    traces:
      receivers: [otlp]
      processors: [memory_limiter, batch]
      exporters: [otlp/tempo]
```

Processor order matters: `memory_limiter` -> enrichment/redaction -> filtering/transformation -> `tail_sampling` -> `batch`.

## OTLP receiver

The OTLP receiver accepts traces (and metrics/logs) from services and from upstream Collectors. It listens on gRPC (4317) and HTTP (4318):

```yaml
receivers:
  otlp:
    protocols:
      grpc:
        endpoint: 0.0.0.0:4317
      http:
        endpoint: 0.0.0.0:4318
```

Protocol vs port:

| Protocol | Port | Path | SDK `OTEL_EXPORTER_OTLP_PROTOCOL` |
|---|---|---|---|
| OTLP/gRPC | 4317 | none | `grpc` |
| OTLP/HTTP | 4318 | appends `/v1/traces`, `/v1/metrics`, `/v1/logs` | `http/protobuf` (recommended) or `http/json` |

Services set `OTEL_EXPORTER_OTLP_ENDPOINT` to the base URL (e.g. `http://collector:4318`) and `OTEL_EXPORTER_OTLP_PROTOCOL`. For HTTP the SDK appends the signal path; do not double-append it. `http/protobuf` has the widest backend compatibility.

| 🚩 Pitfall | ✅ Fix |
|---|---|
| Port 4317 with `http/protobuf`, or 4318 with `grpc` (fails, often silently) | Align protocol and port: 4317 = gRPC, 4318 = HTTP |
| Including or omitting `/v1/traces` inconsistently for OTLP/HTTP | Give the SDK the base URL; let it append the signal path |
| Setting `http/json`/`http/protobuf` without checking backend support | Prefer `http/protobuf`; verify the backend speaks it |

## Core processors

### memory_limiter

Stops the Collector from growing unbounded and getting OOMKilled. It tracks RSS/heap and refuses data (or forces GC) before exhaustion:

```yaml
processors:
  memory_limiter:
    check_interval: 1s
    limit_mib: 512
    spike_limit_mib: 128
```

- `limit_mib`: hard limit; set to ~80% of container memory.
- `spike_limit_mib`: soft headroom; the limiter acts when usage crosses `limit_mib - spike_limit_mib` between checks.
- `check_interval`: how often to check (default 0 = disabled; use 1s).

Place `memory_limiter` **first** in the pipeline. Under high traffic or slow backends, an unprotected Collector OOMKills and drops data.

### batch

Groups telemetry before export to amortize network and backend write cost:

```yaml
processors:
  batch:
    send_batch_size: 4096
    timeout: 10s
    send_batch_max_size: 8192
```

- `send_batch_size`: export when this many spans accumulate (default 8192).
- `timeout`: max wait before flushing a partial batch (default 200ms).
- `send_batch_max_size`: hard cap on a single batch (default 0 = unlimited).

In high-throughput systems a 1s timeout creates many tiny batches that waste CPU and network; use 5-10s timeout with 4096-8192 batch size. Place `batch` **last** so it batches the final, transformed data, and always pair it with `memory_limiter`.

### resource and attributes (enrich / redact)

`resource` modifies resource attributes (service, host, container); `attributes` modifies span attributes:

```yaml
processors:
  resource:
    attributes:
      - key: deployment.environment
        value: production
        action: upsert
      - key: service.version
        from_attribute: app.version
        action: insert
  attributes:
    actions:
      - key: db.statement
        action: delete          # redact SQL to prevent PII leaks
      - key: user.id
        action: hash            # de-identify high-cardinality values
```

Actions: `insert` (add if missing), `update` (change if present), `upsert` (add or change), `delete` (remove), `hash` (replace with a hash), `extract` (regex capture). Use these to add cluster/region/version (enrich) and to strip secrets, PII, and raw statements (redact) before anything leaves the cluster.

### tail_sampling

Defers the sampling decision until a trace completes, enabling outcome-driven selection (keep errors and outliers, sample the rest):

```yaml
processors:
  tail_sampling:
    decision_wait: 10s
    num_traces: 100000
    expected_new_traces_per_sec: 1000
    policies:
      - name: errors
        type: status_code
        status_code:
          status_codes: [ERROR]
      - name: slow
        type: latency
        latency:
          threshold_ms: 1000
      - name: sample-rest
        type: probabilistic
        probabilistic:
          sampling_percentage: 5
```

- `decision_wait`: how long to buffer a trace before deciding (default 30s). Set to 2-3x p99 trace duration; too short and the sampler decides on incomplete traces and misses errors/latency.
- `num_traces`: max buffered traces (default 100000); exceeding it drops new traces.
- `expected_new_traces_per_sec`: sizing hint for memory allocation.
- Policies evaluate in order; a trace is kept if any policy matches. Common types: `status_code` (100% errors), `latency` (100% slow), `probabilistic` (a percentage of the rest). Others: `numeric_attribute`, `string_attribute`, `rate_limiting`, `always_sample`.

Tail sampling is the leading cause of Collector memory pressure: monitor memory and size `num_traces`/`decision_wait` deliberately. It is stateful and **cannot** be scaled horizontally on its own — every span of a trace must reach the same Collector instance. The fix is a load-balancing exporter (below).

This is tail sampling at the pipeline. The wider head-vs-tail strategy and the hybrid `parentbased_always_on` SDK + Collector-side `tail_sampling` pattern live in [sampling.md](sampling.md).

## OTLP exporter to Tempo

Tempo accepts OTLP natively at its distributor on 4317 (gRPC) and 4318 (HTTP); no special exporter is needed — the Collector speaks the same OTLP the services do.

```yaml
exporters:
  otlp/tempo:
    endpoint: tempo-distributor.<namespace>.svc:4317
    tls:
      insecure: true            # plain gRPC; omit/false when TLS is configured
    retry_on_failure:
      enabled: true
      initial_interval: 5s
      max_interval: 30s
      max_elapsed_time: 300s
    sending_queue:
      enabled: true
      num_consumers: 10
      queue_size: 5000
```

- `endpoint`: Tempo's distributor (the OTLP receiver). Reuse the existing cluster Tempo rather than standing up a parallel stack.
- `tls.insecure: true`: required for plain gRPC; a common mistake is omitting it (or the Collector failing to resolve the distributor's DNS name).
- `retry_on_failure` + `sending_queue`: exponential-backoff retry and a buffer so transient backend slowness doesn't drop spans.

## Agent vs gateway topology

| | Agent (per-node / sidecar) | Gateway (central) |
|---|---|---|
| Deployment | DaemonSet per host, or sidecar | Stateless Deployment behind a load balancer |
| Processing | Light: `memory_limiter`, `batch`, node-local enrichment | Heavy: `tail_sampling`, enrich/redact, fan-out, protocol translation |
| Sends to | Gateway tier (or backend) | Backend (Tempo) |
| Use when | You need node-local context or local buffering | You need tail sampling, fan-out, or central policy |

### Load-balancing exporter for tail sampling

When the gateway runs `tail_sampling`, the agent tier must route by trace ID so a whole trace lands on one gateway instance:

```yaml
# Agent tier
exporters:
  loadbalancing:
    routing_key: traceID
    protocol:
      otlp:
        tls:
          insecure: true
    resolver:
      dns:
        hostname: collector-gateway.<namespace>.svc
        port: 4317

service:
  pipelines:
    traces:
      receivers: [otlp]
      processors: [memory_limiter, batch]
      exporters: [loadbalancing]
```

- `routing_key: traceID`: hashes the trace ID to pick a gateway; all spans of a trace go to the same one. (Use `routing_key: service` instead when the downstream tier derives span metrics.)
- `resolver.dns`: discovers all gateway pods via the service DNS name.

Without it, spans scatter across gateways, each sees only fragments, and `tail_sampling` makes wrong calls (drops errors, keeps noise).

## Minimal annotated config

Two-tier topology (agent -> gateway -> Tempo).

**Agent** (per-node, lightweight):

```yaml
receivers:
  otlp:
    protocols:
      grpc:
        endpoint: 0.0.0.0:4317
      http:
        endpoint: 0.0.0.0:4318

processors:
  memory_limiter:
    check_interval: 1s
    limit_mib: 512
    spike_limit_mib: 128
  batch:
    send_batch_size: 4096
    timeout: 10s

exporters:
  loadbalancing:
    routing_key: traceID
    protocol:
      otlp:
        tls:
          insecure: true
    resolver:
      dns:
        hostname: collector-gateway.<namespace>.svc
        port: 4317

service:
  pipelines:
    traces:
      receivers: [otlp]
      processors: [memory_limiter, batch]
      exporters: [loadbalancing]
```

**Gateway** (central: tail sampling + export):

```yaml
receivers:
  otlp:
    protocols:
      grpc:
        endpoint: 0.0.0.0:4317

processors:
  memory_limiter:
    check_interval: 1s
    limit_mib: 2048
    spike_limit_mib: 512
  tail_sampling:
    decision_wait: 10s
    num_traces: 100000
    expected_new_traces_per_sec: 1000
    policies:
      - name: errors
        type: status_code
        status_code:
          status_codes: [ERROR]
      - name: slow
        type: latency
        latency:
          threshold_ms: 1000
      - name: sample-rest
        type: probabilistic
        probabilistic:
          sampling_percentage: 5
  batch:
    send_batch_size: 8192
    timeout: 10s

exporters:
  otlp/tempo:
    endpoint: tempo-distributor.<namespace>.svc:4317
    tls:
      insecure: true
    retry_on_failure:
      enabled: true
      initial_interval: 5s
      max_interval: 30s
      max_elapsed_time: 300s
    sending_queue:
      enabled: true
      num_consumers: 10
      queue_size: 5000

service:
  pipelines:
    traces:
      receivers: [otlp]
      processors: [memory_limiter, tail_sampling, batch]
      exporters: [otlp/tempo]
```

What the config encodes:

- Agents: `memory_limiter` -> `batch` -> `loadbalancing` (route by trace ID to gateways).
- Gateways: `memory_limiter` -> `tail_sampling` (errors, slow, 5% rest) -> `batch` -> `otlp/tempo`.
- `memory_limiter` first and `batch` last in both tiers; `tail_sampling` only in the gateway, after routing guarantees complete traces.

For a simple deployment, collapse to one tier: drop the agent, point services at the gateway, and remove `loadbalancing`.

## References

- [instrumentation.md](instrumentation.md) — SDK init order, the env-var contract, resource/semantic conventions, span processors, and auto/manual/framework instrumentation + W3C propagation
- [sampling.md](sampling.md) — head vs tail sampling, the hybrid production pattern, decision_wait tuning, and the loadbalancing exporter
- [tempo.md](tempo.md) — Tempo architecture, OTLP ingest, storage/retention/compaction, TraceQL, and the metrics-generator
- [correlation.md](correlation.md) — trace-to-logs / trace-to-metrics / metrics-to-traces (exemplars) and service graphs
- [gotchas.md](gotchas.md) — the highest-leverage failure modes and their fixes

## Related

- **Policy:** `.claude/rules/devops-observability.md` — when to trace, what to redact, sampling strategy, retention.
- **Role:** `observability-engineer` agent.
- **Siblings:** `observability-and-logging` (app-side setup), `langfuse-llm-tracing` (LLM call tracing).

## Provenance

Re-derived from public authoritative sources: the [OpenTelemetry Collector docs](https://opentelemetry.io/docs/collector/) (deployment, processors, scaling), the [OTLP spec](https://opentelemetry.io/docs/specs/otlp/), and the [Grafana Tempo docs](https://grafana.com/docs/tempo/latest/). When upstream disagrees with this document, trust upstream.