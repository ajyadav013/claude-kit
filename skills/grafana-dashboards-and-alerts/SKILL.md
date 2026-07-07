---
name: grafana-dashboards-and-alerts
description: Production Grafana dashboards and unified alerting. Use when editing dashboard JSON or PromQL, building RED dashboards, authoring alert rules and contact-point routing, or provisioning dashboards as code.
---

# Grafana Dashboards and Alerts

Build production-quality Grafana dashboards and alerting rules following proven conventions from
large-scale multi-cluster observability deployments. This skill covers the entire lifecycle: JSON
model structure, template variables for portability, RED metrics PromQL patterns, unified alerting
with label-based routing, and dashboard-as-code provisioning.

## When to use

- Building new Grafana dashboards for services, infrastructure, or business metrics
- Writing or debugging PromQL queries for RED (Rate/Error/Duration) metrics
- Authoring Grafana unified alerting rules with proper labeling and routing
- Configuring dashboard template variables ($datasource, cascading label_values, custom variables)
- Setting up contact points (Slack, PagerDuty, webhook) and notification policies
- Provisioning dashboards and alerts as code (file provider, JSON in git)
- Visualizing Tempo distributed traces (service graph nodeGraph panels, span-metrics RED)
- Refactoring dashboards for portability across environments or datasource instances
- Reviewing dashboards for anti-patterns (hardcoded UIDs, broad regexes, missing annotations)

## Core conventions

### Datasource stack and selection

Modern observability deployments typically use:
- **Prometheus** (primary metrics) — often multiple instances (prod/staging/dev)
- **Tempo** (distributed traces) — service graph + span-metrics (RED derived from traces)
- **Pyroscope** (continuous profiling)
- **Cloud-managed services** (Stackdriver/Google Cloud Monitoring, CloudWatch) for managed resources
- **Elasticsearch** or **Loki** (logs)
- **Infinity datasource** (yesoreyeram-infinity-datasource) for JSON/CSV/REST sources

**Golden rule:** Always select datasources via a `$datasource` **template variable** of type
"datasource", not a hardcoded UID. This makes dashboards portable across Prometheus instances and
environments (prod/staging/dev). Panel datasource config:
```json
"datasource": {
  "type": "prometheus",
  "uid": "${datasource}"
}
```

### Dashboard JSON model anatomy

Grafana dashboards are JSON documents. Common `schemaVersion` values: 30, 38, 41.

**Top-level structure:**
- `title`, `uid` (unique identifier), `tags[]` (for organization/search)
- `schemaVersion` (Grafana model version)
- `time`: default time range (`{ "from": "now-1h", "to": "now" }`)
- `templating.list[]`: template variables (datasource selector, cluster/service cascades)
- `annotations.list[]`: event overlays (deployments, incidents)
- `links[]`: dashboard cross-links
- `panels[]`: visualization elements

**Panel structure:**
```json
{
  "type": "timeseries",  // or "table", "stat", "row", "nodeGraph"
  "gridPos": { "h": 8, "w": 12, "x": 0, "y": 0 },
  "datasource": { "type": "prometheus", "uid": "${datasource}" },
  "targets": [ /* queries */ ],
  "fieldConfig": {
    "defaults": {
      "unit": "reqps",
      "thresholds": { /* ... */ }
    }
  },
  "options": { /* panel-type-specific options */ }
}
```

**Query targets** (Prometheus):
```json
{
  "refId": "A",
  "expr": "sum(rate(http_requests_total{service=\"$service\"}[$__rate_interval]))",
  "legendFormat": "{{method}} {{status}}"
}
```

**Row panels** group related visualizations. Collapse/expand rows to organize large dashboards.

**nodeGraph panels** render the Tempo service graph (distributed trace topology).

See `references/dashboard-json-and-templating.md` for exhaustive model details.

### Template variables: the APM dashboard pattern

Template variables make dashboards dynamic and reusable. Key patterns:

1. **Datasource selector** (always include):
   ```yaml
   name: datasource
   type: datasource
   query: prometheus
   current: { value: <default-uid> }
   ```

2. **Cascading label_values queries** (cluster → service hierarchy):
   ```yaml
   # Top-level dimension
   name: cluster
   type: query
   datasource: ${datasource}
   query: label_values(cluster)
   
   # Dependent dimension (filters on parent)
   name: service
   type: query
   datasource: ${datasource}
   query: label_values(traces_spanmetrics_calls_total{cluster="$cluster"}, "service")
   ```

3. **Custom variables** for structured filters:
   ```yaml
   name: span_kind
   type: custom
   options:
     - { text: "Web", value: "SPAN_KIND_SERVER" }
     - { text: "Consumer", value: "SPAN_KIND_CONSUMER" }
     - { text: "Internal", value: "SPAN_KIND_INTERNAL" }
   ```

4. **Multi-select with All** (where cardinality allows):
   ```yaml
   multi: true
   includeAll: true
   allValue: .*
   ```

**Macros in queries:**
- `$__rate_interval` — adaptive rate window (typically 4×scrape interval)
- `$__range` — dashboard's current time range (for increase())
- `$__interval` — aggregation step for grouping

Template variables cascade: changing `$cluster` re-queries downstream vars (`$service`).

### RED metrics PromQL patterns

Three proven sources for Rate/Error/Duration metrics:

#### 1. HTTP RED from NGINX Ingress Controller

**Throughput (requests/sec):**
```promql
sum(irate(nginx_ingress_controller_requests{exported_service=~"$service"}[$__rate_interval])) 
  by (exported_service)
```

**Average latency:**
```promql
avg(rate(nginx_ingress_controller_request_duration_seconds_sum{exported_service=~"$service"}[$__rate_interval])) 
  / avg(rate(nginx_ingress_controller_request_duration_seconds_count{exported_service=~"$service"}[$__rate_interval]))
```

**Percentiles (p90/p95/p99):**
```promql
histogram_quantile(0.95, 
  sum(rate(nginx_ingress_controller_request_duration_seconds_bucket{exported_service=~"$service"}[$__rate_interval])) 
    by (le))
```

**Total requests over dashboard range:**
```promql
sum(increase(nginx_ingress_controller_requests{exported_service=~"$service"}[$__range])) 
  by (exported_service)
```

#### 2. RED from OpenTelemetry span-metrics (Tempo)

**Rate (requests/minute):**
```promql
sum(rate(traces_spanmetrics_calls_total{cluster="$cluster", service="$service", span_kind="$span_kind"}[$__rate_interval])) 
  by (span_kind) * 60
```

**Latency percentiles:**
```promql
histogram_quantile(0.95, 
  sum(rate(traces_spanmetrics_latency_bucket{cluster="$cluster", service="$service", span_kind="$span_kind"}[$__rate_interval])) 
    by (le))
```

**Error ratio:**
```promql
sum(increase(traces_spanmetrics_calls_total{cluster="$cluster", service="$service", span_kind="$span_kind", status_code="STATUS_CODE_ERROR"}[$__range]))
  / sum(increase(traces_spanmetrics_calls_total{cluster="$cluster", service="$service", span_kind="$span_kind"}[$__range]))
```

**Per-operation breakdown:**
```promql
sum(rate(traces_spanmetrics_calls_total{cluster="$cluster", service="$service", span_kind="$span_kind"}[$__range])) 
  by (span_name)
```

#### 3. Pod/container utilization (kube-state-metrics + cAdvisor)

**CPU usage vs limit:**
```promql
sum(rate(container_cpu_usage_seconds_total{container=~"$container", container!="POD"}[$__rate_interval])) 
  by (container, pod)
  / sum(kube_pod_container_resource_limits_cpu_cores{container=~"$container"}) 
      by (container, pod)
```

**Memory usage vs limit:**
```promql
sum(container_memory_usage_bytes{container=~"$container", container!="POD"}) 
  by (container, pod)
  / sum(kube_pod_container_resource_limits_memory_bytes{container=~"$container"}) 
      by (container, pod)
```

**Container restarts:**
```promql
round(sum(increase(kube_pod_container_status_restarts_total{container=~"$container"}[$__rate_interval])) 
  by (container, pod))
```

**Key PromQL guidelines:**
- Use `$__rate_interval` for rate/irate (adapts to scrape frequency)
- Use `$__range` for increase() over dashboard's time window
- Filter `container!="POD"` to exclude Kubernetes pause containers
- `histogram_quantile` requires `by (le)` grouping on the bucket selector

See `references/red-metrics-queries.md` for deeper PromQL guidance.

### Grafana unified alerting

Grafana's unified alerting replaces legacy dashboard alerts. Rules are multi-stage:

**Rule structure (alert YAML):**
```yaml
- title: SRE-otel-collector-ExporterFailures-gt-0
  condition: C
  data:
    - refId: A
      queryType: ''
      model:
        expr: count(up{job="opentelemetry-collector"} == 1)
        datasourceUid: ${PROMETHEUS_DS}
    - refId: B
      queryType: ''
      relativeTimeRange: { from: 300, to: 0 }
      datasourceUid: __expr__
      model:
        type: reduce
        expression: A
        reducer: last
    - refId: C
      queryType: ''
      datasourceUid: __expr__
      model:
        type: threshold
        expression: B
        conditions:
          - evaluator: { params: [0], type: gt }
  for: 1m
  noDataState: Alerting
  execErrState: Alerting
  folderUID: <alerting-folder-uid>
  labels:
    severity: critical
    system: otel-collector
    alert_type: infra
    slack_0: platform-alerts
  annotations:
    __dashboardUid__: <dashboard-uid>
    __panelId__: "42"
    message: "OTel collector exporter failures detected"
    value: "{{ $values.C }}"
```

**Multi-stage flow:**
1. **Stage A (refId: A):** PromQL query
2. **Stage B (refId: B):** Reduce function (last/avg/min/max)
3. **Stage C (refId: C):** Threshold condition (gt/lt/within_range)
4. **condition: C** — points to the final refId that triggers the alert

**Labels drive routing and context:**
- `severity`: critical, warning, info
- `system`: service/component name (otel-collector, kafka, postgres, etc.)
- `alert_type`: infra, application, business
- **Routing labels**: `slack_0`, `webhook_0`, `pagerduty_0` (notification policy matches these)
- `usage`, `deployment_type`, `panel` (additional context)

**Annotations enrich alert detail:**
- `__dashboardUid__` + `__panelId__`: deep-link back to the source panel (ALWAYS include)
- `message`: human-readable summary
- `value`: template the firing metric value (`{{ $values.C }}`)
- `alert_type`: duplicate the label for message context

**Naming convention:**
```
SRE-<system>-<Condition>-<op>-<threshold>
```
Examples:
- `SRE-kafka-minion-TopicLagIncreasing-gt-0`
- `SRE-mongodb-ReplicaSetHealthDegraded-lt-3`
- `SRE-postgres-ConnectionPoolExhaustion-gt-80pct`

**Contact points and notification policies:**
- Contact points: `slack`, `webhook`, `pagerduty` (configured in Grafana UI or provisioning)
- Notification policies route by label matchers: `slack_0=platform-alerts` → Slack contact point
- Policies cascade: most-specific matcher wins

**Common PromQL for alerting:**
```promql
# Service availability (target count)
count(up{job="my-service"} == 1)

# Consumer lag (Kafka, per topic/group)
sum by (group_id, topic_name)(kminion_kafka_consumer_group_topic_partition_lag)

# Replica health (MongoDB)
mongodb_mongod_replset_member_health

# Error rate threshold
sum(rate(http_requests_total{status=~"5.."}[5m])) 
  / sum(rate(http_requests_total[5m])) > 0.01
```

See `references/unified-alerting.md` for provisioning alerts as code.

### Organization and provisioning

**Folder structure** (organize ~137 dashboards):
- **APM** — distributed tracing, span-metrics, service graphs
- **App Metrics** — application-level RED, business metrics
- **Platform / SRE-Automation** — k8s, kafka, mongodb, postgres, redis, temporal, otel-collector
- **Alerting** — alert summary dashboards, incident views

**Tagging conventions:**
- `sre-automation`, `autogen`, `kubernetes-mixin` — provisioned dashboards
- Product/team tags: `prometheus`, `kafka`, `temporal`, `cost`, `utilization`
- **Org-default provisioned tag** — marks dashboards deployed via CI/CD

**Dashboards as code (provisioning):**

Many production dashboards are tagged `autogen` or have an org-provisioned marker. This means they
are **provisioned from files**, not hand-edited in the UI. Editing a provisioned dashboard in the
UI is an **anti-pattern** — changes are lost on the next provisioning sync.

**Provisioning setup** (provisioning/dashboards/dashboards.yaml):
```yaml
apiVersion: 1
providers:
  - name: 'default'
    orgId: 1
    folder: 'Platform/SRE'
    type: file
    options:
      path: /var/lib/grafana/dashboards
```

Store dashboard JSON files in git under `dashboards/platform/` or similar. CI/CD syncs them to
Grafana's provisioning directory. Update a dashboard: edit the JSON in git, commit, redeploy.

**Datasource provisioning** (provisioning/datasources/prometheus.yaml):
```yaml
apiVersion: 1
datasources:
  - name: Prometheus-Prod
    type: prometheus
    access: proxy
    url: http://prometheus.monitoring.svc.cluster.local:9090
    isDefault: true
    jsonData:
      timeInterval: 30s
```

**Alert provisioning:**
Unified alerting rules can be provisioned via:
1. File provider (provisioning/alerting/rules.yaml)
2. API (`POST /api/v1/provisioning/alert-rules`)

Store alert YAML in git alongside dashboards. Notification policies and contact points provision
similarly.

See `references/provisioning-and-organization.md` for full workflow.

## Skeleton / example

Two complete worked examples live verbatim in
[red-dashboard-skeleton.md](references/red-dashboard-skeleton.md):

- **A minimal RED dashboard** for a web service — datasource/cluster/service template variables
  (cascading, multi-select), a request-rate panel (`rate(...) * 60` per-minute) and a p95 latency
  panel (`histogram_quantile` over span-metrics buckets), both driven by `${datasource}`.
- **A unified alert rule** — the three-stage query → reduce → threshold structure, a 5m `for`
  window, explicit `noDataState`, severity/routing labels, and `__dashboardUid__`/`__panelId__`
  annotations deep-linking the alert to its panel.

## Anti-patterns to avoid

- **Hardcoded datasource UID** in panel config instead of `${datasource}` variable. Breaks
  portability across Prometheus instances or environments. Always use a datasource template var.
  
- **Label typos in PromQL group-by** (e.g., `by (continer)` instead of `by (container)`). Silently
  changes cardinality and series matching. Lint queries before deploying.

- **Broad service matching via name regex** (e.g., `exported_service=~".*app.*|.*main.*"`) instead
  of precise label selectors or template variables. Fragile, slow, and matches unintended services.

- **Editing provisioned (autogen) dashboards in the UI**. Changes are overwritten on the next
  provisioning sync. Edit the JSON in git and redeploy.

- **Alerts without `__dashboardUid__` and `__panelId__` annotations**. Responders cannot jump to
  the offending panel. Always deep-link alerts to their source dashboard.

- **Missing `for` duration on noisy alerts**. A 5-minute `for` window prevents flapping on
  transient spikes. Tune per metric volatility.

- **No fallback `noDataState`**. If the metric disappears, should the alert fire (`Alerting`), stay
  quiet (`OK`), or go to a distinct state (`NoData`)? Choose intentionally.

- **Overly-granular label cardinality** in dashboards. Summing by `pod` across 1000 replicas
  creates 1000 series. Aggregate at service/deployment level unless debugging a specific pod.

## References

- [RED Dashboard Skeleton](references/red-dashboard-skeleton.md) — the complete worked RED
  dashboard JSON and three-stage unified alert rule from the Skeleton section
- [Dashboard JSON and Templating](references/dashboard-json-and-templating.md) — full JSON model
  anatomy, template variable types, cascading queries, multi-select, macros
- [RED Metrics Queries](references/red-metrics-queries.md) — NGINX ingress, OTel span-metrics, pod
  utilization PromQL; $__rate_interval vs $__range, histogram_quantile deep dive
- [Unified Alerting](references/unified-alerting.md) — multi-stage rule structure, label-based
  routing, contact points, notification policies, provisioning alerts as code
- [Provisioning and Organization](references/provisioning-and-organization.md) — dashboards-as-code
  workflow, file providers, folder/tag conventions, datasource provisioning
- [Repo Evidence](references/repo-evidence.md) — provenance and pattern sources
