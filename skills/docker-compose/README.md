# docker-compose Skill

Docker Compose patterns for local development and multi-service orchestration, derived from real-world production microservices.

## What this skill covers

- **Service dependencies with health checks**: postgres (pg_isready), redis (redis-cli ping), kafka (kafka-topics.sh --list), zookeeper (zkServer.sh status), wired to `depends_on` with `condition: service_healthy`
- **One image, many containers**: Build once, deploy as server/worker/consumer/cron by varying MODE env var
- **Environment-specific compose files**: Base docker-compose.yml, .dev (bind mounts + debug ports), .prod-test (local Cloud Run simulation), .override (personal gitignored config)
- **YAML anchors for shared environment variables**: Define once with `x-environment: &common-env`, reference with `<<: *common-env`
- **Profiles for optional infrastructure**: Gate monitoring/kafka/temporal services with profiles (activate with --profile flag)
- **Hot-reload development**: Bind mounts for source code, named volumes for data persistence, debug ports per container
- **Kafka + Zookeeper setup**: Conditional startup, health checks, listener configuration, KRaft mode alternative
- **Temporal orchestration**: Auto-setup image with postgres backend, Temporal UI
- **Host connectivity for dev mode**: host.docker.internal for connecting to host-native services
- **Migration service pattern**: One-shot migrator service that runs database migrations then exits

## Source

This skill is grounded in production compose files from real backend microservices (FastAPI/Python), frontend applications (React/Next.js), and infrastructure services. All examples are genericized and sanitized — no internal service names, registries, credentials, or organization-specific details.

## Cross-references

- **containerization-and-deployment**: Multi-stage Dockerfile, MODE dispatch entrypoint.py, cert/keytab writing, Cloud Run deployment (this skill focuses on compose orchestration; containerization-and-deployment covers the broader containerization lifecycle)

## When to use

Use this skill when:
- Setting up local dev infrastructure (postgres/redis/kafka/zookeeper/temporal)
- Implementing one-image-many-containers for different roles (server/worker/consumer/cron)
- Configuring environment-specific compose files (.dev/.prod-test/.override)
- Wiring service dependencies with health checks and conditional startup
- Testing production-like deployments locally before Cloud Run/k8s deploy
- Orchestrating multi-service applications with docker-compose

Cross-link to containerization-and-deployment for Dockerfile patterns, entrypoint MODE dispatch, and deployment strategies.
