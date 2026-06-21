# Repo Evidence: Pattern Provenance

This skill is grounded in conventions derived from a **production multi-cluster Grafana observability deployment**, not theoretical best practices. This document records the provenance of each pattern to maintain traceability.

## Instance shape

**Scale:**
- ~137 dashboards across multiple folders
- 150 unified alerting rules
- Multi-cluster deployment (production, staging, development environments)

**Datasource stack:**
- **Prometheus** (multiple instances) — primary metrics datasource
- **Tempo** — distributed traces, service graph, span-metrics
- **Pyroscope** — continuous profiling
- **Stackdriver / Google Cloud Monitoring** — managed GCP services (CloudSQL, Redis, NAT, Cloud Run, firewall)
- **Google Cloud Logging** — log aggregation
- **Elasticsearch** — log search
- **Infinity datasource** (yesoreyeram-infinity-datasource) — JSON/CSV/REST API sources

**Dashboard organization:**
- Folders: APM, App Metrics, Platform/SRE-Automation, Alerting, General
- Many dashboards tagged `autogen` or with an org-default provisioned tag → dashboards are provisioned as code, not hand-edited in the UI

**Alert organization:**
- Unified alerting rules stored in Grafana (not Prometheus-managed)
- Label-based routing (slack_0, webhook_0, pagerduty_0 routing labels)
- Contact points: Slack, webhook, PagerDuty
- Naming convention: `SRE-<system>-<Condition>-<op>-<threshold>`

## Pattern sources

### Dashboard JSON model and template variables

**Source:** Dashboard exports from the production instance (schemaVersions 30, 38, 41).

**Key archetype:** The **APM dashboard** template variable pattern:
- `$datasource` variable of type "datasource" (query: `prometheus`)
- Cascading `$cluster` → `$service` hierarchy via `label_values()` queries
- `$service` filters on `cluster="$cluster"` (dependent variable, `refresh: 2`)
- Custom `$span_kind` variable for SPAN_KIND_SERVER/CONSUMER/INTERNAL filtering
- Multi-select `$service` with `allValue: ".*"` for regex matching

This pattern is the **foundation of portable dashboards** and appears consistently across the APM folder.

**Evidence fields:**
- `datasource: { type: "prometheus", uid: "${datasource}" }` in panels (never hardcoded UIDs in production dashboards)
- `templating.list[]` with `type: datasource`, `type: query`, `type: custom`
- Cascade via `query: label_values(traces_spanmetrics_calls_total{cluster="$cluster"}, "service")`

### RED metrics PromQL (three sources)

**Source 1: NGINX Ingress Controller (App Metrics folder)**

Dashboards monitoring user-facing HTTP traffic via NGINX ingress. Common metrics:
- `nginx_ingress_controller_requests{exported_service=~"$service"}`
- `nginx_ingress_controller_request_duration_seconds_bucket{exported_service=~"$service", le="..."}`
- `nginx_ingress_controller_request_duration_seconds_sum` / `_count`

**Queries observed:**
- Throughput: `sum(irate(...[$__rate_interval])) by (exported_service)`
- Percentiles: `histogram_quantile(0.95, sum(rate(..._bucket[$__rate_interval])) by (le))`
- Total over range: `sum(increase(...[$__range])) by (exported_service)`

**Source 2: OpenTelemetry span-metrics (APM folder)**

Tempo metrics-generator derives RED metrics from trace spans. Common metrics:
- `traces_spanmetrics_calls_total{cluster="...", service="...", span_kind="...", status_code="..."}`
- `traces_spanmetrics_latency_bucket{cluster="...", service="...", span_kind="...", le="..."}`

**Queries observed:**
- Rate (req/min): `sum(rate(traces_spanmetrics_calls_total{...}[$__rate_interval])) by (span_kind) * 60`
- Latency p95: `histogram_quantile(0.95, sum(rate(traces_spanmetrics_latency_bucket{...}[$__rate_interval])) by (le))`
- Error ratio: `sum(increase(...{status_code="STATUS_CODE_ERROR"}[$__range])) / sum(increase(...[$__range]))`
- Per-operation breakdown: `sum(rate(...[$__range])) by (span_name)`

**Source 3: Pod/container utilization (Platform/SRE-Automation folder)**

Kubernetes resource metrics from kube-state-metrics + cAdvisor. Common metrics:
- `container_cpu_usage_seconds_total{container=~"$container", container!="POD"}`
- `kube_pod_container_resource_limits_cpu_cores{container=~"$container"}`
- `container_memory_usage_bytes{container=~"$container", container!="POD"}`
- `kube_pod_container_status_restarts_total{container=~"$container"}`

**Queries observed:**
- CPU vs limit: `sum(rate(container_cpu_usage_seconds_total{...}[$__rate_interval])) by (container, pod) / sum(kube_pod_container_resource_limits_cpu_cores{...}) by (container, pod)`
- Memory vs limit: `sum(container_memory_usage_bytes{...}) by (container, pod) / sum(kube_pod_container_resource_limits_memory_bytes{...}) by (container, pod)`
- Restarts: `round(sum(increase(kube_pod_container_status_restarts_total{...}[$__rate_interval])) by (container, pod))`

**Key macros:** `$__rate_interval`, `$__range` (ubiquitous across all dashboards).

### Unified alerting (150 rules)

**Source:** Alert rule exports from the production instance.

**Multi-stage structure observed:**
- Stage A: PromQL query (`datasourceUid: <prometheus-uid>`)
- Stage B: Reduce (`datasourceUid: __expr__`, `model.type: reduce`, `reducer: last` or `avg`)
- Stage C: Threshold (`model.type: threshold`, `conditions: [{ evaluator: { params: [X], type: gt }}]`)
- `condition: C` points to final refId

**Common PromQL in alerts:**
- Service availability: `count(up{job="opentelemetry-collector"} == 1)`
- Consumer lag (Kafka): `sum by (group_id, topic_name)(kminion_kafka_consumer_group_topic_partition_lag)`
- Replica health (MongoDB): `mongodb_mongod_replset_member_health`
- Error rate: `sum(rate(http_requests_total{status=~"5.."}[5m])) / sum(rate(http_requests_total[5m]))`

**Labels observed:**
- Standard: `severity`, `system`, `alert_type`, `usage`, `deployment_type`, `panel`
- Routing: `slack_0`, `webhook_0`, `pagerduty_0` (label-based notification policy matching)

**Annotations observed:**
- `__dashboardUid__`, `__panelId__` (deep-link to source panel)
- `message` (template with `{{ $labels.label_name }}`, `{{ $values.C }}`)
- `value`, `alert_type` (enrichment)

**Naming convention observed:**
- `SRE-otel-collector-ExporterFailures-gt-0`
- `SRE-kafka-minion-TopicLagIncreasing-gt-0`
- `SRE-mongodb-ReplicaSetHealthDegraded-lt-3`

Pattern: `SRE-<system>-<Condition>-<op>-<threshold>` (consistent across 150 rules).

**for durations:** 1m, 5m, 30m (varies by metric volatility).

**noDataState:** Mix of `Alerting`, `OK`, `NoData` (intentional per alert).

### Provisioning and organization

**Evidence:**
- Many dashboards tagged `autogen` or with an org-default provisioned tag
- Folder structure: APM, App Metrics, Platform/SRE-Automation, Alerting
- Tag taxonomy: `sre-automation`, `kubernetes-mixin`, `prometheus`, `kafka`, `temporal`, `cost`, `utilization`

**Interpretation:** Dashboards are provisioned from code (file provider or API), not hand-edited in the UI. Editing a provisioned dashboard in the UI is an anti-pattern (changes lost on redeploy).

**Provisioning workflow inferred:**
1. Dashboard JSON stored in git (e.g., `dashboards/platform/kafka-overview.json`)
2. CI/CD syncs to Grafana provisioning directory (`/var/lib/grafana/dashboards/`)
3. Grafana file provider reloads dashboards every `updateIntervalSeconds`
4. Updates to dashboards: edit JSON in git → commit → redeploy

**Alert provisioning inferred:**
- Unified alerting rules provisioned via file provider (provisioning/alerting/rules.yaml) or API
- Contact points and notification policies provisioned similarly

### Anti-patterns observed

These are **real issues** found in the production instance, genericized for teaching:

1. **Hardcoded datasource UID:**
   Found in a small minority of dashboards (likely hand-edited before provisioning workflow was enforced). Example: `"datasource": { "type": "prometheus", "uid": "abc123def456" }` instead of `"uid": "${datasource}"`.

2. **Label typos in PromQL group-by:**
   Example: `by (continer)` instead of `by (container)`. Silently changes cardinality and series matching. Caught during dashboard review.

3. **Broad service matching via name regex:**
   Example: `exported_service=~".*app.*|.*main.*"` instead of precise `exported_service="$service"` or `exported_service=~"service-a|service-b"`. Fragile (matches unintended services) and slow (high cardinality).

4. **Editing provisioned dashboards in the UI:**
   Observed when a developer edited an `autogen`-tagged dashboard in the UI, saved, and lost changes on the next redeploy. Now enforced via `allowUiUpdates: false`.

5. **Alerts without `__dashboardUid__`/`__panelId__` annotations:**
   Early alerts lacked deep-linking. Responders had to manually search for the relevant dashboard. Now required in the alert provisioning template.

## What was NOT genericized

These are **public open-source or vendor-agnostic names** that remain in the skill:

- **Product names:** Grafana, Prometheus, Tempo, Pyroscope, Loki, Stackdriver, Google Cloud Monitoring, Elasticsearch, Infinity datasource
- **Metric names:** `nginx_ingress_controller_*`, `traces_spanmetrics_*`, `container_*`, `kube_pod_*`, `otelcol_*`, `kminion_*`, `kafka_*`, `mongodb_*` (all from open-source exporters)
- **PromQL macros:** `$__rate_interval`, `$__range`, `$__interval` (Grafana built-ins)
- **Label/routing conventions:** `severity`, `system`, `alert_type`, `slack_0`, `webhook_0`, `pagerduty_0` (generic patterns)
- **Contact point types:** `slack`, `webhook`, `pagerduty` (Grafana native integrations)

## Genericization transformations applied

| Original (internal) | Genericized (public) |
|---------------------|----------------------|
| Hostnames (grafana.internal.example) | `https://grafana.example.com` or relative `/api/...` paths |
| Service identifiers (internal service names) | `$service`, `my-service`, `"$service"` |
| Namespace identifiers (internal namespaces) | `$namespace`, `production`, `"$namespace"` |
| GCP project IDs (internal project names) | `$project`, `<gcp-project>` |
| Hardcoded datasource UID (internal UID) | Shown ONLY as anti-pattern; correct form uses `${datasource}` |
| Org-default dashboard tag (internal tag name) | Referred to generically as "org-default provisioned tag" |
| Internal folder acronyms | Generic names: APM, App Metrics, Platform/SRE, Alerting |

**No internal identifiers remain.** All conventions are taught via generic placeholders or public exporter/product names.

## Confidence levels

**High confidence (observed in ≥80% of relevant dashboards/alerts):**
- `$datasource` variable pattern (APM, App Metrics, Platform folders)
- Cascading `$cluster` → `$service` template variables (APM folder)
- `$__rate_interval` and `$__range` macros (ubiquitous)
- Multi-stage alert structure (query → reduce → threshold) (all 150 rules)
- Label-based routing (`slack_0`, `webhook_0`, `pagerduty_0`) (all alerts)
- Dashboard deep-linking (`__dashboardUid__`, `__panelId__`) (all recent alerts)
- Naming convention `SRE-<system>-<Condition>-<op>-<threshold>` (all alerts)

**Medium confidence (observed in 30-80% of relevant dashboards):**
- NGINX ingress PromQL patterns (App Metrics folder)
- OTel span-metrics PromQL patterns (APM folder)
- Pod utilization PromQL patterns (Platform/SRE folder)
- `autogen` or org-provisioned tags (many but not all dashboards)

**Low confidence (inferred from instance structure, not directly observed):**
- Exact provisioning workflow (file provider config not exported; inferred from `autogen` tags and folder structure)
- Datasource provisioning details (datasource config not exported; inferred from multi-environment deployment pattern)

## Pattern stability

All patterns in this skill are **stable production conventions** (in use for ≥6 months across 137 dashboards and 150 alerts). They are not experimental or one-off solutions.

**Temporal coverage:** Patterns reflect the instance state as of the skill authoring date. Grafana versions represented: schemaVersions 30, 38, 41 (Grafana 8.x → 10.x evolution).

## Cross-references

- **`observability-and-logging` skill** — covers emitting the metrics these dashboards visualize (Prometheus exporters, structured logging, trace instrumentation). Complementary to this skill.
- **`gcp-cloud-run-github-actions` skill** — includes Google Cloud Monitoring datasource patterns for managed services (CloudSQL, Redis, NAT).

## Notes for future skill authors

If building a similar skill from a different Grafana instance:

1. **Export representative dashboards** from each folder (APM, App Metrics, Platform/SRE).
2. **Export alert rules** (Alerting → Alert rules → Export).
3. **Capture datasource config** (if accessible) to document multi-datasource patterns.
4. **Genericize ALL internal identifiers** (hostnames, service names, project IDs, org tags, team names, internal acronyms).
5. **Keep public names** (Grafana, Prometheus, Tempo, metric names from open-source exporters, PromQL macros, contact point types).
6. **Record pattern frequency** (how many dashboards/alerts use each pattern) to distinguish core conventions from one-offs.
7. **Document anti-patterns** (observed issues, not theoretical) to teach what NOT to do.

This skill's strength is **grounding in real usage**, not Grafana API documentation. Preserve that by citing observed patterns, not idealizations.
