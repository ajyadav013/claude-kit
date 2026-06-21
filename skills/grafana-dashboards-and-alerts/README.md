# grafana-dashboards-and-alerts

A Claude Code skill for building production-quality Grafana dashboards and unified alerting rules.

## What this skill covers

- **Dashboard JSON structure** — panels, template variables, datasource selection, gridPos layout
- **Template variables** — $datasource portability pattern, cascading label_values queries, custom variables, multi-select
- **RED metrics PromQL** — Rate/Error/Duration patterns from NGINX ingress, OpenTelemetry span-metrics (Tempo), and pod/container utilization (kube-state-metrics + cAdvisor)
- **Grafana unified alerting** — multi-stage rules (query → reduce → threshold), label-based routing (slack_0/webhook_0/pagerduty_0), contact points, notification policies
- **Dashboard organization** — folder/tag conventions, provisioning dashboards as code (file provider, JSON in git)
- **Tempo integration** — service graph nodeGraph panels, span-metrics RED, distributed trace visualization
- **Anti-patterns** — hardcoded datasource UIDs, editing provisioned dashboards in the UI, missing alert annotations, label typos

## Provenance

This skill is derived from a **production multi-cluster Grafana observability stack**:
- ~137 dashboards across APM / App Metrics / Platform-SRE / General folders
- 150 unified alerting rules
- Datasources: Prometheus (multiple instances), Tempo, Pyroscope, Stackdriver/Google Cloud Monitoring, Elasticsearch, Infinity
- Large-scale deployment patterns: cascading template variables, label-based alert routing, dashboards-as-code provisioning

All conventions are **grounded in real instance usage**, not theoretical best practices.

## How to apply

Invoke the `/grafana-dashboards-and-alerts` skill when:
- Building new Grafana dashboards for services, infrastructure, or business metrics
- Writing or debugging PromQL queries for RED (Rate/Error/Duration) metrics
- Authoring Grafana unified alerting rules with proper labeling and routing
- Configuring dashboard template variables for portability across environments
- Setting up contact points (Slack, PagerDuty, webhook) and notification policies
- Provisioning dashboards and alerts as code (file provider, JSON in git)
- Visualizing Tempo distributed traces (service graph, span-metrics)
- Refactoring dashboards for portability or reviewing for anti-patterns

The skill will guide dashboard JSON authoring, PromQL patterns, and alerting conventions following proven multi-cluster deployment patterns.

## Pattern sources

- **Dashboard JSON model** — derived from production dashboard exports (schemaVersions 30, 38, 41)
- **Template variables** — the APM dashboard's $datasource + cascading cluster→service pattern
- **RED PromQL** — three archetypes: NGINX ingress controller metrics, OTel span-metrics (Tempo), pod utilization (kube-state-metrics + cAdvisor)
- **Unified alerting** — 150-rule deployment's multi-stage structure, label-based routing, naming convention
- **Provisioning** — file provider + autogen tag pattern from instance with ~137 provisioned dashboards
- **Anti-patterns** — observed issues (hardcoded UIDs, regex fragility, missing annotations) genericized for public release

## Cross-references

- **`observability-and-logging` skill** — covers emitting the metrics these dashboards visualize (Prometheus exporters, structured logging, trace instrumentation)
- **`gcp-cloud-run-github-actions` skill** — includes Google Cloud Monitoring datasource patterns for managed services (CloudSQL, Redis, NAT)

## Structure

- `SKILL.md` — core skill content (conventions, PromQL patterns, alerting, anti-patterns)
- `references/dashboard-json-and-templating.md` — JSON model anatomy, template variables
- `references/red-metrics-queries.md` — NGINX ingress, OTel span-metrics, pod utilization PromQL
- `references/unified-alerting.md` — multi-stage rules, label-based routing, provisioning
- `references/provisioning-and-organization.md` — dashboards-as-code workflow, folder/tag conventions
- `references/repo-evidence.md` — provenance and pattern sources
