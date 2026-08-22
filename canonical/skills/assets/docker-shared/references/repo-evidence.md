# Repository Evidence

Genericized snippets from production services demonstrating shared Docker patterns.

## Base Image Pattern

**File**: `Dockerfile.base` (from multiple backend services)

**Pattern**: Heavy system dependencies installed once in a base image, published to a private registry.

```dockerfile
FROM python:3.11-slim

ARG PRIVATE_REGISTRY_TOKEN

ENV PYTHONUNBUFFERED=1

# Install heavy system dependencies (PostgreSQL, Kafka, Kerberos, build tools)
RUN apt-get update && \
    apt-get install -y tzdata curl git gcc g++ libc6-dev \
                       libpq5 libpq-dev openssh-client libffi-dev \
                       build-essential make python3-dev \
                       libcurl4-openssl-dev pkg-config libssl-dev \
                       zlib1g-dev liblz4-dev libzstd-dev librdkafka-dev \
                       vim postgresql-client krb5-user libkrb5-dev && \
    rm -rf /var/lib/apt/lists/*

# Setup SSH configuration (for git over SSH)
RUN mkdir -p /root/.ssh

# Fetch a private setup script using the token
# ❌ ANTI-PATTERN OBSERVED IN PRODUCTION (do not replicate):
# The original Dockerfile echoed the token to build logs and wrote it to files
# This is shown here for educational purposes — NEVER do this in production
# RUN echo "===== TOKEN START =====" && \
#     printf "%s\n" "$PRIVATE_REGISTRY_TOKEN" > /tmp/token.txt && \
#     cat /tmp/token.txt && \
#     echo "===== TOKEN END ====="

# ✅ Correct: Use the token without printing it
RUN set -e; \
    STATUS=$(curl -s -o /tmp/setup.sh \
        -w "%{http_code}" \
        -H "Authorization: Basic $PRIVATE_REGISTRY_TOKEN" \
        "https://internal-registry.example.com/scripts/setup.sh"); \
    if [ "$STATUS" != "200" ]; then \
        echo "❌ CURL AUTH FAILED"; \
        exit 1; \
    fi; \
    sh /tmp/setup.sh && \
    rm /tmp/setup.sh

RUN chmod 600 /root/.ssh/id_rsa
RUN printf "Host internal-git.example.com\n\tHostName internal-git.example.com\n\tUser git\n\tStrictHostKeyChecking no\n" >> /root/.ssh/config

# Set working directory
WORKDIR /srv/app

# Copy and install Python requirements (heavy operation)
COPY requirements/requirements.txt .
RUN pip install --no-cache-dir --upgrade pip setuptools wheel
RUN pip install --no-cache-dir -r requirements.txt

# Create log directory
RUN mkdir -p /var/log/app && chmod 777 /var/log/app
```

**Observations**:
- Two services (`serviceA` and `serviceB`) both use this base image pattern
- Base image tagged as `v1`, `v2`, `v12` in the private registry
- Service Dockerfiles reduced to ~15 lines after introducing the base

## Service Dockerfile Using Base

**File**: `Dockerfile` (from multiple backend services)

**Pattern**: Service Dockerfile inherits from the base, copies application code, and runs.

```dockerfile
# Use tag (mutable)
FROM registry.example.com/base-images/project/service-base:v12 AS builder

# Or use digest (immutable)
# FROM registry.example.com/base-images/project/service-base@sha256:3e9e23235cf89f858e953be0511321e7141f2042f45458dc984746e5975a5cc1 AS builder

# Copy application code (lightweight operation)
COPY . .

# Expose port
EXPOSE 80

# Run the application
ENTRYPOINT ["python", "entrypoint.py"]
```

**Observations**:
- Service Dockerfiles are minimal (FROM base, COPY code, ENTRYPOINT)
- Some services use tag pinning (`v12`), others use digest pinning (`@sha256:...`)
- Comment in the Dockerfile suggests digest pinning for production

## .dockerignore Patterns

**File**: `.dockerignore` (from multiple services)

**Pattern**: Exclude version control, dependencies, tests, secrets, IDE files, OS files, Docker files, and logs.

```
# Git and version control
.git
.gitignore
*.md
!README.md

# Python cache and artifacts
__pycache__/
*.py[cod]
*$py.class
*.so
.Python
build/
dist/
*.egg-info/

# Virtual environments
venv/
env/
.venv/

# IDE files
.vscode/
.idea/
*.swp
*.swo
*~

# Test artifacts
screenshots/
videos/
allure-results/
allure-report/
logs/
*.log

# OS specific files
.DS_Store
Thumbs.db

# Temporary files
*.tmp
*.temp
temp/
tmp/

# Coverage reports
htmlcov/
.coverage
.pytest_cache/

# Local configuration files that shouldn't be in container
.env
.env.local
.env.*.local

# Node.js (if any)
node_modules/
npm-debug.log*
```

**Observations**:
- Consistent `.dockerignore` patterns across 10+ services
- Python services exclude `__pycache__`, `.venv`, `.pytest_cache`
- Node.js services exclude `node_modules`, `coverage`
- All services exclude `.env`, `.git`, IDE files, and Docker files

## Shared Compose Environment Variables

**File**: `docker-compose.yml` (from multiple services)

**Pattern**: YAML anchor defines common env vars once, reused across services.

```yaml
version: '3.4'

x-environment: &common-environment-variables
  ENV: DEV
  POSTGRES_URL: postgresql://admin:pass@postgres:5432/app_db
  KAFKA_BROKERS: kafka:29092
  REDIS_URL: redis://redis:6379/9?decode_responses=true
  GOOGLE_CLOUD_PROJECT: project-dev

services:
  app-server:
    build:
      context: .
      dockerfile: Dockerfile
    image: app:latest
    ports:
      - '8081:80'
      - '5679:5679'
    environment:
      <<: *common-environment-variables
      MODE: server
      DEBUG_PORT: 5679
    volumes:
      - .:/srv/app
      - $HOME/.config/gcloud:/root/.config/gcloud

  db-events-worker:
    image: app:latest
    ports:
      - '5680:5680'
    environment:
      <<: *common-environment-variables
      MODE: worker
      WORKER_MODE: db_events_publisher
      DEBUG_PORT: 5680
    volumes:
      - .:/srv/app

  audit-consumer:
    image: app:latest
    ports:
      - '5681:5681'
    environment:
      <<: *common-environment-variables
      MODE: consumer
      CONSUMER_NAME: audit_consumer
      DEBUG_PORT: 5681
    volumes:
      - .:/srv/app
```

**Observations**:
- YAML anchor `x-environment: &common-environment-variables` used in 5+ services
- Same `image: app:latest` reused for server, worker, consumer, cron
- Only `MODE` and role-specific env vars differ
- Unique debug ports (5679, 5680, 5681) per container

## External Networks

**File**: `docker-compose.yml` (from multiple services)

**Pattern**: External network for cross-service communication.

```yaml
version: '3.4'

services:
  app-server:
    image: app:latest
    networks:
      - app-network

networks:
  app-network:
    external: true
    name: local-infra-network
```

**Observations**:
- Multiple compose files across different repos reference the same `local-infra-network`
- Allows services from different repos to communicate (e.g., multiple backends connecting to shared Kafka)
- The network is created externally: `docker network create local-infra-network`

## Resource Limits and Health Checks

**File**: `docker-compose.yml` (from test automation service)

**Pattern**: Resource limits, health checks, and profiles.

```yaml
version: '3.8'

services:
  test-api:
    build:
      context: .
      dockerfile: Dockerfile.api
      args:
        PRIVATE_REGISTRY_TOKEN: ${PRIVATE_REGISTRY_TOKEN}
    container_name: test-automation-api
    environment:
      - TEST_ENV=${TEST_ENV:-SIT}
      - HEADLESS=${HEADLESS:-true}
      - BROWSER_TYPE=${BROWSER_TYPE:-chromium}
    volumes:
      - ./logs:/srv/test_automation/logs
      - ./screenshots:/srv/test_automation/screenshots
      - nfs-test-reports:/mnt/nfs/test-reports
    ports:
      - "8000:8000"
    security_opt:
      - seccomp:unconfined  # Required for Chrome/Chromium
    deploy:
      resources:
        limits:
          memory: 3G
          cpus: '2.0'
        reservations:
          memory: 1G
          cpus: '0.5'
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 40s
    restart: unless-stopped
    networks:
      - test-network

volumes:
  nfs-test-reports:
    driver: local
    driver_opts:
      type: nfs
      o: addr=nfs-server.example.com,rw
      device: ":/export/test-reports"
```

**Observations**:
- Resource limits (`memory: 3G`, `cpus: '2.0'`) standardized across services
- Health checks for API services (`curl -f http://localhost:8000/health`)
- NFS volume for shared test reports across multiple test runners
- Profiles (`legacy`, `reporting`) to start optional services

## Build Arg Token Passing

**File**: `docker-compose.yml` (from multiple services)

**Pattern**: Pass build-time token via `args`.

```yaml
version: '3.8'

services:
  test-api:
    build:
      context: .
      dockerfile: Dockerfile.api
      args:
        PRIVATE_REGISTRY_TOKEN: ${PRIVATE_REGISTRY_TOKEN}
    image: test-automation-api:latest
```

**Build command**:

```bash
# .env file (NOT committed to git)
PRIVATE_REGISTRY_TOKEN=<REDACTED>

# Compose reads from .env automatically
docker-compose build
```

**Observations**:
- Build args passed from `.env` file (never committed)
- The Dockerfile receives the token and uses it WITHOUT printing it
- The production code incorrectly echoed the token (anti-pattern observed)
