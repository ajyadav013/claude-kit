# Provisioning and Organization

This reference covers organizing Grafana dashboards at scale and provisioning them as code for repeatable, version-controlled deployments.

## Folder structure

Grafana folders organize dashboards into logical groups. A production instance with ~137 dashboards typically uses:

**APM (Application Performance Monitoring):**
- Distributed tracing dashboards
- Span-metrics RED (Rate/Error/Duration from Tempo)
- Service graph visualization (nodeGraph panels)
- Per-service trace analysis

**App Metrics:**
- Application-level RED metrics (HTTP requests, error rates, latency)
- Business metrics (orders/sec, revenue, user signups)
- Custom application metrics (cache hit rate, queue depth)

**Platform / SRE-Automation:**
- Kubernetes dashboards (pod/node/deployment metrics)
- Infrastructure components: Kafka, MongoDB, PostgreSQL, Redis, Temporal, OpenTelemetry collector
- Resource utilization (CPU, memory, disk, network)
- Cost dashboards (GCP billing, resource efficiency)

**Alerting:**
- Alert summary dashboards (firing alerts, alert history)
- Incident views (alert timeline, root cause correlation)

**General:**
- Exploratory dashboards (ad-hoc queries, debugging)
- Team-specific views (developer dashboards, per-service overviews)

## Tagging conventions

Tags make dashboards searchable and categorize them by function, ownership, or provisioning status.

### Provisioning status tags

**sre-automation:**
Dashboards built/maintained by the SRE team. Often provisioned from git.

**autogen:**
Auto-generated or provisioned dashboards. **Editing these in the UI is an anti-pattern** — changes are lost on the next provisioning sync.

**org-default provisioned tag:**
Organization-specific tag marking dashboards deployed via CI/CD. Exact name varies (e.g., `default-acme-dashboards`). Use a generic org marker when provisioning.

### Product/component tags

**prometheus, kafka, temporal, otel-collector, postgres, redis, mongodb:**
Component-specific dashboards. Tag by the primary system being monitored.

**kubernetes-mixin:**
Dashboards derived from the Kubernetes-mixin (community-maintained kube-state-metrics + node-exporter dashboards).

**cost, utilization:**
Resource efficiency dashboards (GCP billing, CPU/memory usage vs limits).

### Example tagging

```json
{
  "tags": ["sre-automation", "autogen", "kafka", "platform"]
}
```

Interpretation: SRE-maintained, provisioned from code, monitors Kafka, part of the platform monitoring stack.

## Dashboards as code (file provisioning)

Many production dashboards are tagged `autogen` or have an org-provisioned marker. This means they are **provisioned from files**, not hand-edited in the UI.

### Why provision?

**Version control:**
Dashboards in git → code review, blame, rollback.

**Consistency across environments:**
Same dashboard JSON deploys to dev/staging/prod Grafana instances (using `$datasource` variables for portability).

**CI/CD integration:**
Dashboard changes trigger automated validation + deployment.

**Avoid drift:**
Provisioned dashboards are read-only in the UI (or edits are overwritten on redeploy). Prevents ad-hoc changes that break on the next sync.

### File provider setup

**provisioning/dashboards/dashboards.yaml:**
```yaml
apiVersion: 1
providers:
  - name: 'default'
    orgId: 1
    folder: 'Platform/SRE'
    type: file
    updateIntervalSeconds: 30
    allowUiUpdates: false  # Prevent UI edits (enforce code-only changes)
    options:
      path: /var/lib/grafana/dashboards
      foldersFromFilesStructure: true  # Create folders from directory structure
```

**Directory structure:**
```
/var/lib/grafana/dashboards/
├── platform/
│   ├── kafka-overview.json
│   ├── postgres-metrics.json
│   └── otel-collector.json
├── apm/
│   ├── service-red-metrics.json
│   └── distributed-tracing.json
└── app-metrics/
    ├── api-metrics.json
    └── worker-metrics.json
```

Grafana scans `/var/lib/grafana/dashboards/` every 30 seconds, creates folders from subdirectories (`platform/` → "Platform" folder), and imports JSON files.

### Workflow: Editing a provisioned dashboard

1. **Clone the repo:**
   ```bash
   git clone https://github.com/example/grafana-dashboards.git
   cd grafana-dashboards
   ```

2. **Edit the JSON:**
   ```bash
   vim dashboards/platform/kafka-overview.json
   # Add a new panel, update PromQL, etc.
   ```

3. **Validate (optional):**
   ```bash
   # Lint JSON
   jq . dashboards/platform/kafka-overview.json > /dev/null

   # Validate schema (if you have a JSON schema)
   jsonschema -i dashboards/platform/kafka-overview.json schema/dashboard.schema.json
   ```

4. **Commit and push:**
   ```bash
   git add dashboards/platform/kafka-overview.json
   git commit -m "Add Kafka consumer lag panel"
   git push origin main
   ```

5. **CI/CD deploys:**
   ```bash
   # CI pipeline syncs dashboards/ to /var/lib/grafana/dashboards/ on Grafana server
   rsync -av dashboards/ grafana.example.com:/var/lib/grafana/dashboards/
   ```

6. **Grafana reloads:**
   Grafana detects the file change and updates the dashboard (within `updateIntervalSeconds`).

**Anti-pattern:** Opening the dashboard in the Grafana UI, editing a panel, and clicking Save. If `allowUiUpdates: false`, the save fails. If `allowUiUpdates: true`, the change is overwritten on the next provisioning sync.

### Exporting dashboards from the UI

If you've built a dashboard in the UI and want to provision it:

1. Dashboard settings (gear icon) → JSON Model → Copy to clipboard
2. Save to a file: `dashboards/platform/my-dashboard.json`
3. Edit the JSON:
   - Set `"uid": "my-dashboard"` (stable identifier)
   - Remove `"id"` (auto-assigned by Grafana)
   - Set `"version": 1` (or remove; Grafana manages this)
4. Commit to git and deploy via CI/CD

### Templating for multi-environment deployments

Use Grafana's `${VAR}` syntax for environment-specific values:

```json
{
  "datasource": {
    "type": "prometheus",
    "uid": "${PROMETHEUS_DS}"  // Replaced at runtime by Grafana
  }
}
```

Set `PROMETHEUS_DS` in Grafana's environment or provisioning config:
```bash
export GF_DASHBOARDS_DEFAULT_PROMETHEUS_DS=abc123
```

Or use a datasource provisioning file (see Datasource Provisioning section).

## Datasource provisioning

Provision datasources alongside dashboards for full infrastructure-as-code.

**provisioning/datasources/prometheus.yaml:**
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
      queryTimeout: 60s
      httpMethod: POST
    version: 1
    editable: false  # Prevent UI edits

  - name: Tempo-Prod
    type: tempo
    access: proxy
    url: http://tempo.monitoring.svc.cluster.local:3200
    jsonData:
      tracesToLogs:
        datasourceUid: loki-prod
        tags: ['trace_id']
      serviceMap:
        datasourceUid: prometheus-prod
    version: 1

  - name: Loki-Prod
    type: loki
    access: proxy
    url: http://loki.monitoring.svc.cluster.local:3100
    jsonData:
      maxLines: 1000
    version: 1
```

**Multi-environment setup:**

Use separate provisioning files per environment:
```
provisioning/datasources/
├── dev.yaml       # Datasources for dev Grafana
├── staging.yaml   # Datasources for staging Grafana
└── prod.yaml      # Datasources for prod Grafana
```

Deploy the appropriate file to each Grafana instance.

## Alert provisioning

Provision unified alerting rules alongside dashboards (see `references/unified-alerting.md` for full details).

**provisioning/alerting/rules.yaml:**
```yaml
apiVersion: 1
groups:
  - orgId: 1
    name: kafka-alerts
    folder: Platform/SRE
    interval: 1m
    rules:
      - uid: sre-kafka-lag
        title: SRE-kafka-minion-TopicLagIncreasing-gt-0
        condition: C
        data: [ /* multi-stage query */ ]
        for: 5m
        labels:
          severity: warning
          system: kafka
          slack_0: data-platform
        annotations:
          __dashboardUid__: kafka-consumer-lag
          __panelId__: "12"
```

Store in git under `alerting/rules/` and sync to `/etc/grafana/provisioning/alerting/`.

**Contact points** (provisioning/alerting/contactpoints.yaml):
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
```

**Notification policies** (provisioning/alerting/policies.yaml):
```yaml
apiVersion: 1
policies:
  - orgId: 1
    receiver: default-receiver
    routes:
      - matchers:
          - slack_0 = platform-alerts
        receiver: slack-platform-alerts
```

## API-based provisioning

Alternative to file provisioning: use the Grafana HTTP API.

### Dashboard API

**GET /api/dashboards/uid/:uid:**
```bash
curl -H "Authorization: Bearer ${GRAFANA_API_KEY}" \
  https://grafana.example.com/api/dashboards/uid/kafka-overview
```

**POST /api/dashboards/db** (create or update):
```bash
curl -X POST https://grafana.example.com/api/dashboards/db \
  -H "Authorization: Bearer ${GRAFANA_API_KEY}" \
  -H "Content-Type: application/json" \
  -d @dashboard-payload.json
```

**dashboard-payload.json:**
```json
{
  "dashboard": {
    "uid": "kafka-overview",
    "title": "Kafka Overview",
    "tags": ["sre-automation", "kafka"],
    "panels": [ /* ... */ ]
  },
  "folderId": 42,  // Or folderUid: "platform-sre"
  "overwrite": true,
  "message": "Update Kafka consumer lag panel"
}
```

### Alert API

**POST /api/v1/provisioning/alert-rules:**
```bash
curl -X POST https://grafana.example.com/api/v1/provisioning/alert-rules \
  -H "Authorization: Bearer ${GRAFANA_API_KEY}" \
  -H "Content-Type: application/json" \
  -d @alert-rule.json
```

**GET /api/v1/provisioning/alert-rules:**
```bash
curl -H "Authorization: Bearer ${GRAFANA_API_KEY}" \
  https://grafana.example.com/api/v1/provisioning/alert-rules
```

### CI/CD example (GitHub Actions)

```yaml
name: Deploy Grafana Dashboards
on:
  push:
    branches: [main]
    paths:
      - 'dashboards/**'

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      
      - name: Validate JSON
        run: |
          for f in dashboards/**/*.json; do
            jq . "$f" > /dev/null || exit 1
          done
      
      - name: Deploy to Grafana
        env:
          GRAFANA_API_KEY: ${{ secrets.GRAFANA_API_KEY }}
          GRAFANA_URL: https://grafana.example.com
        run: |
          for f in dashboards/**/*.json; do
            curl -X POST "${GRAFANA_URL}/api/dashboards/db" \
              -H "Authorization: Bearer ${GRAFANA_API_KEY}" \
              -H "Content-Type: application/json" \
              -d @"$f"
          done
```

## Organizing at scale: folder/tag strategy

For large deployments (~137 dashboards, 150 alerts), a clear organization strategy is critical.

### Folder hierarchy

```
├── APM
│   ├── Service RED Metrics
│   ├── Distributed Tracing
│   └── Service Graph
├── App Metrics
│   ├── API Metrics
│   ├── Worker Metrics
│   └── Business Metrics
├── Platform/SRE-Automation
│   ├── Kubernetes
│   │   ├── Cluster Overview
│   │   ├── Pod Insights
│   │   └── Node Metrics
│   ├── Kafka
│   ├── MongoDB
│   ├── PostgreSQL
│   ├── Redis
│   ├── Temporal
│   └── OpenTelemetry Collector
├── Alerting
│   ├── Alert Summary
│   └── Incident Timeline
└── General
    ├── Exploratory
    └── Developer Dashboards
```

**Folder-level permissions:** Grafana supports per-folder permissions (Viewer/Editor/Admin). Use this to gate sensitive dashboards (cost, customer data) or delegate ownership (app teams own their App Metrics folder).

### Tag taxonomy

**By provisioning status:**
- `sre-automation` — SRE-maintained
- `autogen` — Provisioned from code
- `manual` — Hand-built in UI (temporary, migrate to code)

**By component:**
- `prometheus`, `tempo`, `loki`, `kafka`, `postgres`, `redis`, `mongodb`, `temporal`, `otel-collector`, `kubernetes`

**By function:**
- `red` — RED metrics dashboards
- `cost` — Cost/billing dashboards
- `utilization` — Resource efficiency
- `alerting` — Alert summary dashboards

**By ownership:**
- `team-platform`, `team-data`, `team-api` — Team-specific dashboards

**Example dashboard tags:**
```json
{
  "tags": ["sre-automation", "autogen", "kafka", "red", "team-data"]
}
```

Search in Grafana: `tag:kafka tag:red` → finds all Kafka RED dashboards.

## Dashboard links and cross-references

Link related dashboards for quick navigation.

**Dashboard links (top-right dropdown):**
```json
{
  "links": [
    {
      "title": "Kafka Consumer Lag",
      "type": "link",
      "url": "/d/kafka-consumer-lag"
    },
    {
      "title": "Kafka Broker Metrics",
      "type": "link",
      "url": "/d/kafka-broker-metrics"
    },
    {
      "title": "All Kafka Dashboards",
      "type": "dashboards",
      "tags": ["kafka"],
      "keepTime": true  // Preserve time range when navigating
    }
  ]
}
```

**Panel-level links (click title → View):**
```json
{
  "fieldConfig": {
    "defaults": {
      "links": [
        {
          "title": "Trace in Tempo",
          "url": "/d/tempo-trace-view?var-trace_id=${__data.fields.trace_id}"
        }
      ]
    }
  }
}
```

## Permissions and RBAC

**Organization-level roles:**
- **Admin:** Full access (create/edit/delete dashboards, datasources, alerts, users)
- **Editor:** Create/edit dashboards, alerts (cannot manage datasources, users)
- **Viewer:** Read-only (view dashboards, cannot edit)

**Folder-level permissions:**
Override organization roles per folder. Example:
- Folder: `Platform/SRE-Automation`
- Permission: `team-platform` → Editor
- Permission: Everyone else → Viewer

**Dashboard-level permissions:**
Further override per dashboard (rare; prefer folder-level).

**Provisioned dashboards:**
If `allowUiUpdates: false`, even Admins cannot edit in the UI (enforce code-only changes).

## Grafana config for provisioning

**grafana.ini:**
```ini
[paths]
provisioning = /etc/grafana/provisioning

[dashboards]
min_refresh_interval = 5s

[auth.anonymous]
enabled = false

[security]
admin_user = admin
admin_password = ${GRAFANA_ADMIN_PASSWORD}

[server]
root_url = https://grafana.example.com
```

**Environment variables:**
```bash
export GF_SECURITY_ADMIN_PASSWORD=<secret>
export GF_DASHBOARDS_DEFAULT_PROMETHEUS_DS=prometheus-prod-uid
```

## Testing provisioned dashboards

1. **Spin up a local Grafana:**
   ```bash
   docker run -d \
     -p 3000:3000 \
     -v $(pwd)/provisioning:/etc/grafana/provisioning \
     -v $(pwd)/dashboards:/var/lib/grafana/dashboards \
     grafana/grafana:latest
   ```

2. **Open http://localhost:3000**
   Login: `admin` / `admin`

3. **Verify:**
   - Dashboards appear in the correct folders
   - Datasources are configured
   - Template variables work (`$datasource`, `$cluster`, `$service`)
   - Panels render (queries return data)
   - Alerts are present in Alerting → Alert rules

4. **Iterate:**
   Edit JSON → Grafana reloads within `updateIntervalSeconds` (default 30s)

## Anti-patterns

**Editing provisioned dashboards in the UI:**
If `allowUiUpdates: false`, the save fails. If `allowUiUpdates: true`, changes are lost on redeploy. Always edit the JSON in git.

**Hardcoded datasource UIDs in provisioned dashboards:**
```json
"datasource": { "type": "prometheus", "uid": "abc123" }
```
This breaks when deploying to a different Grafana instance. Use a `$datasource` variable instead.

**No version control for dashboards:**
Dashboards drift across environments (dev ≠ prod). Use git to track changes and deploy consistently.

**Overly-granular folder structure:**
```
├── Platform
│   ├── Kafka
│   │   ├── Consumer Lag
│   │   │   ├── Topic A
│   │   │   ├── Topic B
│   │   │   └── Topic C
```
This becomes unmanageable. Group by component (Kafka), not by individual topics. Use template variables to filter.

**Missing tags:**
Dashboards with no tags are hard to find. Always tag by component, function, and ownership.

**Provisioning alerts without `__dashboardUid__` annotations:**
Responders cannot jump to the offending panel. Always deep-link alerts to their source dashboard.

## Full example: Multi-environment provisioning

**Repo structure:**
```
grafana-dashboards/
├── provisioning/
│   ├── datasources/
│   │   ├── dev.yaml
│   │   ├── staging.yaml
│   │   └── prod.yaml
│   ├── dashboards/
│   │   └── dashboards.yaml
│   └── alerting/
│       ├── rules.yaml
│       ├── contactpoints.yaml
│       └── policies.yaml
├── dashboards/
│   ├── platform/
│   │   ├── kafka-overview.json
│   │   └── postgres-metrics.json
│   └── apm/
│       └── service-red-metrics.json
└── deploy.sh
```

**deploy.sh:**
```bash
#!/bin/bash
set -e

ENV=$1  # dev, staging, prod

if [[ -z "$ENV" ]]; then
  echo "Usage: ./deploy.sh <dev|staging|prod>"
  exit 1
fi

GRAFANA_HOST="grafana-${ENV}.example.com"

# Sync datasource provisioning
rsync -av provisioning/datasources/${ENV}.yaml ${GRAFANA_HOST}:/etc/grafana/provisioning/datasources/datasources.yaml

# Sync dashboard provisioning
rsync -av provisioning/dashboards/ ${GRAFANA_HOST}:/etc/grafana/provisioning/dashboards/

# Sync dashboard JSON
rsync -av dashboards/ ${GRAFANA_HOST}:/var/lib/grafana/dashboards/

# Sync alerting
rsync -av provisioning/alerting/ ${GRAFANA_HOST}:/etc/grafana/provisioning/alerting/

echo "Deployed to ${ENV}. Grafana will reload within 30s."
```

**CI/CD (GitHub Actions):**
```yaml
name: Deploy Grafana
on:
  push:
    branches:
      - main

jobs:
  deploy-prod:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Deploy to prod
        run: ./deploy.sh prod
        env:
          SSH_PRIVATE_KEY: ${{ secrets.SSH_PRIVATE_KEY }}
```

This workflow ensures:
- All environments use the same dashboard JSON (portability via `$datasource`)
- Datasources are environment-specific (dev → dev Prometheus, prod → prod Prometheus)
- Dashboards are version-controlled and code-reviewed
- Changes deploy automatically on merge to main
