# Repo Evidence

Generic, sanitized snippets from production services demonstrating docker-compose patterns. All service names, registries, credentials, and organization-specific details have been genericized.

## Base docker-compose.yml Pattern

**From a production microservice** (API + postgres + redis + kafka + zookeeper):

```yaml
version: '3.9'

services:
  api:
    build:
      context: .
      dockerfile: ./deploy/Dockerfile
    image: service:${SERVICE_VERSION:-latest}
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
      SERVICE_HOST: 0.0.0.0
      SERVICE_DB_HOST: service-db
      SERVICE_DB_PORT: 5432
      SERVICE_DB_USER: service
      SERVICE_DB_PASS: service
      SERVICE_DB_BASE: service
      KAFKA_BOOTSTRAP_SERVERS: '["service-kafka:9092"]'

  db:
    image: postgres:13.8-bullseye
    hostname: service-db
    environment:
      POSTGRES_PASSWORD: "service"
      POSTGRES_USER: "service"
      POSTGRES_DB: "service"
    volumes:
      - service-db-data:/var/lib/postgresql/data
    restart: always
    healthcheck:
      test: pg_isready -U service
      interval: 2s
      timeout: 3s
      retries: 40

  migrator:
    image: service:${SERVICE_VERSION:-latest}
    restart: "no"
    command: alembic upgrade head
    environment:
      SERVICE_DB_HOST: service-db
      SERVICE_DB_PORT: 5432
      SERVICE_DB_USER: service
      SERVICE_DB_PASS: service
      SERVICE_DB_BASE: service
    depends_on:
      db:
        condition: service_healthy

  redis:
    image: bitnami/redis:6.2.5
    hostname: "service-redis"
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
    hostname: "service-zookeeper"
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
    hostname: "service-kafka"
    environment:
      KAFKA_BROKER_ID: "1"
      ALLOW_PLAINTEXT_LISTENER: "yes"
      KAFKA_CFG_LISTENERS: "PLAINTEXT://0.0.0.0:9092"
      KAFKA_CFG_ADVERTISED_LISTENERS: "PLAINTEXT://service-kafka:9092"
      KAFKA_CFG_ZOOKEEPER_CONNECT: "service-zookeeper:2181"
    healthcheck:
      test: kafka-topics.sh --list --bootstrap-server localhost:9092
      interval: 1s
      timeout: 3s
      retries: 30
    depends_on:
      zookeeper:
        condition: service_healthy

volumes:
  service-db-data:
    name: service-db-data
```

**Key patterns**:
- Health checks on all infrastructure services (postgres, redis, kafka, zookeeper)
- Migrator service runs once (`restart: "no"`) and exits
- Named volume for postgres data persistence
- `depends_on` with `condition: service_healthy` ensures startup order

## docker-compose.dev.yml (Development Overrides)

**From a production service** (bind mounts, debug ports, YAML anchors):

```yaml
version: '3.4'

x-environment: &common-environment-variables
  ENV: DEV
  POSTGRES_READ_WRITE: postgresql://admin:<REDACTED>@app-postgres:5432/app_db
  KAFKA_BROKERS: kafka:29092
  REDIS_READ_WRITE: redis://app-redis:6379/9?decode_responses=true
  GOOGLE_CLOUD_PROJECT: "project-non-prod"

services:
  app-server:
    build:
      context: ..
      dockerfile: Dockerfile
    container_name: app-server
    image: app:latest
    ports:
      - '8081:80'
      - '5679:5679'
    environment:
      <<: *common-environment-variables
      MODE: server
      DEBUG_PORT: 5679
    volumes:
      - ..:/srv/app
      - $HOME/.config/gcloud:/root/.config/gcloud

  db-events-worker:
    image: app:latest  # Reuse same image
    container_name: db-events-worker
    ports:
      - '5680:5680'
    environment:
      <<: *common-environment-variables
      MODE: worker
      WORKER_MODE: db_events_publisher
      DEBUG_PORT: 5680
    volumes:
      - ..:/srv/app

  audit-consumer:
    image: app:latest
    container_name: audit-consumer
    ports:
      - '5681:5681'
    environment:
      <<: *common-environment-variables
      MODE: consumer
      CONSUMER_NAME: audit_consumer
      DEBUG_PORT: 5681
    volumes:
      - ..:/srv/app

  scheduled-job:
    image: app:latest
    container_name: scheduled-job
    ports:
      - '5683:5683'
    environment:
      <<: *common-environment-variables
      MODE: cron
      CRON_JOB: daily_sync
      DEBUG_PORT: 5683
    volumes:
      - ..:/srv/app

networks:
  appnet:
    external: true
    name: appnet
```

**Key patterns**:
- YAML anchor `x-environment: &common-environment-variables` defines shared env once
- Each service merges with `<<: *common-environment-variables`
- Same image (`app:latest`) deployed 4 times with different MODE env vars
- Unique debug ports (5679, 5680, 5681, 5683) per container
- Bind mount `..:/srv/app` for hot reload
- External network `appnet` for cross-service communication

## docker-compose.prod-test.yml (Local Production Simulation)

**From a production service** (frontend + backend + worker + demo-store):

```yaml
# docker-compose.prod-test.yml
# Usage: docker-compose -f docker-compose.yml -f docker-compose.prod-test.yml up --build
# Simulates the Cloud Run deployment locally

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
      POSTGRES_DB: service_db
      REDIS_HOST: redis
      REDIS_PORT: "6379"
      TEMPORAL_HOST: temporal
      TEMPORAL_PORT: "7233"
      TEMPORAL_ENABLED: "true"
      # Override production validation for local testing
      JWT_SECRET_KEY: "local-prod-test-secret-not-default"
      USE_MOCK_LLM: "true"
      USE_MOCK_VIDEO: "true"
      USE_MOCK_IMAGE: "true"
      GCS_BUCKET: "test-bucket"
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
      POSTGRES_PORT: "5432"
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: postgres
      POSTGRES_DB: service_db
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
      temporal:
        condition: service_started
    healthcheck:
      disable: true

  frontend:
    build:
      context: .
      dockerfile: frontend/Dockerfile
      args:
        VITE_API_BASE_URL: /api/v1
        VITE_APP_NAME: Studio
    ports:
      - "80:80"
    environment:
      BACKEND_URL: http://backend:8000
    depends_on:
      - backend
```

**Key patterns**:
- `ENVIRONMENT: production` triggers production code paths
- No bind mounts (tests production build)
- `USE_MOCK_LLM: "true"` enables test doubles for external APIs
- `JWT_SECRET_KEY` is NOT the default (tests prod validation)
- `healthcheck: disable: true` for worker (no HTTP server)
- `env_file: required: false` allows compose to start without .env.secrets

## Host Connectivity (dev mode)

**From a production service** (connect to host-native postgres/redis/temporal):

```yaml
services:
  backend:
    build:
      context: ./backend
      dockerfile: Dockerfile
    image: service-backend:${VERSION:-latest}
    ports:
      - "8000:8000"
    volumes:
      - ./backend:/app
      # GCP service account for Vertex AI and GCS
      - ${GCS_SERVICE_ACCOUNT_HOST_PATH:-~/.ssh/service-account.json}:/secrets/service-account.json:ro
    env_file:
      - path: ./backend/.env.secrets
        required: false
    environment:
      MODE: server
      RELOAD: "true"
      # Connect to host services via host.docker.internal
      POSTGRES_HOST: host.docker.internal
      REDIS_HOST: host.docker.internal
      TEMPORAL_HOST: host.docker.internal

  worker:
    image: service-backend:${VERSION:-latest}
    volumes:
      - ./backend:/app
      - ${GCS_SERVICE_ACCOUNT_HOST_PATH:-~/.ssh/service-account.json}:/secrets/service-account.json:ro
    env_file:
      - path: ./backend/.env.secrets
        required: false
    environment:
      MODE: worker
      POSTGRES_HOST: host.docker.internal
      REDIS_HOST: host.docker.internal
      TEMPORAL_HOST: host.docker.internal
    healthcheck:
      disable: true
```

**Key patterns**:
- `host.docker.internal` for connecting to host-native services
- `${GCS_SERVICE_ACCOUNT_HOST_PATH:-default}` allows override via env var
- `:ro` (read-only) mount for service account JSON
- `RELOAD: "true"` for hot-reload server
- `healthcheck: disable: true` for worker

## Profiles (Optional Infrastructure)

**From a production service** (kafka, monitoring, temporal gated by profiles):

```yaml
services:
  postgres:
    image: postgres:18
    environment:
      POSTGRES_USER: service
      POSTGRES_PASSWORD: service
      POSTGRES_DB: service_db
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U service -d service_db"]
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

  backend:
    build: ./backend
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy

  # Optional infrastructure (activate with --profile kafka)
  kafka:
    image: bitnami/kafka:3.7
    profiles: ["kafka"]
    environment:
      KAFKA_CFG_NODE_ID: 0
      KAFKA_CFG_PROCESS_ROLES: controller,broker
      KAFKA_CFG_CONTROLLER_QUORUM_VOTERS: 0@kafka:9093
      KAFKA_CFG_LISTENERS: PLAINTEXT://:9092,CONTROLLER://:9093
      KAFKA_CFG_ADVERTISED_LISTENERS: PLAINTEXT://kafka:9092
      KAFKA_CFG_LISTENER_SECURITY_PROTOCOL_MAP: CONTROLLER:PLAINTEXT,PLAINTEXT:PLAINTEXT
      KAFKA_CFG_CONTROLLER_LISTENER_NAMES: CONTROLLER
      KAFKA_CFG_AUTO_CREATE_TOPICS_ENABLE: "true"
    volumes:
      - kafka_data:/bitnami/kafka

  # Optional monitoring stack (activate with --profile monitoring)
  otel-collector:
    image: otel/opentelemetry-collector-contrib:0.100.0
    profiles: ["monitoring"]
    ports:
      - "4317:4317"
      - "4318:4318"
    volumes:
      - ./monitoring/otel/otel-collector-config.yml:/etc/otelcol-contrib/config.yaml

  prometheus:
    image: prom/prometheus:v2.52.0
    profiles: ["monitoring"]
    ports:
      - "9090:9090"
    volumes:
      - ./monitoring/prometheus/prometheus.yml:/etc/prometheus/prometheus.yml
      - prometheus_data:/prometheus

  grafana:
    image: grafana/grafana-oss:11.0.0
    profiles: ["monitoring"]
    ports:
      - "3001:3000"
    environment:
      GF_SECURITY_ADMIN_USER: admin
      GF_SECURITY_ADMIN_PASSWORD: service
    volumes:
      - ./monitoring/grafana/provisioning/dashboards.yml:/etc/grafana/provisioning/dashboards/dashboards.yml
      - grafana_data:/var/lib/grafana
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
      POSTGRES_USER: service
      POSTGRES_PWD: service
      POSTGRES_SEEDS: postgres
    depends_on:
      postgres:
        condition: service_healthy

  temporal-ui:
    image: temporalio/ui:2.26.2
    profiles: ["temporal"]
    ports:
      - "8233:8080"
    environment:
      TEMPORAL_ADDRESS: temporal:7233
    depends_on:
      - temporal

volumes:
  kafka_data:
  prometheus_data:
  grafana_data:
```

**Key patterns**:
- `profiles: ["kafka"]` gates kafka service
- `profiles: ["monitoring"]` gates otel-collector + prometheus + grafana
- `profiles: ["temporal"]` gates temporal + temporal-ui
- Named volumes for data persistence (kafka_data, prometheus_data, grafana_data)
- Temporal uses postgres backend (shared with main app)

## Minimal Compose (MODE dispatch only)

**From a production service** (MongoDB + Redis, MODE env var):

```yaml
version: '3'

services:
  app:
    build: .
    ports:
      - "80:80"
    environment:
      - MODE=server
      # - MODE=cron
      - ENVIRONMENT=development
      - MONGO_SERVICE_READ_WRITE=mongodb://mongo:27017/service_data
      - REDIS_SERVICE_READ_WRITE=redis://redis:6379/0

  redis:
    image: redis:latest
    container_name: redis
    ports:
      - "6379:6379"

  mongo:
    image: mongo:latest
    container_name: mongo
    ports:
      - "27017:27017"
    volumes:
      - ./mongo-init:/docker-entrypoint-initdb.d
      - ./mongo-init:/data
```

**Key patterns**:
- Single service with MODE env var (server or cron)
- No health checks (simple dev setup)
- Bind mount for mongo init scripts

## Nginx Reverse Proxy (with basic auth)

**From a production service** (Nginx + backend with basic auth):

```yaml
version: '3.8'

services:
  nginx:
    image: nginx:alpine
    container_name: service-nginx
    ports:
      - "8080:8080"
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf:ro
      - ./.htpasswd:/etc/nginx/.htpasswd:ro
    depends_on:
      - backend
    restart: unless-stopped
    command: >
      sh -c "
      rm -f /etc/nginx/conf.d/default.conf &&
      nginx -g 'daemon off;'
      "

  backend:
    build:
      context: ..
      dockerfile: Dockerfile
    container_name: service-backend
    expose:
      - "8080"
    volumes:
      - ./results:/app/results
      - ./reports:/app/reports
    restart: unless-stopped
```

**Key patterns**:
- `expose: - "8080"` (internal port only, no host exposure)
- Nginx proxies to backend (basic auth at edge)
- `restart: unless-stopped` (restarts automatically unless manually stopped)
- Read-only mounts for config (`:ro`)
- Multi-line command with `>`

## Summary of Patterns

- **Health checks**: postgres (pg_isready), redis (redis-cli ping), kafka (kafka-topics.sh), zookeeper (zkServer.sh status)
- **One image, many containers**: Build once, deploy as server/worker/consumer/cron via MODE env var
- **Environment-specific files**: docker-compose.yml (base), .dev (bind mounts + debug ports), .prod-test (production simulation)
- **YAML anchors**: `x-environment: &common-env` to share env vars
- **Profiles**: Gate optional services (kafka, monitoring, temporal) with `profiles: ["name"]`
- **Host connectivity**: `host.docker.internal` for connecting to host-native services
- **Migrator pattern**: One-shot service with `restart: "no"` and `command: alembic upgrade head`
- **Debug ports**: Unique per container (5678, 5679, 5680...)
- **Named volumes**: For data persistence (db-data, kafka_data, prometheus_data)
- **Bind mounts**: For hot reload (`.:/srv/app`) and GCP auth (`$HOME/.config/gcloud`)
