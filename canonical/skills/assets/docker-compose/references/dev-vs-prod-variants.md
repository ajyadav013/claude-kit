# Dev vs Prod Compose Variants

Environment-specific compose files, profiles, env_file patterns, and host connectivity for development.

## Compose File Variants

### Base docker-compose.yml

**Purpose**: Production-like base configuration — no bind mounts, no debug ports, minimal exposed ports.

**Pattern**:
```yaml
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
    environment:
      APP_HOST: 0.0.0.0
      DB_HOST: app-db

  db:
    image: postgres:13.8-bullseye
    hostname: app-db
    environment:
      POSTGRES_USER: app
      POSTGRES_PASSWORD: app
      POSTGRES_DB: app
    volumes:
      - db-data:/var/lib/postgresql/data
    healthcheck:
      test: pg_isready -U app
      interval: 2s
      retries: 40

volumes:
  db-data:
```

**Key points**:
- No port exposure (unless needed for external access)
- Named volumes for data persistence (not bind mounts)
- `restart: always` for long-running services
- `env_file: - .env` for local secrets (gitignored)

### docker-compose.dev.yml

**Purpose**: Development overrides — bind mounts for hot reload, debug ports, exposed infrastructure ports.

**Pattern**:
```yaml
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
      - .:/srv/app  # Bind mount for hot reload
      - $HOME/.config/gcloud:/root/.config/gcloud  # GCP auth
    depends_on:
      db:
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
    ports:
      - '5432:5432'  # Expose for external DB clients

  redis:
    ports:
      - '6379:6379'

  kafka:
    ports:
      - '9092:9092'
```

**Usage**: `docker-compose -f docker-compose.yml -f docker-compose.dev.yml up --build`

**Key points**:
- YAML anchor `x-environment: &common-dev-env` defines shared env once
- Each service merges with `<<: *common-dev-env`
- Bind mounts `.:/srv/app` for hot reload (no rebuild on code change)
- Unique debug ports per container (5678, 5680) for debugpy/pdb attachment
- Expose infrastructure ports (5432, 6379, 9092) for external tools (DBeaver, RedisInsight, Kafka UI)

### docker-compose.prod-test.yml

**Purpose**: Simulate Cloud Run/production deployment locally — production builds, production env vars, no dev mounts.

**Pattern**:
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
      POSTGRES_DB: app_db
      REDIS_HOST: redis
      REDIS_PORT: "6379"
      TEMPORAL_HOST: temporal
      TEMPORAL_PORT: "7233"
      TEMPORAL_ENABLED: "true"
      # Override production validation for local testing
      JWT_SECRET_KEY: "local-prod-test-secret-not-default"
      USE_MOCK_LLM: "true"
      USE_MOCK_VIDEO: "true"
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
      TEMPORAL_ENABLED: "true"
      JWT_SECRET_KEY: "local-prod-test-secret-not-default"
      DEBUG: "false"
    depends_on:
      postgres:
        condition: service_healthy
      temporal:
        condition: service_started
    healthcheck:
      disable: true  # Worker has no HTTP server
```

**Usage**: `docker-compose -f docker-compose.yml -f docker-compose.prod-test.yml up --build`

**Key points**:
- `ENVIRONMENT: production` triggers production code paths (validation, error handling)
- No bind mounts — tests the built image, not source code
- `USE_MOCK_LLM: "true"` enables test doubles for external APIs
- `JWT_SECRET_KEY` is NOT the default value (tests prod validation logic)
- `DEBUG: "false"` disables debug mode
- `healthcheck: disable: true` for worker (no HTTP server to check)

**Why this pattern**:
- Catches production-only issues before deploying to Cloud Run
- Tests that Dockerfile builds correctly for production
- Validates env var injection matches Cloud Run config
- Simulates multi-service deployment (backend + worker + temporal)

### docker-compose.override.yml

**Purpose**: Per-developer personal overrides (never commit; gitignored).

**Pattern**:
```yaml
# docker-compose.override.yml (gitignored)
services:
  server:
    ports:
      - '8080:80'  # Different port for personal preference
    environment:
      LOG_LEVEL: DEBUG
    volumes:
      - /custom/path:/data

  db:
    ports:
      - '5433:5432'  # Avoid conflict with host postgres
```

**Usage**: `docker-compose up` (override merges automatically)

**Key points**:
- Never commit (add to `.gitignore`)
- Merges automatically without `-f` flag
- Useful for personal port mappings, custom volumes, debug settings
- Does not interfere with team's base config

### docker-compose.local.yml

**Purpose**: Alternative to .override for personal config (explicit -f flag required).

**Usage**: `docker-compose -f docker-compose.yml -f docker-compose.local.yml up`

**Key points**:
- Requires explicit `-f` flag (doesn't auto-merge like .override)
- Can be committed (if team wants to share a "local" variant)
- Less common than .override

## Profiles for Optional Infrastructure

**Pattern**:
```yaml
services:
  backend:
    build: ./backend
    depends_on:
      postgres:
        condition: service_healthy

  postgres:
    image: postgres:18
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U app"]

  # Optional Kafka (activate with --profile kafka)
  kafka:
    image: bitnami/kafka:3.7
    profiles: ["kafka"]
    environment:
      KAFKA_CFG_NODE_ID: 0
      KAFKA_CFG_PROCESS_ROLES: controller,broker

  # Optional monitoring stack (activate with --profile monitoring)
  prometheus:
    image: prom/prometheus:v2.52.0
    profiles: ["monitoring"]
    ports:
      - "9090:9090"

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
      POSTGRES_USER: app
      POSTGRES_PWD: app

  temporal-ui:
    image: temporalio/ui:2.26.2
    profiles: ["temporal"]
    ports:
      - "8233:8080"
    depends_on:
      - temporal
```

**Usage**:
- `docker-compose up` — starts only backend + postgres (no kafka, monitoring, temporal)
- `docker-compose --profile kafka up` — adds kafka
- `docker-compose --profile monitoring up` — adds prometheus + grafana
- `docker-compose --profile temporal up` — adds temporal + temporal-ui
- `docker-compose --profile kafka --profile monitoring up` — adds kafka + monitoring

**Why**:
- Developers working on API features don't need Kafka/Temporal/monitoring running locally
- Reduces startup time and resource usage
- Keeps compose file comprehensive without forcing heavy infrastructure

## env_file and Environment Variables

**env_file pattern**:
```yaml
services:
  backend:
    env_file:
      - .env
    environment:
      MODE: server
      DEBUG: "true"
```

**env_file with optional secrets**:
```yaml
services:
  backend:
    env_file:
      - path: ./backend/.env.secrets
        required: false
    environment:
      MODE: server
```

**Key points**:
- `env_file: - .env` loads all vars from .env file
- `environment:` overrides or adds to env_file vars
- `required: false` allows compose to start even if .env.secrets is missing
- Never commit .env or .env.secrets (add to `.gitignore`)
- Commit `.env.example` with dummy values

**.env example**:
```bash
# .env (gitignored)
POSTGRES_USER=app
POSTGRES_PASSWORD=app
POSTGRES_DB=app
JWT_SECRET_KEY=dev-secret-key-change-in-prod
DEBUG=true
```

**.env.example** (committed):
```bash
# .env.example
POSTGRES_USER=app
POSTGRES_PASSWORD=change-me
POSTGRES_DB=app
JWT_SECRET_KEY=change-me
DEBUG=false
```

## Host Connectivity for Dev Mode

**Pattern (macOS/Windows Docker Desktop)**:
```yaml
services:
  backend:
    environment:
      MODE: server
      RELOAD: "true"
      # Connect to host services via host.docker.internal
      POSTGRES_HOST: host.docker.internal
      REDIS_HOST: host.docker.internal
      TEMPORAL_HOST: host.docker.internal
    volumes:
      - ./backend:/app
```

**Why**: Avoids running postgres/redis/temporal in containers when you already have them running on the host (native install or Docker on host network).

**Linux alternative**:
```yaml
services:
  backend:
    extra_hosts:
      - "host.docker.internal:host-gateway"
```

Or use `network_mode: "host"` (less portable):
```yaml
services:
  backend:
    network_mode: "host"
```

**Key points**:
- `host.docker.internal` is a special DNS name that resolves to the host machine's IP
- Works out-of-the-box on macOS/Windows Docker Desktop
- Linux requires `extra_hosts` or `network_mode: "host"`
- Useful for connecting to host postgres on port 5432, redis on 6379, etc.

## Full Example: Layered Compose Files

**Base (docker-compose.yml)**:
```yaml
version: '3.9'

services:
  api:
    build: .
    image: app:latest
    restart: always
    env_file:
      - .env
    depends_on:
      db:
        condition: service_healthy

  db:
    image: postgres:13.8-bullseye
    hostname: app-db
    environment:
      POSTGRES_USER: app
      POSTGRES_PASSWORD: app
    volumes:
      - db-data:/var/lib/postgresql/data
    healthcheck:
      test: pg_isready -U app
      interval: 2s

volumes:
  db-data:
```

**Dev (docker-compose.dev.yml)**:
```yaml
x-environment: &common-dev-env
  ENV: DEV
  POSTGRES_URL: postgresql://app:app@app-db:5432/app

services:
  server:
    image: app:latest
    ports:
      - '8000:80'
      - '5678:5678'
    environment:
      <<: *common-dev-env
      MODE: server
      RELOAD: "true"
    volumes:
      - .:/srv/app

  worker:
    image: app:latest
    environment:
      <<: *common-dev-env
      MODE: worker

  db:
    ports:
      - '5432:5432'
```

**Prod-test (docker-compose.prod-test.yml)**:
```yaml
services:
  backend:
    build: ./backend
    environment:
      ENVIRONMENT: production
      MODE: server
      DEBUG: "false"
```

**Personal override (docker-compose.override.yml, gitignored)**:
```yaml
services:
  server:
    environment:
      LOG_LEVEL: DEBUG
```

**Usage**:
- Dev mode: `docker-compose -f docker-compose.yml -f docker-compose.dev.yml up`
- Prod-test: `docker-compose -f docker-compose.yml -f docker-compose.prod-test.yml up --build`
- Personal dev mode: `docker-compose -f docker-compose.yml -f docker-compose.dev.yml up` (override merges automatically)
