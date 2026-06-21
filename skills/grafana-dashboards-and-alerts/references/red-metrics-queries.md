# RED Metrics Queries

This reference covers PromQL patterns for RED (Rate/Error/Duration) metrics from three proven production sources: NGINX ingress controller, OpenTelemetry span-metrics (Tempo), and Kubernetes pod/container utilization.

## RED metrics overview

RED is a foundational observability framework for request-driven systems:
- **Rate**: Requests per second/minute
- **Error**: Error ratio or count
- **Duration**: Latency (average, percentiles)

Complement RED with USE (Utilization/Saturation/Errors) for resource-level metrics (CPU, memory, disk).

## Source 1: NGINX Ingress Controller

The NGINX ingress controller exposes HTTP metrics for services behind a Kubernetes ingress. This is often the most reliable source for user-facing request metrics.

### Metric structure

```
nginx_ingress_controller_requests{exported_service="...", status="...", method="..."}
nginx_ingress_controller_request_duration_seconds_bucket{exported_service="...", le="..."}
nginx_ingress_controller_request_duration_seconds_sum{exported_service="..."}
nginx_ingress_controller_request_duration_seconds_count{exported_service="..."}
```

Key labels:
- `exported_service`: Target service name (often matches Kubernetes Service)
- `status`: HTTP status code (200, 404, 500, etc.)
- `method`: HTTP method (GET, POST, PUT, DELETE)
- `le`: Histogram bucket boundary (for percentile calculations)

### Rate: Requests per second

```promql
sum(irate(nginx_ingress_controller_requests{exported_service=~"$service"}[$__rate_interval])) 
  by (exported_service)
```

**Breakdown by status:**
```promql
sum(irate(nginx_ingress_controller_requests{exported_service=~"$service"}[$__rate_interval])) 
  by (exported_service, status)
```

**Why `irate` vs `rate`:** `irate` uses the last two samples (more responsive to spikes); `rate` averages over the full window (smoother). For alerting, use `rate` (less noisy). For real-time dashboards, `irate` is acceptable.

**Use `$__rate_interval` not a fixed `[5m]`.** The macro adapts to scrape frequency (typically 4× scrape interval), preventing under-sampling or over-smoothing.

### Error ratio

```promql
sum(rate(nginx_ingress_controller_requests{exported_service=~"$service", status=~"5.."}[$__rate_interval]))
  / sum(rate(nginx_ingress_controller_requests{exported_service=~"$service"}[$__rate_interval]))
```

**5xx errors only:**
```promql
sum(rate(nginx_ingress_controller_requests{exported_service=~"$service", status=~"5.."}[$__rate_interval])) 
  by (exported_service)
```

**4xx + 5xx:**
```promql
sum(rate(nginx_ingress_controller_requests{exported_service=~"$service", status=~"4..|5.."}[$__rate_interval]))
  / sum(rate(nginx_ingress_controller_requests{exported_service=~"$service"}[$__rate_interval]))
```

### Duration: Average latency

```promql
avg(rate(nginx_ingress_controller_request_duration_seconds_sum{exported_service=~"$service"}[$__rate_interval])) 
  / avg(rate(nginx_ingress_controller_request_duration_seconds_count{exported_service=~"$service"}[$__rate_interval]))
```

**Why this works:** The `_sum` metric is the total duration of all requests; `_count` is the number of requests. Dividing them gives the average duration.

**By service:**
```promql
sum(rate(nginx_ingress_controller_request_duration_seconds_sum{exported_service=~"$service"}[$__rate_interval])) 
  by (exported_service)
  / sum(rate(nginx_ingress_controller_request_duration_seconds_count{exported_service=~"$service"}[$__rate_interval])) 
      by (exported_service)
```

### Duration: Percentiles (p90, p95, p99)

```promql
histogram_quantile(0.95, 
  sum(rate(nginx_ingress_controller_request_duration_seconds_bucket{exported_service=~"$service"}[$__rate_interval])) 
    by (le))
```

**By service:**
```promql
histogram_quantile(0.95, 
  sum(rate(nginx_ingress_controller_request_duration_seconds_bucket{exported_service=~"$service"}[$__rate_interval])) 
    by (le, exported_service))
```

**All three percentiles (multi-query panel):**
- Query A (p90): `histogram_quantile(0.90, ...)`
- Query B (p95): `histogram_quantile(0.95, ...)`
- Query C (p99): `histogram_quantile(0.99, ...)`

**Critical:** The `by (le)` grouping is REQUIRED for `histogram_quantile`. Omitting it produces incorrect results.

### Total requests over dashboard range

```promql
sum(increase(nginx_ingress_controller_requests{exported_service=~"$service"}[$__range])) 
  by (exported_service)
```

**Why `$__range` not `$__rate_interval`:** `$__range` is the dashboard's current time window (e.g., 1h). `increase()` over `$__range` gives the total count in the visible window.

Use this for stat panels showing "Total Requests (last 1h)".

## Source 2: OpenTelemetry span-metrics (Tempo)

Tempo's metrics-generator can derive RED metrics from distributed trace spans. This gives per-operation granularity and works even when the application doesn't expose Prometheus metrics directly.

### Metric structure

```
traces_spanmetrics_calls_total{cluster="...", service="...", span_kind="...", span_name="...", status_code="..."}
traces_spanmetrics_latency_bucket{cluster="...", service="...", span_kind="...", le="..."}
traces_spanmetrics_latency_sum{cluster="...", service="...", span_kind="..."}
traces_spanmetrics_latency_count{cluster="...", service="...", span_kind="..."}
```

Key labels:
- `cluster`: Deployment cluster (prod/staging/dev)
- `service`: Service name (from trace service.name attribute)
- `span_kind`: OpenTelemetry span kind (SPAN_KIND_SERVER, SPAN_KIND_CLIENT, SPAN_KIND_CONSUMER, SPAN_KIND_PRODUCER, SPAN_KIND_INTERNAL)
- `span_name`: Operation name (e.g., "GET /api/users", "process_order")
- `status_code`: STATUS_CODE_UNSET, STATUS_CODE_OK, STATUS_CODE_ERROR

### Rate: Requests per minute

```promql
sum(rate(traces_spanmetrics_calls_total{cluster="$cluster", service="$service", span_kind="$span_kind"}[$__rate_interval])) 
  by (span_kind) * 60
```

**Why × 60:** `rate()` returns per-second rate. Multiply by 60 for requests per minute (more intuitive for high-traffic services).

**Per-operation breakdown:**
```promql
sum(rate(traces_spanmetrics_calls_total{cluster="$cluster", service="$service", span_kind="$span_kind"}[$__rate_interval])) 
  by (span_name) * 60
```

Use this to identify which endpoints are busiest.

### Error ratio

```promql
sum(increase(traces_spanmetrics_calls_total{cluster="$cluster", service="$service", span_kind="$span_kind", status_code="STATUS_CODE_ERROR"}[$__range]))
  / sum(increase(traces_spanmetrics_calls_total{cluster="$cluster", service="$service", span_kind="$span_kind"}[$__range]))
```

**Why `increase` not `rate`:** Error ratio over the full dashboard range is more intuitive than instantaneous error rate. For a real-time error rate, use `rate` instead:

```promql
sum(rate(traces_spanmetrics_calls_total{..., status_code="STATUS_CODE_ERROR"}[$__rate_interval]))
  / sum(rate(traces_spanmetrics_calls_total{...}[$__rate_interval]))
```

### Duration: Percentiles

```promql
histogram_quantile(0.95, 
  sum(rate(traces_spanmetrics_latency_bucket{cluster="$cluster", service="$service", span_kind="$span_kind"}[$__rate_interval])) 
    by (le))
```

**By operation:**
```promql
histogram_quantile(0.95, 
  sum(rate(traces_spanmetrics_latency_bucket{cluster="$cluster", service="$service", span_kind="$span_kind"}[$__rate_interval])) 
    by (le, span_name))
```

**Unit:** `traces_spanmetrics_latency_*` is in seconds. Set panel `unit: "s"` or `unit: "ms"`.

### Span kind filtering

**Web (server-side HTTP):**
```promql
{span_kind="SPAN_KIND_SERVER"}
```

**Consumer (message queue consumers):**
```promql
{span_kind="SPAN_KIND_CONSUMER"}
```

**Internal (internal function calls):**
```promql
{span_kind="SPAN_KIND_INTERNAL"}
```

Use a custom template variable (see `references/dashboard-json-and-templating.md`) to let users switch between span kinds.

### Cascading cluster → service variables

```json
{
  "name": "cluster",
  "type": "query",
  "query": "label_values(cluster)"
},
{
  "name": "service",
  "type": "query",
  "query": "label_values(traces_spanmetrics_calls_total{cluster=\"$cluster\"}, \"service\")"
}
```

This filters the service list to only those present in the selected cluster.

## Source 3: Pod/container utilization (kube-state-metrics + cAdvisor)

For resource-level RED, track CPU/memory usage vs limits and container restarts.

### Metric structure

```
container_cpu_usage_seconds_total{container="...", pod="...", namespace="..."}
container_memory_usage_bytes{container="...", pod="...", namespace="..."}
kube_pod_container_resource_limits_cpu_cores{container="...", pod="...", namespace="..."}
kube_pod_container_resource_limits_memory_bytes{container="...", pod="...", namespace="..."}
kube_pod_container_status_restarts_total{container="...", pod="...", namespace="..."}
```

Key labels:
- `container`: Container name (NOT the Kubernetes POD pause container)
- `pod`: Pod name
- `namespace`: Kubernetes namespace

**Filter `container!="POD"`** to exclude the pause container (it has no resource usage).

### CPU usage vs limit

```promql
sum(rate(container_cpu_usage_seconds_total{container=~"$container", container!="POD"}[$__rate_interval])) 
  by (container, pod)
  / sum(kube_pod_container_resource_limits_cpu_cores{container=~"$container"}) 
      by (container, pod)
```

**Unit:** Ratio (0.0 to 1.0+). Set panel `unit: "percentunit"` (displays as 0-100%).

**Interpretation:** `1.0` = 100% of CPU limit. Values >1.0 indicate throttling (container is CPU-constrained).

**Aggregated by container (across all pods):**
```promql
sum(rate(container_cpu_usage_seconds_total{container=~"$container", container!="POD"}[$__rate_interval])) 
  by (container)
  / sum(kube_pod_container_resource_limits_cpu_cores{container=~"$container"}) 
      by (container)
```

### Memory usage vs limit

```promql
sum(container_memory_usage_bytes{container=~"$container", container!="POD"}) 
  by (container, pod)
  / sum(kube_pod_container_resource_limits_memory_bytes{container=~"$container"}) 
      by (container, pod)
```

**Unit:** Ratio. Set panel `unit: "percentunit"`.

**Interpretation:** `1.0` = 100% of memory limit. Values approaching 1.0 risk OOMKill.

**Why no `rate()`:** `container_memory_usage_bytes` is a gauge (current value), not a counter. Don't apply `rate()` to it.

### Container restarts

```promql
round(sum(increase(kube_pod_container_status_restarts_total{container=~"$container"}[$__rate_interval])) 
  by (container, pod))
```

**Why `round()`:** `increase()` can produce fractional values due to extrapolation. `round()` converts to integers (restarts are discrete events).

**Unit:** `short` (count).

**Interpretation:** Non-zero restarts indicate crashes or OOMKills. Cross-reference with CPU/memory usage.

## PromQL best practices

### $__rate_interval vs $__range

- **`$__rate_interval`**: Use in `rate()` and `irate()`. Adapts to scrape frequency (typically 4× scrape interval, e.g., `2m` for 30s scrapes). Grafana calculates this dynamically.
- **`$__range`**: Dashboard's current time window (e.g., `1h`, `6h`). Use in `increase()` for totals over the visible range.

**Examples:**
```promql
# Rate per second (adaptive window)
rate(metric[$__rate_interval])

# Total count over dashboard range
increase(metric[$__range])

# Average over a fixed 5-minute window (avoid, prefer $__rate_interval)
rate(metric[5m])
```

### histogram_quantile deep dive

Prometheus histograms store latency buckets. `histogram_quantile` interpolates percentiles from these buckets.

**Requirements:**
1. Metric name ends in `_bucket`
2. Must have `le` label (bucket boundary)
3. Query MUST group `by (le)` (and optionally other labels)

**Syntax:**
```promql
histogram_quantile(φ, sum(rate(metric_bucket{...}[$__rate_interval])) by (le, label1, label2))
```

- `φ`: Percentile (0.50 = p50, 0.95 = p95, 0.99 = p99)
- `by (le)`: REQUIRED. Omitting this produces nonsense results.
- `by (le, service)`: Percentile per service
- `by (le)`: Single percentile across all series

**Common mistakes:**
```promql
# WRONG: Missing `by (le)`
histogram_quantile(0.95, rate(metric_bucket[5m]))

# WRONG: Grouping by label before rate()
sum(histogram_quantile(0.95, rate(metric_bucket[5m]) by (le))) by (service)

# CORRECT:
histogram_quantile(0.95, sum(rate(metric_bucket[5m])) by (le, service))
```

**Units:** If the histogram is in seconds, set panel `unit: "s"`. Grafana will auto-convert to ms for small values.

### rate() vs irate()

- **`rate()`**: Average rate over the full time window. Smoother, better for alerting.
- **`irate()`**: Instantaneous rate (last two samples). More responsive, better for real-time dashboards.

**When to use:**
- Dashboards: `irate` for request rate, `rate` for latency (less noisy)
- Alerts: Always `rate` (prevents flapping on single spikes)

**Edge case:** `irate` can miss spikes if the scrape interval is large. Prefer `rate` unless you need sub-minute responsiveness.

### Avoid over-aggregation

**Bad:**
```promql
sum(rate(metric[5m]))
```

This sums across all labels (pod, namespace, etc.), losing granularity.

**Good:**
```promql
sum(rate(metric[5m])) by (service, status)
```

Aggregate by meaningful dimensions. Balance cardinality (too many series slows Grafana) with insight.

### Label matching operators

- `=`: Exact match (`service="api"`)
- `!=`: Not equal (`container!="POD"`)
- `=~`: Regex match (`exported_service=~"$service"` where `$service` is multi-select)
- `!~`: Regex not match (`status!~"2.."`)

**Multi-select variables expand to regex:**
```promql
# User selects ["api", "worker"]
{service=~"$service"}  →  {service=~"api|worker"}

# User selects "All" (allValue: ".*")
{service=~"$service"}  →  {service=~".*"}
```

### Subqueries (advanced)

Calculate rate-of-change of a gauge (e.g., "is lag increasing?"):

```promql
rate(metric[5m:1m])
```

This evaluates `metric[5m]` every 1 minute, then calculates `rate()` over those evaluations. Useful for detecting trends in non-counter metrics.

**Example:** Kafka consumer lag trend:
```promql
rate(kminion_kafka_consumer_group_topic_partition_lag[10m:1m])
```

Positive values = lag increasing; negative = decreasing.

## Full RED dashboard example

Combining all three sources:

```json
{
  "panels": [
    {
      "title": "HTTP Requests/sec (NGINX Ingress)",
      "targets": [
        {
          "expr": "sum(irate(nginx_ingress_controller_requests{exported_service=~\"$service\"}[$__rate_interval])) by (exported_service)"
        }
      ]
    },
    {
      "title": "Trace Requests/min (Tempo Span-Metrics)",
      "targets": [
        {
          "expr": "sum(rate(traces_spanmetrics_calls_total{cluster=\"$cluster\", service=~\"$service\", span_kind=\"$span_kind\"}[$__rate_interval])) by (service) * 60"
        }
      ]
    },
    {
      "title": "p95 Latency (NGINX Ingress)",
      "targets": [
        {
          "expr": "histogram_quantile(0.95, sum(rate(nginx_ingress_controller_request_duration_seconds_bucket{exported_service=~\"$service\"}[$__rate_interval])) by (le, exported_service))"
        }
      ]
    },
    {
      "title": "p95 Latency (Tempo Span-Metrics)",
      "targets": [
        {
          "expr": "histogram_quantile(0.95, sum(rate(traces_spanmetrics_latency_bucket{cluster=\"$cluster\", service=~\"$service\", span_kind=\"$span_kind\"}[$__rate_interval])) by (le, service))"
        }
      ]
    },
    {
      "title": "Error Ratio (Tempo Span-Metrics)",
      "targets": [
        {
          "expr": "sum(increase(traces_spanmetrics_calls_total{cluster=\"$cluster\", service=~\"$service\", span_kind=\"$span_kind\", status_code=\"STATUS_CODE_ERROR\"}[$__range])) / sum(increase(traces_spanmetrics_calls_total{cluster=\"$cluster\", service=~\"$service\", span_kind=\"$span_kind\"}[$__range]))"
        }
      ]
    },
    {
      "title": "CPU Usage vs Limit",
      "targets": [
        {
          "expr": "sum(rate(container_cpu_usage_seconds_total{container=~\"$container\", container!=\"POD\"}[$__rate_interval])) by (container, pod) / sum(kube_pod_container_resource_limits_cpu_cores{container=~\"$container\"}) by (container, pod)"
        }
      ],
      "fieldConfig": { "defaults": { "unit": "percentunit" } }
    },
    {
      "title": "Memory Usage vs Limit",
      "targets": [
        {
          "expr": "sum(container_memory_usage_bytes{container=~\"$container\", container!=\"POD\"}) by (container, pod) / sum(kube_pod_container_resource_limits_memory_bytes{container=~\"$container\"}) by (container, pod)"
        }
      ],
      "fieldConfig": { "defaults": { "unit": "percentunit" } }
    },
    {
      "title": "Container Restarts",
      "targets": [
        {
          "expr": "round(sum(increase(kube_pod_container_status_restarts_total{container=~\"$container\"}[$__rate_interval])) by (container, pod))"
        }
      ]
    }
  ]
}
```

This gives a comprehensive view: user-facing HTTP metrics (NGINX), per-operation trace metrics (Tempo), and resource utilization (Kubernetes).
