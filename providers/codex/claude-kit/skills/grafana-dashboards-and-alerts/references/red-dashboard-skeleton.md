# Skeleton — minimal RED dashboard + a unified alert rule

Deep-dive reference for the `grafana-dashboards-and-alerts` skill. The conventions behind every
field here are explained in SKILL.md; these are the worked examples to copy and adapt.

A minimal RED dashboard for a web service (excerpt):

```json
{
  "title": "Service RED Metrics",
  "uid": "service-red-dashboard",
  "schemaVersion": 38,
  "tags": ["sre-automation", "red"],
  "time": { "from": "now-1h", "to": "now" },
  "templating": {
    "list": [
      {
        "name": "datasource",
        "type": "datasource",
        "query": "prometheus"
      },
      {
        "name": "cluster",
        "type": "query",
        "datasource": "${datasource}",
        "query": "label_values(cluster)"
      },
      {
        "name": "service",
        "type": "query",
        "datasource": "${datasource}",
        "query": "label_values(traces_spanmetrics_calls_total{cluster=\"$cluster\"}, \"service\")",
        "multi": true,
        "includeAll": true
      }
    ]
  },
  "panels": [
    {
      "type": "row",
      "title": "Request Rate",
      "gridPos": { "h": 1, "w": 24, "x": 0, "y": 0 },
      "collapsed": false
    },
    {
      "type": "timeseries",
      "title": "Requests per Minute",
      "gridPos": { "h": 8, "w": 12, "x": 0, "y": 1 },
      "datasource": { "type": "prometheus", "uid": "${datasource}" },
      "targets": [
        {
          "refId": "A",
          "expr": "sum(rate(traces_spanmetrics_calls_total{cluster=\"$cluster\", service=~\"$service\"}[$__rate_interval])) by (service) * 60",
          "legendFormat": "{{service}}"
        }
      ],
      "fieldConfig": {
        "defaults": { "unit": "reqpm" }
      }
    },
    {
      "type": "timeseries",
      "title": "p95 Latency",
      "gridPos": { "h": 8, "w": 12, "x": 12, "y": 1 },
      "datasource": { "type": "prometheus", "uid": "${datasource}" },
      "targets": [
        {
          "refId": "A",
          "expr": "histogram_quantile(0.95, sum(rate(traces_spanmetrics_latency_bucket{cluster=\"$cluster\", service=~\"$service\"}[$__rate_interval])) by (le, service))",
          "legendFormat": "{{service}}"
        }
      ],
      "fieldConfig": {
        "defaults": { "unit": "s" }
      }
    }
  ]
}
```

**Unified alert example:**

```yaml
- title: SRE-kafka-minion-TopicLagIncreasing-gt-0
  condition: C
  data:
    - refId: A
      model:
        expr: sum by (group_id, topic_name)(kminion_kafka_consumer_group_topic_partition_lag)
        datasourceUid: ${PROMETHEUS_DS}
    - refId: B
      datasourceUid: __expr__
      model:
        type: reduce
        expression: A
        reducer: last
    - refId: C
      datasourceUid: __expr__
      model:
        type: threshold
        expression: B
        conditions:
          - evaluator: { params: [0], type: gt }
  for: 5m
  noDataState: OK
  labels:
    severity: warning
    system: kafka
    slack_0: data-platform
  annotations:
    __dashboardUid__: kafka-consumer-lag
    __panelId__: "12"
    message: "Kafka consumer lag increasing for {{$labels.topic_name}}"
```
