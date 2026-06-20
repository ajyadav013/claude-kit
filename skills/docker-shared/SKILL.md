---
name: docker-shared
description: Shared Docker building blocks — base images with pre-installed dependencies published to private registries, .dockerignore conventions, and compose fragment reuse (YAML anchors, x- extension fields, external networks/volumes). Use when creating a base image to share heavy system dependencies across multiple services, setting up .dockerignore to exclude secrets/tests/build artifacts, or sharing compose configuration fragments across service stacks.
---

# Shared Docker Building Blocks

Patterns for reusable Docker infrastructure across multiple services — base images, build hygiene, and compose fragment reuse.

## When to use

- Creating a base image to share heavy system dependencies (gcc, build-essential, postgres client, Kafka libs) across multiple related services
- Publishing base images to a private registry (Harbor, ECR, ACR, GCR) and consuming them with tag or digest pinning
- Handling private registry / package authentication during image builds
- Standardizing .dockerignore across services to exclude secrets, tests, and development artifacts
- Sharing compose configuration fragments (common env vars, resource limits, logging config) across services using YAML anchors and extension fields
- Connecting services to external infrastructure (shared Kafka cluster, Redis instance, custom network) via external networks and volumes

## Core conventions

### Shared Base Images

**Pattern**: Create a `Dockerfile.base` that installs heavy, rarely-changing system dependencies (build tools, database clients, language runtimes, system libraries). Publish it to a private registry with versioned tags. Service Dockerfiles then `FROM <registry>/<org>/<service>-base:<tag>` to inherit those layers.

**Why**: Avoids reinstalling the same heavy dependencies in every service Dockerfile; speeds up builds; ensures consistent system-level configuration across services.

**Tag vs digest pinning**: Use tags (`v1`, `v2`, `v12`) for active development; switch to digest pinning (`@sha256:...`) in production for immutable guarantees.

**Multi-service reuse**: A single base image can serve multiple related services that share dependencies (e.g., a Python 3.11 base with PostgreSQL client, Kafka libs, and Kerberos tools used by 3-4 backend services).

**Workflow**: Build the base image, push to registry with a new tag (e.g., `v13`), update service Dockerfiles to reference the new tag, rebuild service images.

### Private Registry Authentication

**Build-time auth with ARG**: Pass a private registry or package manager token as a `--build-arg` at build time. The Dockerfile declares `ARG REGISTRY_TOKEN` and uses it to authenticate `docker login`, `pip install` from private package indexes, or `curl` to fetch private scripts.

**CRITICAL ANTI-PATTERN**: **NEVER echo, print, or write a build-arg secret to a RUN layer or the console.** Even a debug `RUN echo "$REGISTRY_TOKEN"` or `printf "%s\n" "$REGISTRY_TOKEN"` bakes the secret into the image layer and build logs, making it recoverable from the final image or CI logs.

**Secure alternative**: Use BuildKit `--secret` and `RUN --mount=type=secret,id=token` for build-time secrets that never appear in layers. For local dev without BuildKit, use a `.env` file with the token and pass via `docker build --build-arg REGISTRY_TOKEN=$(cat .env | grep TOKEN | cut -d= -f2)`, but never commit the `.env`.

**Example ARG pattern** (genericized, with anti-pattern shown for educational purposes):

```dockerfile
# Dockerfile.base
FROM python:3.11-slim

ARG PRIVATE_REGISTRY_TOKEN

# ❌ ANTI-PATTERN: This bakes the token into the image layer and build logs
# RUN echo "===== TOKEN START =====" && \
#     printf "%s\n" "$PRIVATE_REGISTRY_TOKEN" && \
#     echo "===== TOKEN END ====="

# ✅ Correct: Use the token WITHOUT printing it
RUN apt-get update && \
    apt-get install -y curl git && \
    curl -H "Authorization: Bearer $PRIVATE_REGISTRY_TOKEN" \
         https://internal-registry.example.com/scripts/setup.sh -o /tmp/setup.sh && \
    sh /tmp/setup.sh && \
    rm /tmp/setup.sh
```

**BuildKit secret mount** (preferred):

```dockerfile
# syntax=docker/dockerfile:1.4
FROM python:3.11-slim

RUN --mount=type=secret,id=registry_token \
    REGISTRY_TOKEN=$(cat /run/secrets/registry_token) && \
    curl -H "Authorization: Bearer $REGISTRY_TOKEN" \
         https://internal-registry.example.com/scripts/setup.sh -o /tmp/setup.sh && \
    sh /tmp/setup.sh && \
    rm /tmp/setup.sh

# Build with: docker buildx build --secret id=registry_token,src=token.txt .
```

### .dockerignore Conventions

**Purpose**: Exclude files from the build context to reduce image size, speed up builds, and prevent secrets from leaking into images.

**Standard exclusions**:
- **Version control**: `.git`, `.gitignore`
- **Dependencies**: `node_modules/`, `.venv/`, `venv/`, `__pycache__/`, `*.pyc`
- **Tests and coverage**: `tests/`, `*.test.js`, `.pytest_cache/`, `.coverage`, `htmlcov/`
- **Secrets**: `.env`, `.env.local`, `.env.*.local`, `.env.secrets`, `*.key`, `*.pem` (unless explicitly needed)
- **IDE**: `.vscode/`, `.idea/`, `*.swp`, `*.swo`
- **OS**: `.DS_Store`, `Thumbs.db`
- **Logs and artifacts**: `*.log`, `logs/`, `screenshots/`, `videos/`, `dist/`, `build/`
- **Docker files**: `Dockerfile*`, `docker-compose*`, `.dockerignore` (the Docker files themselves don't belong in the image)
- **Documentation**: `*.md`, `docs/` (unless your image serves docs)

**Include exceptions**: Use `!` to re-include specific files after a broader exclusion (e.g., `*.md` excludes all markdown, `!README.md` includes only the README).

**Example .dockerignore**:

```
# Version control
.git
.gitignore

# Dependencies
node_modules
npm-debug.log*
__pycache__
*.pyc
.venv
venv

# Tests
tests/
.pytest_cache/
.coverage
htmlcov/

# Secrets
.env
.env.*
*.key
*.pem

# IDE
.vscode
.idea
*.swp

# OS
.DS_Store
Thumbs.db

# Docker
Dockerfile*
docker-compose*
.dockerignore

# Documentation
*.md
!README.md

# Logs and artifacts
*.log
logs/
screenshots/
videos/
dist/
build/
```

### Shared Compose Fragments

**YAML anchors and aliases**: Define a block once with `x-<name>: &anchor-name`, then reference it with `<<: *anchor-name`.

**Common use cases**: Shared environment variables, logging configuration, resource limits, restart policies.

**Example**:

```yaml
version: '3.9'

# Define shared environment variables once
x-common-env: &common-env
  DATABASE_URL: postgresql://user:pass@db:5432/app
  REDIS_URL: redis://redis:6379/0
  LOG_LEVEL: INFO

# Define shared resource limits
x-resource-limits: &resource-limits
  deploy:
    resources:
      limits:
        memory: 2G
        cpus: '1.0'
      reservations:
        memory: 512M
        cpus: '0.5'

services:
  api:
    image: app:latest
    environment:
      <<: *common-env
      MODE: server
    <<: *resource-limits
    ports:
      - '8000:80'

  worker:
    image: app:latest
    environment:
      <<: *common-env
      MODE: worker
    <<: *resource-limits
```

**x- extension fields**: Top-level keys prefixed with `x-` are ignored by Docker Compose but can hold reusable fragments. Useful for defining shared config that doesn't fit into the `services:`, `networks:`, or `volumes:` sections.

**External networks and volumes**: Use `external: true` to reference infrastructure created outside the compose file (e.g., a shared Docker network for cross-service communication, or a persistent volume managed by k8s/Swarm).

**Example**:

```yaml
version: '3.9'

services:
  app:
    image: app:latest
    networks:
      - shared-network
    volumes:
      - shared-data:/data

networks:
  shared-network:
    external: true
    name: prod-network  # Must already exist (created externally)

volumes:
  shared-data:
    external: true
    name: prod-shared-data  # Must already exist
```

**Service extends** (deprecated but still used): Compose v2 supports `extends` to inherit config from another service in the same file or a different file. Prefer YAML anchors for same-file reuse; use `extends` only for cross-file inheritance.

**Compose include** (Compose v2.20+): Use `include` to import entire compose files as fragments:

```yaml
include:
  - path: ./docker-compose.db.yml
  - path: ./docker-compose.monitoring.yml

services:
  app:
    image: app:latest
    depends_on:
      - db  # Defined in docker-compose.db.yml
```

## Skeleton / example

### Base Image Workflow

**Dockerfile.base** (installs heavy system dependencies):

```dockerfile
FROM python:3.11-slim

ARG PRIVATE_REGISTRY_TOKEN

ENV PYTHONUNBUFFERED=1

# Install heavy system dependencies (example: PostgreSQL client, Kafka libs, build tools, Kerberos)
RUN apt-get update && \
    apt-get install -y tzdata curl git gcc g++ libc6-dev \
                       libpq5 libpq-dev openssh-client libffi-dev \
                       build-essential make python3-dev \
                       libcurl4-openssl-dev pkg-config libssl-dev \
                       zlib1g-dev liblz4-dev libzstd-dev librdkafka-dev \
                       vim postgresql-client krb5-user libkrb5-dev && \
    rm -rf /var/lib/apt/lists/*

# Example: Fetch a private setup script using the token (no echo/print!)
RUN curl -H "Authorization: Bearer $PRIVATE_REGISTRY_TOKEN" \
         https://internal-registry.example.com/setup/install.sh \
         -o /tmp/install.sh && \
    sh /tmp/install.sh && \
    rm /tmp/install.sh

# Example: Install Python dependencies from a private package index
COPY requirements/base-requirements.txt /tmp/
RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir \
        --index-url https://:$PRIVATE_REGISTRY_TOKEN@internal-pypi.example.com/simple \
        -r /tmp/base-requirements.txt && \
    rm /tmp/base-requirements.txt

WORKDIR /srv/app
```

**Build and publish**:

```bash
# Build the base image
docker build -f Dockerfile.base \
  --build-arg PRIVATE_REGISTRY_TOKEN=<REDACTED> \
  -t registry.example.com/base-images/myservice-base:v1 .

# Push to registry
docker push registry.example.com/base-images/myservice-base:v1

# Get digest for immutable pinning
docker inspect registry.example.com/base-images/myservice-base:v1 \
  --format='{{index .RepoDigests 0}}'
# Output: registry.example.com/base-images/myservice-base@sha256:abcdef123456...
```

**Service Dockerfile** (uses the base):

```dockerfile
# Use tag (mutable)
FROM registry.example.com/base-images/myservice-base:v1 AS builder

# Or use digest (immutable)
# FROM registry.example.com/base-images/myservice-base@sha256:abcdef123456... AS builder

# Copy application code (lightweight operation)
COPY . .

# Install application-specific dependencies
COPY requirements/app-requirements.txt .
RUN pip install --no-cache-dir -r app-requirements.txt

EXPOSE 80

ENTRYPOINT ["python", "entrypoint.py"]
```

### Shared Compose Example

```yaml
version: '3.9'

# Shared environment variables
x-common-env: &common-env
  DATABASE_URL: postgresql://user:pass@db:5432/app
  REDIS_URL: redis://redis:6379/0
  KAFKA_BROKERS: kafka:9092
  LOG_LEVEL: INFO

# Shared logging config
x-logging: &default-logging
  driver: json-file
  options:
    max-size: "10m"
    max-file: "3"

services:
  api:
    image: app:latest
    environment:
      <<: *common-env
      MODE: server
    logging: *default-logging
    networks:
      - app-net

  worker:
    image: app:latest
    environment:
      <<: *common-env
      MODE: worker
      WORKER_MODE: background_tasks
    logging: *default-logging
    networks:
      - app-net

  db:
    image: postgres:13
    environment:
      POSTGRES_USER: user
      POSTGRES_PASSWORD: pass
      POSTGRES_DB: app
    volumes:
      - db-data:/var/lib/postgresql/data
    logging: *default-logging
    networks:
      - app-net

networks:
  app-net:

volumes:
  db-data:
```

## Anti-patterns to avoid

- **Echoing/printing build-arg secrets in Dockerfile RUN layers** — even a debug `RUN echo "$REGISTRY_TOKEN"` bakes the secret into the image layer and build logs; use BuildKit `--mount=type=secret` instead.
- **Committing .env files with registry tokens** — always `.gitignore` them; use CI secrets or secret managers.
- **Forgetting to tag base images with versions** — always version base images (`v1`, `v2`, `v12`) to enable rollback and track changes.
- **Missing .dockerignore** — without it, `.git`, `node_modules`, `.venv`, and secrets leak into the build context and image.
- **Duplicating common environment variables across services in compose** — use YAML anchors (`x-common-env: &common-env`) to define once and reuse.
- **Creating external networks/volumes that don't exist** — `docker network create <name>` and `docker volume create <name>` must be run before `docker-compose up` if `external: true` is used.
- **Ignoring README.md when you need it in the image** — use `*.md` then `!README.md` to exclude all markdown except the README.
- **Using ARG secrets after the layer that needs them** — ARG values persist in build history; unset them or use multi-stage builds to discard the builder stage.
- **Re-installing the same heavy deps in every service** — extract them into a shared base image instead.

## References

- [shared-base-images.md](./references/shared-base-images.md) — Base image pattern, tag vs digest pinning, registry auth
- [dockerignore-and-build-secrets.md](./references/dockerignore-and-build-secrets.md) — .dockerignore conventions, ARG secrets anti-pattern, BuildKit secrets
- [shared-compose-fragments.md](./references/shared-compose-fragments.md) — YAML anchors, x- extension fields, external networks/volumes
- [repo-evidence.md](./references/repo-evidence.md) — Genericized snippets from production services

**Cross-references**:
- [containerization-and-deployment](../containerization-and-deployment/SKILL.md) — Multi-stage builds, entrypoint MODE dispatch, docker-compose patterns
