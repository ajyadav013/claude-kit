# gcp-cloud-run-github-actions

A Claude Skill for standardizing GitHub Actions workflows that deploy containerized services to Google Cloud Run.

## What this covers

This skill encodes production patterns for deploying to Cloud Run via GitHub Actions, including:

- **Authentication**: Service account keys and Workload Identity Federation
- **Image caching**: Skip rebuilds when images already exist in the registry
- **Multi-job pipelines**: Deploy backend, worker, and frontend services with dependencies
- **One-image-many-roles**: Reuse a single Docker image for multiple services (server vs worker)
- **Cloud Run configuration**: VPC connectors, Cloud SQL instances, memory/CPU limits, autoscaling, timeouts
- **Environment variables**: Pass config and secrets securely to Cloud Run services
- **Post-deploy validation**: Sanity check jobs to verify service health after deployment
- **Environment-specific workflows**: Separate workflows for dev/staging/prod with different triggers and settings

## Derived from real production services

These patterns are extracted from real monorepo workflows deploying FastAPI backends, Temporal workers, React frontends, and Next.js apps to Cloud Run. All examples are genericized to remove internal service names, GCP project IDs, registry hosts, and secret values.

## When to use this skill

Use this skill when:

- Building CI/CD pipelines for Cloud Run deployments
- Setting up multi-service deployments from a monorepo
- Configuring VPC connectors, Cloud SQL instances, and environment variables
- Optimizing build times by skipping unnecessary rebuilds
- Adding deployment sanity checks to validate service health
- Migrating from other deployment platforms to Cloud Run

## Cross-references

This skill is distinct from but complements:

- **containerization-and-deployment**: Broader topic covering Docker multi-stage builds, Kubernetes, and general deployment strategies. This skill focuses narrowly on GitHub Actions → Cloud Run workflows.
- **fastapi-service-patterns**: Covers application-layer FastAPI conventions. This skill covers the deployment layer.
- **ci-cd-and-automation**: General CI/CD patterns across platforms. This skill is GCP-specific.

## Structure

- `SKILL.md`: Main skill content with conventions, examples, and anti-patterns
- `references/cloud-run-deploy.md`: Deep dive on `gcloud run deploy` flags
- `references/workflow-structure.md`: GitHub Actions workflow structure and multi-job patterns
- `references/repo-evidence.md`: Genericized snippets from real workflows

## License

Public domain. Safe to share and publish.
