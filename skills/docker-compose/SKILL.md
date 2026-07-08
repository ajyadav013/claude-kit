---
name: docker-compose
description: Docker Compose for local dev and multi-service orchestration. Use when setting up local infrastructure (postgres/redis/kafka/temporal), one-image-many-roles containers, or env-specific compose files.
---

# Docker Compose for Local Development

Docker Compose patterns for multi-service orchestration, environment-specific configurations, health checks, and one-image-many-roles deployments from production services.

## When to use

- Setting up local development infrastructure (postgres, redis, kafka, zookeeper, temporal)
- Deploying one image as multiple containers with different roles (server/worker/consumer/cron via MODE env var)
- Configuring health checks for service dependencies (pg_isready, redis-cli ping, kafka-topics.sh)
- Managing environment-specific compose files (docker-compose.yml base, .dev for development, .prod-test for local production simulation, .override for personal overrides)
- Orchestrating services with conditional startup (depends_on with condition: service_healthy)
- Setting up hot-reload development with bind mounts and debug ports
- Using YAML anchors to share common environment variables across services
- Simulating Cloud Run/production deployments locally with prod-test compose files
- Deploying services with profiles for optional infrastructure (monitoring, kafka, temporal)

## Core conventions

### Service Dependencies with Health Checks

**Health check commands per service**: Define `healthcheck` for each infrastructure service using service-specific commands.

**Postgres**: `test: pg_isready -U username` (or `test: ["CMD-SHELL", "pg_isready -U username -d dbname"]`)

**Redis**: `test: redis-cli ping` (or `test: ["CMD", "redis-cli", "ping"]`)

**Kafka**: `test: kafka-topics.sh --list --bootstrap-server localhost:9092`

**Zookeeper**: `test: zkServer.sh status`

**Intervals and retries**: Set `interval: 1s` or `2s`, `timeout: 3s`, `retries: 30-50` for fast startup feedback.

**Conditional startup with depends_on**: Use `depends_on` with `condition: service_healthy` to ensure postgres/redis/kafka are ready before starting the application.

```yaml
services:
  api:
    depends_on:
      db:
        condition: service_healthy
      redis:
        condition: service_healthy
      kafka:
        condition: service_healthy
```

**Why**: Services that start before dependencies are ready will fail or retry indefinitely; health checks prevent this.

**Migration service pattern**: Create a `migrator` service that runs `alembic upgrade head` (or `flyway migrate`) with `restart: "no"` and `depends_on: db: condition: service_healthy`. It runs once, migrates the database, then exits.

### One Image, Many Containers Pattern

**Build once, deploy many roles**: Build the application image once in one service; reference `image: app:latest` in other services to reuse the same image.

**MODE env var dispatch**: Each service sets `MODE=server`, `MODE=worker`, `MODE=consumer`, or `MODE=cron`; the entrypoint.py reads `MODE` and dispatches to the correct startup function.

**Worker/consumer specialization**: For workers, set `WORKER_MODE=background_tasks` or `WORKER_MODE=db_events_publisher`; for consumers, set `CONSUMER_NAME=audit_consumer`.

**Why**: Reduces CI/CD complexity (one Dockerfile, one build, many deploys); ensures parity between server/worker/consumer code.

**Example**:
```yaml
services:
  server:
    build: .
    image: app:latest
    environment:
      MODE: server
  
  worker:
    image: app:latest  # Reuse same image
    environment:
      MODE: worker
      WORKER_MODE: background_tasks
  
  consumer:
    image: app:latest
    environment:
      MODE: consumer
```

**Disable health checks for non-HTTP services**: Workers and consumers don't run HTTP servers; disable inherited health checks with `healthcheck: disable: true`.

### Environment-Specific Compose Files

**Base docker-compose.yml**: Defines core services (api, db, redis, kafka) with production-like config (no bind mounts, no debug ports).

**docker-compose.dev.yml**: Development overrides — adds bind mounts (`./backend:/app`), debug ports (`5678:5678`), hot-reload env vars (`RELOAD: "true"`), host.docker.internal for connecting to host-native services.

**docker-compose.prod-test.yml**: Simulates Cloud Run deployment locally — sets `ENVIRONMENT: production`, disables dev mounts, injects production-like env vars (`JWT_SECRET_KEY`, `USE_MOCK_LLM`), tests production build paths.

**docker-compose.override.yml**: Per-developer personal overrides (never commit; gitignored); merges automatically with docker-compose.yml.

**docker-compose.local.yml**: Alternative to .override for personal config (explicit -f flag required).

**Usage**: `docker-compose -f docker-compose.yml -f docker-compose.dev.yml up --build` (dev mode), `docker-compose -f docker-compose.yml -f docker-compose.prod-test.yml up --build` (production simulation).

**Why**: Keeps base compose clean and reusable; avoids dev-specific config polluting production; enables local prod testing before deploy.

### Volume Mounts and Hot Reload

**Bind mounts for source code**: Mount `./backend:/app` or `.:/srv/service_name` to enable code changes without rebuilding.

**Named volumes for data persistence**: Use named volumes for postgres data (`db-data:/var/lib/postgresql/data`), redis data, kafka logs.

**GCP service account mount**: Mount `~/.ssh/service-account.json:/secrets/service-account.json:ro` (read-only) for local GCP API access.

**GCloud config mount**: Mount `$HOME/.config/gcloud:/root/.config/gcloud` for local GCP auth.

**Why**: Hot reload speeds up development; named volumes persist data across container restarts; service account mounts enable local testing of GCP APIs.

### YAML Anchors for Shared Environment Variables

**Define anchor once**: Use `x-environment: &common-env` to define shared env vars at the top level (not under services).

**Reference in services**: Use `environment: { <<: *common-env, MODE: server }` to merge shared env and service-specific env.

**Why**: Reduces duplication; ensures consistency across server/worker/consumer env vars; easy to update shared config in one place.

**Example**:
```yaml
x-environment: &common-env
  ENV: DEV
  POSTGRES_URL: postgresql://user:pass@db:5432/dbname
  REDIS_URL: redis://redis:6379/0

services:
  server:
    environment:
      <<: *common-env
      MODE: server
  
  worker:
    environment:
      <<: *common-env
      MODE: worker
```

### Debug Ports for Multiple Containers

**Unique debug port per container**: Expose unique debugpy/pdb ports for each container (5678, 5679, 5680, 5681...).

**Set DEBUG_PORT env var**: Pass `DEBUG_PORT: 5679` so entrypoint.py can start debugpy on the correct port.

**Why**: Multiple containers from the same image need unique debug ports to avoid port conflicts; VSCode/PyCharm can attach to each container independently.

### External Networks for Cross-Service Communication

**External network definition**: Define `networks: appnet: external: true, name: appnet` to connect to a shared network across multiple repos.

**Why**: Allows multiple local services (e.g., shared Kafka, Redis, Postgres) to communicate across docker-compose stacks without port conflicts.

**Usage**: Create the network once with `docker network create appnet`; reference in multiple compose files.

### Profiles for Optional Infrastructure

**Profile-gated services**: Use `profiles: ["monitoring"]` or `profiles: ["kafka"]` to mark services as optional.

**Activate with --profile**: `docker-compose --profile monitoring up` starts only services in the monitoring profile.

**Why**: Keeps compose file comprehensive without forcing developers to run heavy infrastructure (Prometheus, Grafana, Temporal) for simple feature work.

**Example**:
```yaml
services:
  kafka:
    image: bitnami/kafka:3.7
    profiles: ["kafka"]
  
  prometheus:
    image: prom/prometheus
    profiles: ["monitoring"]
```

### env_file and Environment Variables

**env_file for secrets**: Use `env_file: - .env` or `env_file: - path: ./backend/.env.secrets, required: false` to load secrets from file.

**environment for overrides**: Use `environment:` to override or add env vars on top of env_file.

**Never commit .env**: Add `.env` and `.env.secrets` to `.gitignore`; commit `.env.example` with dummy values.

**Why**: Keeps secrets out of compose files and git history; env_file simplifies local dev setup.

### Kafka + Zookeeper Pattern

**Zookeeper first**: Kafka depends on Zookeeper; define `depends_on: zookeeper: condition: service_healthy`.

**Kafka listener config**: Set `KAFKA_CFG_LISTENERS`, `KAFKA_CFG_ADVERTISED_LISTENERS`, `KAFKA_CFG_ZOOKEEPER_CONNECT` for broker connectivity.

**Health check**: `test: kafka-topics.sh --list --bootstrap-server localhost:9092` ensures broker is ready.

**Why**: Kafka requires Zookeeper for coordination; misconfigured listeners cause connection failures.

**Newer pattern (KRaft mode)**: Kafka 3.7+ supports KRaft (no Zookeeper) with `KAFKA_CFG_PROCESS_ROLES: controller,broker` and `KAFKA_CFG_CONTROLLER_QUORUM_VOTERS`.

### Temporal Setup

**Temporal server**: Use `temporalio/auto-setup:1.24` with postgres backend; set `DB: postgresql`, `POSTGRES_USER`, `POSTGRES_PWD`, `POSTGRES_SEEDS: postgres`.

**Temporal UI**: Use `temporalio/ui:2.26.2` with `TEMPORAL_ADDRESS: temporal:7233`.

**Why**: Temporal requires postgres for durable state; auto-setup image runs migrations automatically.

### Host Connectivity for Dev Mode

**host.docker.internal**: Use `POSTGRES_HOST: host.docker.internal` to connect to services running on the host machine (macOS/Windows Docker Desktop).

**Why**: Avoids running heavy infrastructure (postgres/redis/temporal) in containers when you already have them running locally.

**Linux alternative**: Use `network_mode: "host"` or `extra_hosts: - "host.docker.internal:host-gateway"`.

## Skeleton / example

Four complete worked compose files live verbatim in
[compose-skeletons.md](./references/compose-skeletons.md):

- **`docker-compose.yml` (base)** — postgres + redis + kafka/zookeeper with health checks, an
  `alembic upgrade head` migrator (`restart: "no"`), and an env-file-driven api service.
- **`docker-compose.dev.yml`** — bind mounts, per-container debugpy ports (5678/5679/5680),
  YAML-anchored shared env, MODE-dispatched server/consumer/worker from one image.
- **`docker-compose.prod-test.yml`** — local Cloud Run simulation (production env vars, mock LLM,
  optional secrets file, worker health check disabled).
- **Profiles variant** — KRaft-mode Kafka, prometheus + grafana, and Temporal, each gated behind
  `--profile kafka|monitoring|temporal`.

## Anti-patterns to avoid

- **Missing health checks on dependencies** — services start before postgres/redis/kafka are ready; always define `healthcheck` + `depends_on: condition: service_healthy`.
- **Hardcoding localhost in connection strings** — use service hostnames (app-db, app-redis, app-kafka) for DNS resolution within Docker network.
- **Same debug port for all containers** — port conflicts when running server + worker + consumer; use unique ports (5678, 5679, 5680).
- **Committing .env or .env.secrets** — secrets leak into git history; add to `.gitignore` and commit `.env.example` instead.
- **No restart policy** — containers exit on failure and don't restart; use `restart: always` for long-running services, `restart: "no"` for one-shot migrators.
- **Exposing ports in base docker-compose.yml for production services** — production doesn't need exposed ports; only expose in docker-compose.dev.yml.
- **Copying production secrets into docker-compose** — use dummy credentials for local dev; never mount prod secrets locally.
- **Running heavy infrastructure when not needed** — use profiles to gate optional services (monitoring, kafka, temporal) so developers don't wait for unnecessary containers.
- **Forgetting to disable health checks for workers/consumers** — workers don't run HTTP servers; inherited health checks will fail; use `healthcheck: disable: true`.
- **Not using YAML anchors for shared env** — duplicating env vars across server/worker/consumer leads to inconsistencies; define once with `x-environment: &common-env`.
- **Using external networks without creating them first** — `external: true` requires the network to exist; run `docker network create appnet` before compose up.
- **Mounting entire home directory** — only mount what's needed (`.:/app`, `~/.config/gcloud`); avoid mounting `~` which slows down Docker.

## References

- [compose-skeletons.md](./references/compose-skeletons.md) — Four full worked files: base stack, dev overlay, prod-test (Cloud Run simulation), and the profiles variant
- [compose-services-and-healthchecks.md](./references/compose-services-and-healthchecks.md) — Health check commands for postgres/redis/kafka/zookeeper, depends_on patterns, migrator service
- [dev-vs-prod-variants.md](./references/dev-vs-prod-variants.md) — docker-compose.yml vs .dev vs .prod-test, profiles, env_file, host.docker.internal
- [repo-evidence.md](./references/repo-evidence.md) — Generic snippets from production services (no internal names)
- [containerization-and-deployment](../containerization-and-deployment/SKILL.md) — Multi-stage Dockerfile, MODE dispatch entrypoint, cert/keytab writing, Cloud Run deployment (broader containerization patterns; cross-link for Dockerfile and deployment)
