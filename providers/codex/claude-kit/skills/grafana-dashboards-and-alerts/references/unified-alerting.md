# Unified Alerting

Grafana's unified alerting replaces legacy dashboard alerts with a multi-datasource, label-based alerting system. This reference covers rule structure, label-based routing, contact points, and provisioning alerts as code.

## Unified alerting vs legacy alerts

**Legacy (pre-Grafana 8):**
- Alerts tied to dashboard panels
- Single datasource per alert
- Limited routing (email only)

**Unified (Grafana 8+):**
- Alerts independent of dashboards (though often linked via annotations)
- Multi-datasource support (Prometheus, Loki, cloud providers)
- Label-based routing to multiple contact points (Slack, PagerDuty, webhook)
- Grafana-managed rules (stored in Grafana) or datasource-managed rules (stored in Prometheus/Loki)

This guide focuses on **Grafana-managed rules**, which are provisioned and routed by Grafana.

## Alert rule structure

Unified alerts are **multi-stage queries**: query → reduce → threshold.

### Basic anatomy (YAML)

```yaml
- uid: sre-otel-collector-exporter-failures
  title: SRE-otel-collector-ExporterFailures-gt-0
  condition: C
  data:
    - refId: A
      queryType: ''
      relativeTimeRange:
        from: 300
        to: 0
      datasourceUid: ${PROMETHEUS_DS}
      model:
        expr: count(up{job="opentelemetry-collector"} == 1)
        refId: A
    - refId: B
      queryType: ''
      relativeTimeRange:
        from: 300
        to: 0
      datasourceUid: __expr__
      model:
        type: reduce
        expression: A
        reducer: last
        refId: B
    - refId: C
      queryType: ''
      datasourceUid: __expr__
      model:
        type: threshold
        expression: B
        conditions:
          - evaluator:
              params: [0]
              type: gt
        refId: C
  for: 1m
  noDataState: Alerting
  execErrState: Alerting
  folderUID: alerting-folder-uid
  ruleGroup: otel-collector-alerts
  labels:
    severity: critical
    system: otel-collector
    alert_type: infra
    usage: platform
    deployment_type: kubernetes
    slack_0: platform-alerts
  annotations:
    __dashboardUid__: otel-collector-dashboard
    __panelId__: "42"
    message: "OTel collector exporter failures detected"
    value: "{{ $values.C }}"
    alert_type: infra
```

### Multi-stage flow

1. **Stage A (refId: A):** Execute PromQL query
   ```yaml
   datasourceUid: ${PROMETHEUS_DS}  # Reference to Prometheus datasource
   model:
     expr: count(up{job="opentelemetry-collector"} == 1)
   ```

2. **Stage B (refId: B):** Reduce to scalar
   ```yaml
   datasourceUid: __expr__  # Special datasource for Grafana expressions
   model:
     type: reduce
     expression: A
     reducer: last  # or avg, min, max, sum
   ```

3. **Stage C (refId: C):** Threshold condition
   ```yaml
   datasourceUid: __expr__
   model:
     type: threshold
     expression: B
     conditions:
       - evaluator:
           params: [0]       # Threshold value
           type: gt          # gt, lt, within_range, outside_range
   ```

4. **condition: C** — Points to the final refId that triggers the alert

### Field reference

**Top-level:**
- `uid`: Unique identifier (stable across renames)
- `title`: Human-readable name. Use the naming convention (see Naming Convention section).
- `condition`: The refId that triggers the alert (typically the final stage)
- `data[]`: Multi-stage query pipeline
- `for`: How long the condition must be true before firing (e.g., `1m`, `5m`, `30m`)
- `noDataState`: What to do if the query returns no data (`Alerting`, `OK`, `NoData`)
- `execErrState`: What to do if the query fails (`Alerting`, `OK`, `Error`)
- `folderUID`: Folder containing this rule (organize by system/team)
- `ruleGroup`: Group name (alerts in the same group are evaluated together)
- `labels{}`: Key-value pairs for routing and context (see Labels section)
- `annotations{}`: Rich metadata attached to firing alerts (see Annotations section)

**relativeTimeRange:**
- `from`: Seconds back from now (e.g., `300` = 5 minutes ago)
- `to`: Seconds back from now (e.g., `0` = now)

This defines the time window for the query. Example: `from: 600, to: 0` queries the last 10 minutes.

**Reduce types:**
- `last`: Most recent value
- `avg`: Average over time range
- `min`: Minimum value
- `max`: Maximum value
- `sum`: Sum of all values

**Threshold evaluator types:**
- `gt`: Greater than (value > threshold)
- `lt`: Less than (value < threshold)
- `within_range`: Value inside [min, max] (params: [min, max])
- `outside_range`: Value outside [min, max]

## Labels

Labels drive alert routing and provide context. They are key-value pairs attached to every alert instance.

### Standard labels

**Severity:**
```yaml
severity: critical  # or warning, info
```

**System/component:**
```yaml
system: otel-collector  # or kafka, postgres, api, worker, etc.
```

**Alert type:**
```yaml
alert_type: infra  # or application, business
```

**Additional context:**
```yaml
usage: platform          # or customer-facing, internal
deployment_type: kubernetes  # or cloud-run, vm
panel: requests-per-second  # Panel title (for UI deep-linking context)
```

### Routing labels

Notification policies match on these labels to route alerts to contact points.

**Slack:**
```yaml
slack_0: platform-alerts  # or app-alerts, data-alerts, oncall
```

**Webhook:**
```yaml
webhook_0: incident-webhook
```

**PagerDuty:**
```yaml
pagerduty_0: oncall-rotation
```

**Convention:** Use `_0`, `_1`, `_2` suffixes for multiple contact points of the same type.

### Routing example

```yaml
# Alert labels
labels:
  severity: critical
  system: kafka
  slack_0: data-platform
  pagerduty_0: oncall
```

**Notification policy (configured in Grafana UI or provisioning):**
```yaml
- matchers:
    - slack_0 = data-platform
  receiver: slack-data-platform
  continue: true  # Keep evaluating policies (send to multiple)

- matchers:
    - pagerduty_0 = oncall
  receiver: pagerduty-oncall
```

This alert fires → Grafana matches `slack_0=data-platform` → sends to Slack → continues → matches `pagerduty_0=oncall` → pages oncall.

## Annotations

Annotations enrich alert notifications with context and deep-links. They are **not** used for routing.

### Dashboard deep-linking (ALWAYS include)

```yaml
annotations:
  __dashboardUid__: service-red-dashboard
  __panelId__: "12"
```

These special annotations create a deep-link in the alert notification: "View panel →". Responders can jump directly to the offending panel.

**How to find these:**
1. Open the dashboard in Grafana
2. Note the UID in the URL: `https://grafana.example.com/d/<dashboard-uid>/...`
3. Click the panel title → View → Copy Link → extract `panelId=<id>` from the URL

### Message template

```yaml
annotations:
  message: "OTel collector exporter failures detected on {{ $labels.instance }}"
```

**Template variables:**
- `{{ $labels.label_name }}`: Prometheus label value
- `{{ $values.refId }}`: Query result (e.g., `{{ $values.C }}` for the threshold stage)
- `{{ $value }}`: Shorthand for the condition's value

### Value display

```yaml
annotations:
  value: "{{ $values.C }}"
```

Shows the numeric value that triggered the alert (e.g., "42 requests failing").

### Alert type (duplicate label)

```yaml
annotations:
  alert_type: infra
```

Duplicating the `alert_type` label in annotations makes it visible in the alert message (some notification backends don't show labels).

### Full example

```yaml
annotations:
  __dashboardUid__: kafka-consumer-lag
  __panelId__: "8"
  message: "Kafka consumer lag increasing for topic {{ $labels.topic_name }}, group {{ $labels.group_id }}"
  value: "{{ $values.C }} messages behind"
  alert_type: infra
  runbook_url: "https://wiki.example.com/runbooks/kafka-lag"
```

## Naming convention

Use a consistent, grep-able naming scheme:

```
SRE-<system>-<Condition>-<op>-<threshold>
```

**Examples:**
- `SRE-otel-collector-ExporterFailures-gt-0`
- `SRE-kafka-minion-TopicLagIncreasing-gt-0`
- `SRE-mongodb-ReplicaSetHealthDegraded-lt-3`
- `SRE-postgres-ConnectionPoolExhaustion-gt-80pct`
- `SRE-api-ErrorRate-gt-1pct`

**Components:**
- `SRE`: Prefix (or `App`, `Business` for non-infra alerts)
- `<system>`: Component name (lowercase-with-hyphens)
- `<Condition>`: PascalCase description (ExporterFailures, TopicLagIncreasing)
- `<op>`: Operator (gt, lt, eq, ne)
- `<threshold>`: Value (0, 1pct, 80pct, 3)

**Why this helps:**
- Grep by system: `grep "SRE-kafka" alert-rules.yaml`
- Grep by condition: `grep "ErrorRate" alert-rules.yaml`
- Understand the alert without reading the query

## Common PromQL for alerting

### Service availability (target count)

```promql
count(up{job="my-service"} == 1)
```

Alert when fewer than N instances are up:
```yaml
conditions:
  - evaluator:
      params: [3]
      type: lt
```

### Consumer lag (Kafka)

```promql
sum by (group_id, topic_name)(kminion_kafka_consumer_group_topic_partition_lag)
```

Alert when lag exceeds threshold:
```yaml
conditions:
  - evaluator:
      params: [1000]
      type: gt
```

### Replica health (MongoDB)

```promql
mongodb_mongod_replset_member_health
```

Alert when fewer than 3 healthy replicas:
```yaml
conditions:
  - evaluator:
      params: [3]
      type: lt
```

### Error rate threshold

```promql
sum(rate(http_requests_total{status=~"5.."}[5m])) 
  / sum(rate(http_requests_total[5m]))
```

Alert when error rate exceeds 1%:
```yaml
conditions:
  - evaluator:
      params: [0.01]
      type: gt
```

### Resource exhaustion (CPU)

```promql
sum(rate(container_cpu_usage_seconds_total{container="api", container!="POD"}[5m])) 
  / sum(kube_pod_container_resource_limits_cpu_cores{container="api"})
```

Alert when CPU usage exceeds 80% of limit:
```yaml
conditions:
  - evaluator:
      params: [0.80]
      type: gt
```

### Lag trend (increasing)

```promql
deriv(kminion_kafka_consumer_group_topic_partition_lag[10m])
```

Alert when lag derivative is positive (lag increasing):
```yaml
conditions:
  - evaluator:
      params: [0]
      type: gt
```

## Contact points

Contact points define where alerts are sent. Configure in Grafana UI (Alerting → Contact points) or provision via API/files.

### Slack contact point (UI)

1. Alerting → Contact points → New contact point
2. Name: `slack-platform-alerts`
3. Type: Slack
4. Webhook URL: `https://hooks.slack.com/services/...`
5. Channel: `#platform-alerts`
6. Title: `{{ .GroupLabels.alertname }}`
7. Message: `{{ range .Alerts }}{{ .Annotations.message }}{{ end }}`

### Webhook contact point

1. Type: Webhook
2. URL: `https://incident-management.example.com/webhooks/grafana`
3. Method: POST
4. Body:
   ```json
   {
     "alertname": "{{ .GroupLabels.alertname }}",
     "severity": "{{ .CommonLabels.severity }}",
     "message": "{{ range .Alerts }}{{ .Annotations.message }}{{ end }}"
   }
   ```

### PagerDuty contact point

1. Type: PagerDuty
2. Integration Key: `<PagerDuty integration key>`
3. Severity: `{{ .CommonLabels.severity }}`
4. Summary: `{{ .GroupLabels.alertname }}`
5. Details: `{{ range .Alerts }}{{ .Annotations.message }}{{ end }}`

## Notification policies

Notification policies route alerts to contact points based on label matchers. They cascade: most-specific match wins.

### Default policy (UI)

Alerting → Notification policies → Default policy

**Default contact point:** `default-receiver` (fallback if no matchers)

### Label-based routing

```yaml
- matchers:
    - slack_0 = platform-alerts
  receiver: slack-platform-alerts
  continue: true

- matchers:
    - slack_0 = app-alerts
  receiver: slack-app-alerts
  continue: true

- matchers:
    - pagerduty_0 = oncall
  receiver: pagerduty-oncall
  continue: false  # Stop here, don't page multiple times

- matchers:
    - severity = critical
    - system = database
  receiver: pagerduty-database-oncall
```

**continue: true** — Keep evaluating policies (send to multiple contact points)
**continue: false** — Stop here (don't cascade to default)

### Mute timings

Suppress alerts during maintenance windows:

1. Alerting → Notification policies → Mute timings → New
2. Name: `weekend-maintenance`
3. Time interval: Saturdays, 02:00-06:00 UTC
4. Add to notification policy:
   ```yaml
   - matchers:
       - system = non-critical
     receiver: slack-platform-alerts
     mute_timings:
       - weekend-maintenance
   ```

## Provisioning alerts as code

### File provider (recommended)

**Provisioning config** (`provisioning/alerting/rules.yaml`):
```yaml
apiVersion: 1
groups:
  - orgId: 1
    name: otel-collector-alerts
    folder: Platform/SRE
    interval: 1m
    rules:
      - uid: sre-otel-collector-exporter-failures
        title: SRE-otel-collector-ExporterFailures-gt-0
        condition: C
        data:
          - refId: A
            queryType: ''
            relativeTimeRange: { from: 300, to: 0 }
            datasourceUid: ${PROMETHEUS_DS}
            model:
              expr: count(up{job="opentelemetry-collector"} == 1)
          - refId: B
            queryType: ''
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
        labels:
          severity: critical
          system: otel-collector
          slack_0: platform-alerts
        annotations:
          __dashboardUid__: otel-collector-dashboard
          __panelId__: "42"
          message: "OTel collector exporter failures"
```

**Grafana config** (`grafana.ini`):
```ini
[paths]
provisioning = /etc/grafana/provisioning
```

Store alert YAML in git under `alerting/rules/` and sync to `/etc/grafana/provisioning/alerting/`.

### API provisioning

**POST /api/v1/provisioning/alert-rules:**
```bash
curl -X POST https://grafana.example.com/api/v1/provisioning/alert-rules \
  -H "Authorization: Bearer ${GRAFANA_API_KEY}" \
  -H "Content-Type: application/json" \
  -d @alert-rule.json
```

**alert-rule.json:**
```json
{
  "uid": "sre-kafka-lag",
  "title": "SRE-kafka-minion-TopicLagIncreasing-gt-0",
  "condition": "C",
  "data": [ /* ... */ ],
  "for": "5m",
  "noDataState": "OK",
  "folderUID": "alerting-folder",
  "ruleGroup": "kafka-alerts",
  "labels": { "severity": "warning", "system": "kafka", "slack_0": "data-platform" },
  "annotations": { "__dashboardUid__": "kafka-consumer-lag", "__panelId__": "8", "message": "Kafka lag increasing" }
}
```

### Provisioning contact points

**provisioning/alerting/contactpoints.yaml:**
```yaml
apiVersion: 1
contactPoints:
  - orgId: 1
    name: slack-platform-alerts
    receivers:
      - uid: slack-platform-alerts-uid
        type: slack
        settings:
          url: https://hooks.slack.com/services/...
          recipient: '#platform-alerts'
          title: '{{ .GroupLabels.alertname }}'
          text: '{{ range .Alerts }}{{ .Annotations.message }}{{ end }}'
```

### Provisioning notification policies

**provisioning/alerting/policies.yaml:**
```yaml
apiVersion: 1
policies:
  - orgId: 1
    receiver: default-receiver
    group_by: ['alertname']
    routes:
      - matchers:
          - slack_0 = platform-alerts
        receiver: slack-platform-alerts
        continue: true
      - matchers:
          - pagerduty_0 = oncall
        receiver: pagerduty-oncall
```

## Alert evaluation flow

1. **Grafana evaluates the rule** every `interval` (default 1m)
2. **Executes stage A** (PromQL query over `relativeTimeRange`)
3. **Executes stage B** (reduce to scalar)
4. **Executes stage C** (threshold condition)
5. **If condition is true for `for` duration**, alert enters `Pending` state
6. **After `for` expires**, alert enters `Firing` state
7. **Grafana matches labels against notification policies**
8. **Routes to matching contact points**
9. **Sends notifications** (Slack message, PagerDuty page, webhook POST)

**If the condition resolves**, the alert enters `Normal` state and Grafana sends a resolution notification (if enabled in contact point settings).

## Best practices

### for duration

Set `for` to prevent flapping on transient spikes:
- High-volatility metrics (request rate): `for: 5m`
- Low-volatility metrics (replica count): `for: 1m`
- Critical alerts (service down): `for: 30s`

### noDataState

Choose intentionally:
- **Alerting**: Fire if the metric disappears (service stopped scraping)
- **OK**: Stay quiet if no data (metric not always present)
- **NoData**: Distinct state (track metric gaps without paging)

### execErrState

- **Alerting**: Fire on query errors (defensive, catches datasource outages)
- **OK**: Stay quiet on errors (avoid alert spam during Grafana/Prometheus issues)

### Alert fatigue

- Use `for` to reduce flapping
- Set `group_by` in notification policies to batch related alerts
- Add mute timings for known maintenance windows
- Use severity levels: page for `critical`, Slack for `warning`

### Testing alerts

1. Lower threshold temporarily (e.g., `gt: 0` instead of `gt: 1000`)
2. Trigger the condition in a test environment
3. Verify notification routing (Slack message, PagerDuty page)
4. Restore original threshold

Or use Grafana's "Test rule" button (Alerting → Alert rules → Edit → Test).

## Full example: Kafka consumer lag alert

```yaml
- uid: sre-kafka-lag-increasing
  title: SRE-kafka-minion-TopicLagIncreasing-gt-0
  condition: C
  data:
    - refId: A
      queryType: ''
      relativeTimeRange: { from: 600, to: 0 }
      datasourceUid: ${PROMETHEUS_DS}
      model:
        expr: sum by (group_id, topic_name)(kminion_kafka_consumer_group_topic_partition_lag)
    - refId: B
      queryType: ''
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
          - evaluator: { params: [1000], type: gt }
  for: 5m
  noDataState: OK
  execErrState: Alerting
  folderUID: platform-sre-alerts
  ruleGroup: kafka-alerts
  labels:
    severity: warning
    system: kafka
    alert_type: infra
    slack_0: data-platform
    pagerduty_0: oncall
  annotations:
    __dashboardUid__: kafka-consumer-lag-dashboard
    __panelId__: "12"
    message: "Kafka consumer lag exceeds 1000 messages for topic {{ $labels.topic_name }}, group {{ $labels.group_id }}"
    value: "{{ $values.C }} messages behind"
    runbook_url: "https://wiki.example.com/runbooks/kafka-consumer-lag"
```

**What happens:**
1. Query: Sum Kafka lag by topic/group
2. Reduce: Take last value
3. Threshold: Alert if > 1000
4. Wait 5 minutes (`for: 5m`)
5. If still above threshold, fire
6. Route to Slack (`slack_0: data-platform`) and PagerDuty (`pagerduty_0: oncall`)
7. Message includes topic/group labels and lag value
8. Responders click deep-link → panel 12 in kafka-consumer-lag-dashboard
