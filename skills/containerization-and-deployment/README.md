# Containerization and Deployment

Docker containerization, multi-role deployment, secrets management, and local dev infrastructure patterns from production Python/FastAPI microservices.

## What this skill covers

- **Multi-stage Dockerfiles**: Builder + runtime separation, Alpine/slim base images, dependency caching, security hardening
- **Entrypoint MODE dispatch**: One image deploying as server/consumer/worker/cron/temporal_worker based on env var
- **Cert/keytab writing**: Converting env-var secrets (PEM certs, keytabs) to filesystem files for Kafka SASL_SSL/Kerberos
- **Docker Compose for local dev**: Service dependencies, health checks, volume mounts, debug ports, shared env anchors
- **Cloud Run / k8s deployment**: MODE env vars, CloudSQL socket connection, VPC connectors, secrets as env vars
- **Secrets hygiene**: Never commit credentials, base64-encode binary secrets, env-only secret injection

## Provenance

Derived from real-world production Python/FastAPI services implementing multi-stage Dockerfiles, MODE-based entrypoint dispatch, cert/keytab writing patterns, docker-compose orchestration with health checks, and Cloud Run/k8s deployments.

## How to apply

1. **For new services**: Start with the multi-stage Dockerfile template; use alpine for minimal footprint or slim for broader compatibility.
2. **For multi-role deployments**: Implement `entrypoint.py` MODE dispatch; deploy the same image to server/consumer/worker/cron with env var changes.
3. **For Kafka SASL_SSL/Kerberos**: Use the cert/keytab writing pattern in `entrypoint.py` before starting consumers; store secrets as env vars in base64.
4. **For local dev**: Use docker-compose with health checks; mount code volumes for hot reload; expose unique debug ports per container.
5. **For Cloud Run/k8s**: Set `MODE` env var per deployment; use CloudSQL socket for managed Postgres; inject secrets as env vars.

## Sources

- **Codebase patterns**: Multi-stage Dockerfile patterns, entrypoint MODE dispatch, cert/keytab writing, docker-compose health checks, Cloud Run deployment, one-image-many-roles pattern.
- **Verified against**: Multi-stage Docker build best practices (Docker docs), health check syntax (Docker Compose v3 spec), Cloud Run `--set-env-vars` flag (gcloud CLI docs), base64 encoding for binary secrets (standard practice for env vars).
