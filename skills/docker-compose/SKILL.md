---
name: docker-compose
description: Docker Compose patterns for local development and multi-service orchestration. Use when setting up local infrastructure (postgres/redis/kafka/zookeeper/temporal), implementing one-image-many-containers for different roles (server/worker/consumer/cron), configuring environment-specific compose files (.dev/.prod-test/.override), or wiring service dependencies with health checks and conditional startup.
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

```yaml
# docker-compose.yml (base)
version: '3.9'

services:
  api:
    build:
      context: .
      dockerfile: ./deploy/Dockerfile
    image: app:${APP_VERSION:-latest}
    restart: always
    env_file:
      - .env
    depends_on:
      db:
        condition: service_healthy
      redis:
        condition: service_healthy
      kafka:
        condition: service_healthy
    environment:
      APP_HOST: 0.0.0.0
      DB_HOST: app-db
      DB_PORT: 5432
      DB_USER: app
      DB_PASS: app
      DB_NAME: app
      KAFKA_BOOTSTRAP_SERVERS: '["app-kafka:9092"]'

  db:
    image: postgres:13.8-bullseye
    hostname: app-db
    environment:
      POSTGRES_PASSWORD: "app"
      POSTGRES_USER: "app"
      POSTGRES_DB: "app"
    volumes:
      - app-db-data:/var/lib/postgresql/data
    restart: always
    healthcheck:
      test: pg_isready -U app
      interval: 2s
      timeout: 3s
      retries: 40

  migrator:
    image: app:${APP_VERSION:-latest}
    restart: "no"
    command: alembic upgrade head
    environment:
      DB_HOST: app-db
      DB_PORT: 5432
      DB_USER: app
      DB_PASS: app
      DB_NAME: app
    depends_on:
      db:
        condition: service_healthy

  redis:
    image: bitnami/redis:6.2.5
    hostname: "app-redis"
    restart: always
    environment:
      ALLOW_EMPTY_PASSWORD: "yes"
    healthcheck:
      test: redis-cli ping
      interval: 1s
      timeout: 3s
      retries: 50

  zookeeper:
    image: "bitnami/zookeeper:3.7.1"
    hostname: "app-zookeeper"
    environment:
      ALLOW_ANONYMOUS_LOGIN: "yes"
      ZOO_LOG_LEVEL: "ERROR"
    healthcheck:
      test: zkServer.sh status
      interval: 1s
      timeout: 3s
      retries: 30

  kafka:
    image: "bitnami/kafka:3.2.0"
    hostname: "app-kafka"
    environment:
      KAFKA_BROKER_ID: "1"
      ALLOW_PLAINTEXT_LISTENER: "yes"
      KAFKA_CFG_LISTENERS: "PLAINTEXT://0.0.0.0:9092"
      KAFKA_CFG_ADVERTISED_LISTENERS: "PLAINTEXT://app-kafka:9092"
      KAFKA_CFG_ZOOKEEPER_CONNECT: "app-zookeeper:2181"
    healthcheck:
      test: kafka-topics.sh --list --bootstrap-server localhost:9092
      interval: 1s
      timeout: 3s
      retries: 30
    depends_on:
      zookeeper:
        condition: service_healthy

volumes:
  app-db-data:
    name: app-db-data
```

```yaml
# docker-compose.dev.yml
version: '3.9'

x-environment: &common-dev-env
  ENV: DEV
  POSTGRES_URL: postgresql://app:app@app-db:5432/app
  REDIS_URL: redis://app-redis:6379/0
  KAFKA_BROKERS: app-kafka:9092

services:
  server:
    build: .
    image: app:latest
    ports:
      - '8000:80'
      - '5678:5678'  # debugpy
    environment:
      <<: *common-dev-env
      MODE: server
      DEBUG_PORT: 5678
      RELOAD: "true"
    volumes:
      - .:/srv/app
      - $HOME/.config/gcloud:/root/.config/gcloud
    depends_on:
      db:
        condition: service_healthy
      redis:
        condition: service_healthy

  consumer:
    image: app:latest
    ports:
      - '5679:5679'
    environment:
      <<: *common-dev-env
      MODE: consumer
      DEBUG_PORT: 5679
    volumes:
      - .:/srv/app
    depends_on:
      kafka:
        condition: service_healthy

  worker:
    image: app:latest
    ports:
      - '5680:5680'
    environment:
      <<: *common-dev-env
      MODE: worker
      WORKER_MODE: background_tasks
      DEBUG_PORT: 5680
    volumes:
      - .:/srv/app

  db:
    image: postgres:13.8-bullseye
    hostname: app-db
    ports:
      - '5432:5432'
    environment:
      POSTGRES_PASSWORD: "app"
      POSTGRES_USER: "app"
      POSTGRES_DB: "app"
    volumes:
      - db-data:/var/lib/postgresql/data
    healthcheck:
      test: pg_isready -U app
      interval: 2s
      timeout: 3s
      retries: 40

  redis:
    image: bitnami/redis:6.2.5
    hostname: "app-redis"
    ports:
      - '6379:6379'
    environment:
      ALLOW_EMPTY_PASSWORD: "yes"
    healthcheck:
      test: redis-cli ping
      interval: 1s
      timeout: 3s
      retries: 50

  kafka:
    image: "bitnami/kafka:3.2.0"
    hostname: "app-kafka"
    ports:
      - '9092:9092'
    environment:
      KAFKA_BROKER_ID: "1"
      ALLOW_PLAINTEXT_LISTENER: "yes"
      KAFKA_CFG_LISTENERS: "PLAINTEXT://0.0.0.0:9092"
      KAFKA_CFG_ADVERTISED_LISTENERS: "PLAINTEXT://app-kafka:9092"
      KAFKA_CFG_ZOOKEEPER_CONNECT: "app-zookeeper:2181"
    healthcheck:
      test: kafka-topics.sh --list --bootstrap-server localhost:9092
      interval: 1s
      timeout: 3s
      retries: 30
    depends_on:
      zookeeper:
        condition: service_healthy

  zookeeper:
    image: "bitnami/zookeeper:3.7.1"
    hostname: "app-zookeeper"
    ports:
      - '2181:2181'
    environment:
      ALLOW_ANONYMOUS_LOGIN: "yes"
      ZOO_LOG_LEVEL: "ERROR"
    healthcheck:
      test: zkServer.sh status
      interval: 1s
      timeout: 3s
      retries: 30

volumes:
  db-data:
```

```yaml
# docker-compose.prod-test.yml
# Usage: docker-compose -f docker-compose.yml -f docker-compose.prod-test.yml up --build
# Simulates Cloud Run deployment locally

services:
  backend:
    build: ./backend
    ports:
      - "8000:8000"
    environment:
      ENVIRONMENT: production
      MODE: server
      POSTGRES_HOST: postgres
      POSTGRES_PORT: "5432"
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: postgres
      POSTGRES_DB: app_db
      REDIS_HOST: redis
      REDIS_PORT: "6379"
      TEMPORAL_HOST: temporal
      TEMPORAL_PORT: "7233"
      TEMPORAL_ENABLED: "true"
      JWT_SECRET_KEY: "local-prod-test-secret-not-default"
      USE_MOCK_LLM: "true"
      DEBUG: "false"
    env_file:
      - path: ./backend/.env.secrets
        required: false
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy

  worker:
    build: ./backend
    environment:
      ENVIRONMENT: production
      MODE: worker
      POSTGRES_HOST: postgres
      REDIS_HOST: redis
      TEMPORAL_HOST: temporal
      TEMPORAL_ENABLED: "true"
      JWT_SECRET_KEY: "local-prod-test-secret-not-default"
      DEBUG: "false"
    depends_on:
      postgres:
        condition: service_healthy
      temporal:
        condition: service_started
    healthcheck:
      disable: true
```

```yaml
# docker-compose with profiles
services:
  backend:
    build: ./backend
    ports:
      - "8000:8000"
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy

  postgres:
    image: postgres:18
    environment:
      POSTGRES_USER: app
      POSTGRES_PASSWORD: app
      POSTGRES_DB: app_db
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U app -d app_db"]
      interval: 5s
      timeout: 5s
      retries: 5

  redis:
    image: redis:7-alpine
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 5s
      retries: 5

  # Optional infrastructure (activate with --profile kafka)
  kafka:
    image: bitnami/kafka:3.7
    profiles: ["kafka"]
    ports:
      - "9092:9092"
    environment:
      KAFKA_CFG_NODE_ID: 0
      KAFKA_CFG_PROCESS_ROLES: controller,broker
      KAFKA_CFG_CONTROLLER_QUORUM_VOTERS: 0@kafka:9093
      KAFKA_CFG_LISTENERS: PLAINTEXT://:9092,CONTROLLER://:9093
      KAFKA_CFG_ADVERTISED_LISTENERS: PLAINTEXT://kafka:9092

  # Optional monitoring stack (activate with --profile monitoring)
  prometheus:
    image: prom/prometheus:v2.52.0
    profiles: ["monitoring"]
    ports:
      - "9090:9090"
    volumes:
      - ./monitoring/prometheus.yml:/etc/prometheus/prometheus.yml

  grafana:
    image: grafana/grafana-oss:11.0.0
    profiles: ["monitoring"]
    ports:
      - "3001:3000"
    depends_on:
      - prometheus

  # Optional Temporal (activate with --profile temporal)
  temporal:
    image: temporalio/auto-setup:1.24
    profiles: ["temporal"]
    ports:
      - "7233:7233"
    environment:
      DB: postgresql
      DB_PORT: 5432
      POSTGRES_USER: app
      POSTGRES_PWD: app
      POSTGRES_SEEDS: postgres
    depends_on:
      postgres:
        condition: service_healthy
```

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

- [compose-services-and-healthchecks.md](./references/compose-services-and-healthchecks.md) — Health check commands for postgres/redis/kafka/zookeeper, depends_on patterns, migrator service
- [dev-vs-prod-variants.md](./references/dev-vs-prod-variants.md) — docker-compose.yml vs .dev vs .prod-test, profiles, env_file, host.docker.internal
- [repo-evidence.md](./references/repo-evidence.md) — Generic snippets from production services (no internal names)
- [containerization-and-deployment](../containerization-and-deployment/SKILL.md) — Multi-stage Dockerfile, MODE dispatch entrypoint, cert/keytab writing, Cloud Run deployment (broader containerization patterns; cross-link for Dockerfile and deployment)
