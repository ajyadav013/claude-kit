# Sampling: Control Trace Cost Without Losing the Traces That Matter

Sampling keeps a fraction of traces so storage and egress do not grow linearly with traffic, but the
fraction you keep must include the traces you actually debug with: errors and latency outliers. The
production answer is a two-layer split. **Head sampling** (in the SDK) decides at trace start and is
blind to the outcome, so it can only propagate context cheaply or apply a flat probability.
**Tail sampling** (in the Collector) decides after the trace completes, so it can keep 100% of errors
and slow traces plus a small probabilistic baseline. The 2026 standard is hybrid: SDKs run
`parentbased_always_on` to preserve the trace tree, and the Collector's `tail_sampling` processor
makes the real keep/drop decision.

> **Sibling boundary.** This file is the sampling chapter of `otel-tracing` — the language-neutral
> pipeline + Tempo backend skill. App-side wiring (structured logging, PII redaction, error
> tracking, RED metrics, health probes, framework auto-instrumentation) lives in
> `observability-and-logging`; sampling LLM/model calls (prompts, tokens, cost) lives in
> `langfuse-llm-tracing`. The neutral policy is `.claude/rules/devops-observability.md`. This is the
> concrete OTEL + Tempo how-to underneath them.

## When to use

- Deciding **how much** to sample in production, and whether head sampling alone is enough (it isn't past low traffic)
- Configuring `OTEL_TRACES_SAMPLER` in your services and the `tail_sampling` processor in the Collector
- Diagnosing why **error traces are missing** from the backend (almost always uniform head sampling)
- Setting `decision_wait` and sizing tail-sampling memory; debugging fragmented traces (load-balancing misconfig)
- Estimating the cost of 100% sampling and tuning policies to hit a volume/cost target

## Why sample: volume and cost vs fidelity

Every exported span flows SDK → Collector → backend (Tempo, vendor SaaS) and costs CPU, network
egress, and storage. A service at 10,000 req/s with 20 spans per trace emits 200,000 spans/s. At
~1 KB/span that is ~200 MB/s egress and ~17 TB/day raw. Most systems cannot afford or operate 100%
capture at that scale.

Uniform sampling cuts volume proportionally — 10% sampling, ~10% cost — but the traces you lose
matter more than the ones you keep. At a 1% error rate, errors appear in 1 of every 100 traces; a
flat 10% sample silently drops 90% of them. During an incident you most need the failing traces, and
uniform head sampling cannot guarantee their capture. The goal is **outcome-driven selection**: keep
100% of errors and anomalies, sample normal traffic for baseline visibility, and apply the cost
reduction only to low-signal volume.

## Head sampling: parent-based + trace-id-ratio in the SDK

Head sampling decides at span creation, the moment the SDK creates the root span. It is **blind to
the outcome**: the sampler cannot see the final status code, the duration, or attributes set later.
It is **stateless** and **deterministic** — the SDK hashes the `TraceId` and compares it to a
threshold, with no buffering and no cross-service coordination — which is exactly why it is cheap.

| Sampler (`OTEL_TRACES_SAMPLER`) | Behavior | Use case |
|---|---|---|
| `always_on` | Sample every trace (100%) | Development, debugging, very low traffic |
| `always_off` | Sample nothing (0%) | Disable tracing without removing instrumentation |
| `traceidratio` | Fixed probability from `TraceId` hash (arg `0.1` = 10%) | Simple probabilistic cost control |
| `parentbased_always_on` | Honor parent's decision; sample if root (no parent) | **Production default** — preserves the trace tree |
| `parentbased_always_off` | Honor parent's decision; drop if root | Rarely used standalone |
| `parentbased_traceidratio` | Parent-based, with the ratio applied to root spans | Probabilistic head sampling with consistent propagation |

**Parent-based** sampling is what keeps distributed traces whole. When a request crosses a service
boundary, the upstream decision rides the W3C `traceparent` header's `trace-flags` byte (bit 0, the
`sampled` flag). A child with a `parentbased_*` sampler honors it: parent sampled ⇒ child samples;
parent did not ⇒ child does not. You never get a trace with the root missing because one downstream
service decided independently.

The SDK applies the decision **before export**, so non-sampled spans never leave the process —
saving CPU, network, and storage at the earliest point. Cost is predictable: 10% sampling means ~10%
export volume.

### Head sampling limitations

- **Blind to errors.** The decision precedes span completion, so the sampler cannot know the final `status.code`. A trace that will return HTTP 5xx or throw looks identical to a success at creation.
- **Blind to latency.** Duration is unknown because the span has not finished. Fast and slow requests sample at the same rate.
- **Blind to attributes.** Business-critical attributes (user/tenant id, transaction type, cohort) are often set mid-span or at end and cannot be filtered on.

Net effect: uniform head sampling at 10% loses ~90% of errors and ~90% of latency outliers —
unacceptable for production debugging.

### Configuration

Head samplers are configured via environment variables (the cross-language contract):

```bash
# Parent-based always-on (recommended production default; propagates context)
OTEL_TRACES_SAMPLER=parentbased_always_on

# Parent-based with 10% probability at root
OTEL_TRACES_SAMPLER=parentbased_traceidratio
OTEL_TRACES_SAMPLER_ARG=0.1
```

Head sampling alone suits **development** and **very low-traffic** services where 100% capture is
affordable. For high traffic, use head sampling only to propagate context
(`parentbased_always_on` in every SDK) and defer the real decision to the Collector's tail sampler.

## Tail sampling: decided after the trace completes

Tail sampling defers the decision until **after the trace completes** — all spans have finished and
reached the Collector. The `tail_sampling` processor buffers spans in memory for a `decision_wait`
period (e.g., 10s), waits for the trace to assemble, then evaluates **policies** against the full
trace. Policies can inspect span status, duration, attributes, and trace-level intrinsics (trace
duration, root service) to make outcome-driven decisions.

### Tail sampling policies

A trace is kept if it matches **any** policy (OR semantics):

| Policy type | Keeps traces where | Example |
|---|---|---|
| `status_code` | Any span has the given status | Capture 100% of `ERROR` traces |
| `numeric_attribute` | A numeric attribute matches a condition | `http.response.status_code >= 500` |
| `string_attribute` | A string attribute matches value/regex | A specific tenant or cohort |
| `latency` | Trace duration exceeds a threshold | Slow requests (`threshold_ms`) |
| `probabilistic` | Random sample at a fixed percentage | 5% baseline for normal traffic |
| `rate_limiting` | Cap at N traces/sec | Bound cost during traffic surges |
| `always_sample` | Every trace | Combine in an `and` policy for AND logic |
| `and` | All sub-policies match | Compose multiple conditions |

Common production set:

1. `status_code: [ERROR]` — keep 100% of errors
2. `latency > 2s` — keep 100% of slow traces
3. `probabilistic: 5%` — keep a baseline of everything else

Result: every error and latency outlier is retained; normal fast-success traffic samples at 5% for
cost control.

### Whole-trace locality requirement

Tail sampling needs **all spans of one trace** at the **same Collector instance** before
`decision_wait` expires. If spans scatter across instances (the default with any load balancing),
each Collector sees only a fragment, evaluates policies on incomplete data, and decides wrong — for
example dropping an error trace because it only saw the healthy root span, not the child that failed.

The fix is the **agent → gateway topology** with a **load-balancing exporter routing by `TraceId`**:

1. **Agent tier** (per-host Collectors, e.g., a DaemonSet): receive OTLP from the SDKs, do minimal local work (batch, resource detection), and forward to the gateway tier via the `loadbalancing` exporter with `routing_key: traceID`.
2. **Gateway tier** (centralized, stateless Deployment): the `loadbalancing` exporter consistently hashes each span's `TraceId` so all spans of a trace land on the same gateway. That gateway runs `tail_sampling`, sees the complete trace, decides correctly, and exports to Tempo.

Load-balancing exporter (agent tier):

```yaml
exporters:
  loadbalancing:
    protocol:
      otlp:
        tls:
          insecure: true
    resolver:
      dns:
        hostname: collector-gateway   # headless service DNS for the gateway tier
        port: 4317
    routing_key: traceID              # hash by TraceId so whole traces co-locate

service:
  pipelines:
    traces:
      receivers: [otlp]
      processors: [batch]
      exporters: [loadbalancing]
```

Gateway tier:

```yaml
processors:
  memory_limiter:                     # MUST be the first processor
    check_interval: 1s
    limit_mib: 512                    # set to ~80% of the container memory limit
    spike_limit_mib: 128

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
          threshold_ms: 2000
      - name: baseline
        type: probabilistic
        probabilistic:
          sampling_percentage: 5

  batch:                              # batch is last
    send_batch_size: 8192
    timeout: 10s

exporters:
  otlp/tempo:
    endpoint: tempo:4317              # Tempo OTLP gRPC distributor (HTTP is 4318)
    tls:
      insecure: true

service:
  pipelines:
    traces:
      receivers: [otlp]
      processors: [memory_limiter, tail_sampling, batch]
      exporters: [otlp/tempo]
```

Processor order matters: `memory_limiter` is **first** so it can refuse data before OOM, and `batch`
is **last**. `tail_sampling` buffers spans for `decision_wait`, so under high traffic or a slow
backend it is the leading cause of Collector memory growth; the memory limiter is the backstop.

### Tail sampling tuning

| Parameter | Meaning | How to set |
|---|---|---|
| `decision_wait` | How long to buffer spans waiting for the trace to complete | **2–3× p99 trace duration.** Too short ⇒ decisions on incomplete traces (errors dropped because the error span has not arrived). |
| `num_traces` | Max traces buffered in memory | 100,000+ for high throughput; watch memory. |
| `expected_new_traces_per_sec` | Sizing hint for internal structures | Set near peak traces/sec to avoid resize overhead. |

### Tail sampling costs

- **Memory.** Buffering for seconds consumes RAM; 100,000 traces × 20 spans × ~1 KB ≈ 2 GB of trace data plus overhead. Pair with `memory_limiter` and monitor.
- **Delay.** Spans do not reach the backend until `decision_wait` expires, so traces appear ~10s late. Do not alert on traces in real time — alert on metrics (Tempo's metrics-generator RED metrics) instead.
- **Complexity.** Requires the agent→gateway topology and `TraceId` routing. A misconfigured load balancer breaks tail sampling silently — traces fragment and decisions go wrong with no error.

Use tail sampling when traffic is high enough that 100% is prohibitive **and** you need guaranteed
capture of errors and outliers. Skip it for low-traffic services and development.

## Consistent propagation of the sampling decision

The `sampled` flag in the W3C `traceparent` `trace-flags` byte carries the decision across service
boundaries. With **hybrid sampling**, configure every SDK with `parentbased_always_on` (or
`parentbased_traceidratio` at ratio `1.0`):

- The SDK always creates spans and exports them to the Collector (no SDK-side dropping).
- The SDK always sets the `sampled` flag, so downstream services keep creating spans.
- The trace tree arrives complete at the Collector.

The **Collector's tail sampler** then makes the real keep/drop decision at the gateway. The SDK's
`sampled` flag is effectively a "keep propagating context" hint, not the final verdict.

This gives a clean consistency guarantee: every service on the request path sees the same context and
emits spans, and the tail decision applies to the **whole trace** — all spans kept or all dropped.
You never get partial traces.

### Edge case: external traffic

- **No inbound `traceparent`** (browser, third-party webhook): the root service's SDK mints a new `TraceId`, its `parentbased_always_on` sampler samples the root, sets the flag, and propagation proceeds; the gateway decides the trace's fate.
- **Inbound `traceparent` from another instrumented system**: the root's `parentbased_*` sampler honors the external decision. Overriding with `always_on` would break consistency, so do it only deliberately.

## Recommended defaults and how to tune

| Tier | SDK sampler | Collector | decision_wait | Approx. kept volume |
|---|---|---|---|---|
| Dev / very low traffic | `parentbased_always_on` (100%) | none; export direct to Tempo | n/a | 100% |
| Production, ≤ ~1,000 req/s | `parentbased_always_on` | `status_code:ERROR` + `latency>2s` + `probabilistic:10%` | 10s (p99 < ~5s) | ~10–15% |
| Production, > ~1,000 req/s | `parentbased_always_on` | errors + `latency>3s` + `probabilistic:5%` + optional `rate_limiting:100/s` | 15s | ~5–10% |

Tune the probabilistic baseline to hit a volume target, tighten the latency threshold to shed
volume, and add `rate_limiting` to cap spend during surges. The agent→gateway topology is required
once you scale gateways for tail sampling.

### The cost of 100% sampling in production

One service at 1,000 req/s with 20 spans/trace emits 20,000 spans/s. At ~1 KB/span compressed that is
~20 MB/s ≈ ~1.7 TB/month of egress per service. At typical cloud egress ($0.09–$0.12/GB) that is
roughly $150–200/month in egress alone, before backend storage. With 14-day Tempo block retention,
average data at rest is ~1.7 TB × 14/30 ≈ 0.8 TB, adding tens of dollars/month at object-storage
rates. Across ten such services, 100% sampling runs on the order of $1,500–2,000/month.

A tail-sampling set (errors + slow + ~5% baseline) drops kept volume to ~5–10% — roughly $150–400/month
for the same fleet, a 75–90% reduction, while still retaining every error and slow trace. As a rough
break-even, 100% sampling is affordable up to ~100 req/s per service (depending on span count and
provider); beyond that, tail sampling pays for itself in the first month.

## References

- [instrumentation.md](instrumentation.md) — SDK init order, the env-var contract, resource/semantic conventions, span processors, and auto/manual/framework instrumentation + W3C propagation
- [collector.md](collector.md) — the OTel Collector pipeline, agent/gateway topology, the core processors, the OTLP-to-Tempo exporter, and the loadbalancing exporter
- [tempo.md](tempo.md) — Tempo architecture, OTLP ingest, storage/retention/compaction, TraceQL, and the metrics-generator
- [correlation.md](correlation.md) — trace-to-logs / trace-to-metrics / metrics-to-traces (exemplars) and service graphs
- [gotchas.md](gotchas.md) — the highest-leverage failure modes and their fixes

## Provenance

Re-derived from public authoritative documentation:
[OpenTelemetry Sampling](https://opentelemetry.io/docs/concepts/sampling/),
[SDK environment variables](https://opentelemetry.io/docs/specs/otel/configuration/sdk-environment-variables/),
[tail-sampling processor](https://github.com/open-telemetry/opentelemetry-collector-contrib/tree/main/processor/tailsamplingprocessor),
[load-balancing exporter](https://github.com/open-telemetry/opentelemetry-collector-contrib/tree/main/exporter/loadbalancingexporter),
[Collector scaling](https://opentelemetry.io/docs/collector/scaling/),
[Grafana Tempo](https://grafana.com/docs/tempo/latest/), and
[W3C Trace Context](https://www.w3.org/TR/trace-context/). Defaults and processor configuration
evolve; when upstream OpenTelemetry or Grafana docs disagree with this reference, trust upstream and
update this skill.

## Related

- Rules: `.claude/rules/devops-observability.md` (neutral observability policy — logs, metrics, traces, correlation; backend-agnostic), `.claude/rules/agent-resilience.md` (tracing must degrade gracefully and never crash the app)
- Agent: `observability-engineer` (owns the OTLP → Collector → Tempo pipeline, tail sampling, Grafana datasources, trace↔logs↔metrics correlation)
- Siblings: `observability-and-logging` (app-side instrumentation and logging), `langfuse-llm-tracing` (LLM prompt/token/cost tracing)
