# Dashboard JSON and Templating

This reference covers the Grafana dashboard JSON model structure and template variable patterns for building portable, reusable dashboards.

## Dashboard JSON model anatomy

Grafana dashboards are JSON documents. The model has evolved over time; common `schemaVersion` values in production: 30, 38, 41. Older dashboards can be migrated by opening them in the UI and re-saving.

### Top-level structure

```json
{
  "title": "Service Overview",
  "uid": "service-overview-dashboard",
  "tags": ["sre-automation", "red", "platform"],
  "schemaVersion": 38,
  "version": 12,
  "time": {
    "from": "now-1h",
    "to": "now"
  },
  "timepicker": {
    "refresh_intervals": ["5s", "10s", "30s", "1m", "5m", "15m"],
    "time_options": ["5m", "15m", "1h", "6h", "12h", "24h", "2d", "7d", "30d"]
  },
  "templating": { "list": [ /* template variables */ ] },
  "annotations": { "list": [ /* event annotations */ ] },
  "links": [ /* dashboard links */ ],
  "panels": [ /* visualization panels */ ],
  "refresh": "30s",
  "editable": true,
  "fiscalYearStartMonth": 0
}
```

**Key fields:**
- `title`: Dashboard display name
- `uid`: Unique identifier (used for deep-linking alerts, cross-references). Stable across renames.
- `tags[]`: Organizational tags (folder filtering, search). Common: `sre-automation`, `autogen`, `kubernetes-mixin`, product names.
- `schemaVersion`: Grafana model version (UI auto-migrates on save)
- `time`: Default time range. Use relative ranges (`now-1h`) for reusability.
- `templating.list[]`: Template variables (see Template Variables section below)
- `annotations.list[]`: Event overlays (deployments, incidents)
- `links[]`: Cross-links to related dashboards
- `panels[]`: Visualization elements (timeseries, table, stat, row, nodeGraph)
- `refresh`: Auto-refresh interval (`5s`, `30s`, `1m`, `""` for off)

### Panel structure

Panels are the visualization building blocks. Each panel occupies a grid position and queries one or more datasources.

```json
{
  "type": "timeseries",  // or "table", "stat", "row", "nodeGraph", "heatmap", "gauge"
  "id": 42,
  "title": "Request Rate",
  "gridPos": {
    "h": 8,   // height in grid units
    "w": 12,  // width (24 = full row)
    "x": 0,   // column offset
    "y": 1    // row offset
  },
  "datasource": {
    "type": "prometheus",
    "uid": "${datasource}"  // ALWAYS use a template variable
  },
  "targets": [
    {
      "refId": "A",
      "expr": "sum(rate(http_requests_total{service=\"$service\"}[$__rate_interval]))",
      "legendFormat": "{{method}} {{status}}",
      "datasource": { "type": "prometheus", "uid": "${datasource}" }
    }
  ],
  "fieldConfig": {
    "defaults": {
      "unit": "reqps",
      "color": { "mode": "palette-classic" },
      "thresholds": {
        "mode": "absolute",
        "steps": [
          { "value": null, "color": "green" },
          { "value": 80, "color": "red" }
        ]
      },
      "custom": {
        "lineInterpolation": "linear",
        "fillOpacity": 10,
        "showPoints": "never"
      }
    },
    "overrides": []  // per-series overrides
  },
  "options": {
    "legend": { "displayMode": "list", "placement": "bottom" },
    "tooltip": { "mode": "multi" }
  }
}
```

**Panel types:**
- `timeseries`: Line/area charts (replaces legacy "graph" panel)
- `table`: Tabular data with column aggregations
- `stat`: Single-value metric (current/min/max/avg)
- `row`: Collapsible grouping container (no data)
- `nodeGraph`: Service graph visualization (Tempo distributed tracing)
- `heatmap`: Bucketed histogram over time
- `gauge`: Dial or horizontal bar

**gridPos layout:**
Grid is 24 columns wide. Heights are in arbitrary units (typically 1 unit ≈ 30px). Panels stack top-to-bottom, left-to-right by `y` then `x`.

**datasource selection:**
ALWAYS use a template variable:
```json
"datasource": { "type": "prometheus", "uid": "${datasource}" }
```
NEVER hardcode a UID like `"uid": "abc123def456"` — this breaks portability across environments.

**fieldConfig:**
- `unit`: Grafana units (reqps, s, ms, bytes, percent, decbytes, etc.)
- `thresholds`: Color coding by value
- `custom`: Panel-type-specific settings (line style, fill, stacking)
- `overrides[]`: Per-series styling (by field name or regex)

### Query targets (Prometheus)

```json
{
  "refId": "A",
  "expr": "sum(rate(http_requests_total{service=\"$service\"}[$__rate_interval])) by (method, status)",
  "legendFormat": "{{method}} {{status}}",
  "instant": false,
  "range": true,
  "intervalFactor": 1,
  "datasource": { "type": "prometheus", "uid": "${datasource}" }
}
```

**Key fields:**
- `refId`: Query identifier (A, B, C...). Used in expressions and transforms.
- `expr`: PromQL query. Use template variables (`$service`) and macros (`$__rate_interval`).
- `legendFormat`: Series label template. Use `{{label_name}}` to interpolate Prometheus labels.
- `instant`: Query instant value (stat panels)
- `range`: Query time range (timeseries panels)

**PromQL macros:**
- `$__rate_interval`: Adaptive rate window (4× scrape interval). Use in `rate()` and `irate()`.
- `$__range`: Dashboard's current time range (e.g., `1h` → `3600s`). Use in `increase()`.
- `$__interval`: Auto-calculated aggregation step. Use in `avg_over_time()` or `max_over_time()`.
- `$__rate_interval_ms`, `$__range_s`, `$__range_ms`: Variant formats.

### Row panels

Rows group related panels and can collapse/expand to save vertical space.

```json
{
  "type": "row",
  "id": 10,
  "title": "Request Latency",
  "gridPos": { "h": 1, "w": 24, "x": 0, "y": 0 },
  "collapsed": false,
  "panels": []  // Empty if not collapsed; contains child panels if collapsed
}
```

Collapsed rows store their child panels in the `panels[]` array. Expanded rows have `panels: []` and child panels appear as top-level entries in the dashboard's `panels[]` with `y` positions immediately following the row.

### nodeGraph panels (Tempo service graph)

Visualize distributed trace topology from Tempo's service graph.

```json
{
  "type": "nodeGraph",
  "title": "Service Graph",
  "gridPos": { "h": 12, "w": 24, "x": 0, "y": 0 },
  "datasource": { "type": "tempo", "uid": "${tempo_datasource}" },
  "targets": [
    {
      "refId": "A",
      "queryType": "serviceMap"
    }
  ],
  "options": {
    "nodes": {
      "mainStatUnit": "reqps",
      "secondaryStatUnit": "ms"
    },
    "edges": {
      "mainStatUnit": "reqps",
      "secondaryStatUnit": "ms"
    }
  }
}
```

The service graph is auto-generated by Tempo's metrics-generator from trace spans. Nodes are services; edges are request flows.

## Template variables

Template variables make dashboards dynamic and reusable. They appear as dropdowns at the top of the dashboard.

### Variable types

1. **Datasource** (always include for portability)
2. **Query** (label_values from metrics)
3. **Custom** (static list of options)
4. **Constant** (hidden value reused in queries)
5. **Interval** (time window selector)
6. **Textbox** (user-entered value)
7. **Ad hoc filters** (dynamic label filters)

### 1. Datasource variable (the golden rule)

ALWAYS include a datasource selector to make dashboards portable across Prometheus instances (prod/staging/dev, different clusters).

```json
{
  "name": "datasource",
  "type": "datasource",
  "label": "Datasource",
  "query": "prometheus",
  "current": {
    "text": "Prometheus-Prod",
    "value": "abc123"
  },
  "hide": 0,
  "includeAll": false,
  "multi": false,
  "options": [],
  "refresh": 1,
  "regex": "",
  "skipUrlSync": false
}
```

**Usage in panels:**
```json
"datasource": { "type": "prometheus", "uid": "${datasource}" }
```

**Why:** Hardcoding a datasource UID (`"uid": "abc123"`) breaks the dashboard when deploying to a different Grafana instance or environment. The `$datasource` variable lets users switch datasources without editing JSON.

### 2. Query variables (label_values)

Extract dynamic lists from Prometheus label values.

**Top-level dimension (e.g., cluster):**
```json
{
  "name": "cluster",
  "type": "query",
  "label": "Cluster",
  "datasource": { "uid": "${datasource}", "type": "prometheus" },
  "query": "label_values(cluster)",
  "current": {},
  "hide": 0,
  "includeAll": true,
  "multi": false,
  "options": [],
  "refresh": 2,  // 2 = on time range change
  "regex": "",
  "skipUrlSync": false,
  "sort": 1  // 1 = alphabetical ascending
}
```

**Cascading dimension (filters on parent):**
```json
{
  "name": "service",
  "type": "query",
  "label": "Service",
  "datasource": { "uid": "${datasource}", "type": "prometheus" },
  "query": "label_values(traces_spanmetrics_calls_total{cluster=\"$cluster\"}, \"service\")",
  "current": {},
  "hide": 0,
  "includeAll": true,
  "multi": true,  // Allow selecting multiple services
  "options": [],
  "refresh": 2,
  "regex": "",
  "skipUrlSync": false,
  "sort": 1
}
```

**How cascading works:**
When the user changes `$cluster`, Grafana re-queries the `service` variable with the new cluster value. This filters the service list to only those present in the selected cluster.

**Query syntax variants:**
```promql
# All unique values of a label across all metrics
label_values(label_name)

# Values of a label from a specific metric
label_values(metric_name, "label_name")

# Filtered by another label
label_values(metric_name{label1="value"}, "label2")

# With a metric filter
label_values(up{job=~".*api.*"}, "instance")
```

**Multi-select and All:**
```json
{
  "multi": true,        // Allow selecting multiple values
  "includeAll": true,   // Add an "All" option
  "allValue": ".*"      // Regex value for "All" (used in =~ matchers)
}
```

When `allValue: ".*"`, the variable expands to a regex that matches everything:
```promql
# User selects "All"
{service=~"$service"}  →  {service=~".*"}

# User selects ["api", "worker"]
{service=~"$service"}  →  {service=~"api|worker"}
```

### 3. Custom variables

Static lists for structured filters.

```json
{
  "name": "span_kind",
  "type": "custom",
  "label": "Span Kind",
  "query": "Web : SPAN_KIND_SERVER, Consumer : SPAN_KIND_CONSUMER, Internal : SPAN_KIND_INTERNAL",
  "current": {},
  "hide": 0,
  "includeAll": false,
  "multi": false,
  "options": [
    { "text": "Web", "value": "SPAN_KIND_SERVER", "selected": true },
    { "text": "Consumer", "value": "SPAN_KIND_CONSUMER", "selected": false },
    { "text": "Internal", "value": "SPAN_KIND_INTERNAL", "selected": false }
  ],
  "skipUrlSync": false
}
```

The `query` field is a comma-separated list of `display : value` pairs. The UI shows `display`, queries use `value`.

### 4. Constant variables

Hidden values reused across queries (DRY for common filters).

```json
{
  "name": "namespace",
  "type": "constant",
  "label": "Namespace",
  "query": "production",
  "current": { "value": "production", "text": "production" },
  "hide": 2  // 2 = hide variable entirely
}
```

Use in queries:
```promql
kube_pod_info{namespace="$namespace"}
```

### 5. Interval variables

Let users pick aggregation windows.

```json
{
  "name": "resolution",
  "type": "interval",
  "label": "Resolution",
  "query": "1m,5m,15m,1h",
  "current": { "value": "5m", "text": "5m" },
  "auto": true,
  "auto_count": 30,
  "auto_min": "10s"
}
```

Use in queries:
```promql
avg_over_time(metric[$resolution])
```

### Template variable syntax in queries

**Simple substitution:**
```promql
{service="$service"}
```

**Regex matching (for multi-select):**
```promql
{service=~"$service"}
```

If user selects `["api", "worker"]`, this expands to:
```promql
{service=~"api|worker"}
```

**All selected (with allValue):**
```promql
{service=~"$service"}  →  {service=~".*"}
```

**Pipe formatting (for label lists):**
```promql
sum by ($__all_variables) (metric)
```

**Glob formatting (for filenames):**
```promql
${var:glob}
```

### Refresh behavior

`refresh` field controls when the variable re-queries:
- `0`: Never (static)
- `1`: On dashboard load
- `2`: On time range change

Cascading variables (those filtering on other variables) should use `refresh: 2` to update when dependencies change.

### Variable ordering

Variables appear left-to-right in the UI in the order they're defined in `templating.list[]`. Put the datasource selector first, then top-level dimensions (cluster), then cascading dimensions (service).

## Full example: APM dashboard template variables

This is the proven pattern from production APM dashboards. It provides maximum flexibility while maintaining performance.

```json
{
  "templating": {
    "list": [
      {
        "name": "datasource",
        "type": "datasource",
        "label": "Datasource",
        "query": "prometheus",
        "current": {},
        "hide": 0,
        "multi": false,
        "refresh": 1
      },
      {
        "name": "cluster",
        "type": "query",
        "label": "Cluster",
        "datasource": { "uid": "${datasource}", "type": "prometheus" },
        "query": "label_values(cluster)",
        "current": {},
        "hide": 0,
        "includeAll": true,
        "multi": false,
        "refresh": 2,
        "sort": 1
      },
      {
        "name": "service",
        "type": "query",
        "label": "Service",
        "datasource": { "uid": "${datasource}", "type": "prometheus" },
        "query": "label_values(traces_spanmetrics_calls_total{cluster=\"$cluster\"}, \"service\")",
        "current": {},
        "hide": 0,
        "includeAll": true,
        "multi": true,
        "allValue": ".*",
        "refresh": 2,
        "sort": 1
      },
      {
        "name": "span_kind",
        "type": "custom",
        "label": "Span Kind",
        "query": "Web : SPAN_KIND_SERVER, Consumer : SPAN_KIND_CONSUMER, Internal : SPAN_KIND_INTERNAL",
        "current": {},
        "hide": 0,
        "multi": false,
        "options": [
          { "text": "Web", "value": "SPAN_KIND_SERVER", "selected": true },
          { "text": "Consumer", "value": "SPAN_KIND_CONSUMER", "selected": false },
          { "text": "Internal", "value": "SPAN_KIND_INTERNAL", "selected": false }
        ]
      }
    ]
  }
}
```

**Flow:**
1. User selects datasource (Prometheus-Prod / Prometheus-Dev)
2. `cluster` variable queries `label_values(cluster)` from the selected datasource
3. User selects cluster
4. `service` variable re-queries, filtering by `cluster="$cluster"`
5. User selects one or more services
6. Panels use `{cluster="$cluster", service=~"$service", span_kind="$span_kind"}` in queries

This pattern is **the foundation of portable, reusable dashboards**. Every multi-environment dashboard should follow it.
