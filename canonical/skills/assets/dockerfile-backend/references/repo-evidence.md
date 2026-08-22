# Real-World Dockerfile Patterns (Genericized)

Short, genericized snippets from production Python backend Dockerfiles, demonstrating patterns in the wild. All internal references, service names, and secrets have been removed.

## Multi-Stage Alpine Pattern

**Source**: Production microservice handling Kafka streaming and PostgreSQL

```dockerfile
ARG PYTHON_VERSION=3.10.15-alpine3.20

# Builder stage
FROM python:${PYTHON_VERSION} AS builder

ENV PYTHONUNBUFFERED=1

RUN apk update && apk upgrade && \
    apk add --no-cache curl openssh git librdkafka-dev g++ && \
    rm -rf /var/cache/apk/*

WORKDIR /srv/app

COPY ./requirements/requirements.txt .

# Create virtual environment in builder
RUN python -m venv /opt/venv
ENV VIRTUAL_ENV=/opt/venv
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

RUN pip install --upgrade --no-cache-dir pip wheel && \
    pip install --upgrade --no-cache-dir setuptools && \
    pip install --no-cache-dir -r requirements.txt

COPY . .

# Capture git SHA before removing .git
RUN git rev-parse HEAD > gitsha && rm -rf .git

# Runtime stage
FROM python:${PYTHON_VERSION}

ENV PYTHONUNBUFFERED=1

RUN apk update && apk upgrade && \
    apk add --no-cache vim librdkafka-dev && \
    rm -rf /var/cache/apk/*

WORKDIR /srv/app
COPY --from=builder /srv/app .
COPY --from=builder /opt/venv /opt/venv

ENV VIRTUAL_ENV=/opt/venv
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

EXPOSE 80

RUN chmod +x ci-test.sh && \
    mkdir -p /var/log/app && chmod 777 /var/log/app

ENTRYPOINT ["python", "entrypoint.py"]
```

**Key patterns**:
- ARG for parameterized Python version
- Multi-stage with explicit `AS builder` and `COPY --from=builder`
- Virtual environment in `/opt/venv` (outside app directory for volume mount compatibility)
- `git rev-parse HEAD > gitsha` for versioning before removing .git
- Separate build deps (g++, git, openssh) from runtime deps (vim, librdkafka-dev)
- Log directory creation with broad permissions (for non-root user compatibility)

## Multi-Stage Debian Slim Pattern

**Source**: Production service with Kafka, PostgreSQL, and Kerberos authentication

```dockerfile
ARG PYTHON_VERSION=3.11-slim-bookworm

FROM python:$PYTHON_VERSION as builder

ENV PYTHONUNBUFFERED=1

RUN apt update && apt upgrade -y && \
    apt-get install curl openssh-server git librdkafka-dev g++ -y && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /srv/app

COPY ./requirements/requirements.txt .

# Create virtual environment
RUN python -m venv /opt/venv
ENV VIRTUAL_ENV=/opt/venv
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

RUN pip3 install --upgrade pip setuptools wheel && \
    pip3 install -r ./requirements.txt

COPY . .
RUN git rev-parse HEAD > gitsha && rm -rf .git

FROM python:$PYTHON_VERSION

ENV PYTHONUNBUFFERED=1

RUN apt update && apt upgrade -y && \
    apt-get install vim librdkafka-dev -y && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /srv/app
COPY --from=builder /srv/app .
COPY --from=builder /opt/venv /opt/venv

ENV VIRTUAL_ENV=/opt/venv
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

EXPOSE 80
RUN chmod +x ci-test.sh
RUN mkdir -p /var/log/app && chmod 777 /var/log/app

ENTRYPOINT ["python", "entrypoint.py"]
```

**Key patterns**:
- Debian slim base for broader package compatibility
- `apt-get clean && rm -rf /var/lib/apt/lists/*` to reduce image size
- Separate upgrade + install in one RUN to minimize layers
- chmod +x on test script (for CI/CD health checks)

## Single-Stage Slim Pattern (FastAPI Service)

**Source**: Production REST API service

```dockerfile
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml .
RUN pip install --no-cache-dir ".[prod]"

COPY . .
ENV PYTHONPATH=/app
ENV WEB_CONCURRENCY=4

EXPOSE 8000
CMD ["gunicorn", "app.application:get_app()", \
     "--worker-class", "uvicorn.workers.UvicornWorker", \
     "--workers", "4", \
     "--bind", "0.0.0.0:8000", \
     "--timeout", "120", \
     "--graceful-timeout", "30", \
     "--access-logfile", "-"]
```

**Key patterns**:
- Single-stage for simpler services (no venv needed)
- Uses `pyproject.toml` with extras (`[prod]`)
- Gunicorn with uvicorn workers (ASGI server for FastAPI)
- WEB_CONCURRENCY env var (read by some frameworks for worker count)
- `--access-logfile -` sends logs to stdout for Docker logging
- Timeout and graceful-timeout tuning for long-running requests

## Comprehensive System Dependencies (Kafka + Postgres + Kerberos)

**Source**: Production service with full stack dependencies

```dockerfile
FROM python:3.11-slim

ARG PRIVATE_REGISTRY_TOKEN

ENV PYTHONUNBUFFERED=1

RUN apt-get update && \
    apt-get install -y tzdata curl git gcc g++ libc6-dev libpq5 libpq-dev \
        openssh-client libffi-dev build-essential make python3-dev \
        libcurl4-openssl-dev pkg-config libssl-dev zlib1g-dev liblz4-dev \
        libzstd-dev librdkafka-dev vim postgresql-client && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /srv/app
COPY . /srv/app

COPY requirements/requirements.txt .

RUN pip install --no-cache-dir --upgrade pip setuptools wheel
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /var/log/app && chmod 777 /var/log/app

EXPOSE 80

ENTRYPOINT ["python", "entrypoint.py"]
```

**Key patterns**:
- Comprehensive system dependencies in one RUN (all stack needs)
- tzdata for timezone support
- libpq5 + libpq-dev for PostgreSQL (both runtime and headers)
- librdkafka-dev for Kafka
- Compression libs (zlib1g-dev, liblz4-dev, libzstd-dev) for Kafka compression
- postgresql-client for psql debugging tool
- vim for in-container debugging
- ARG for private registry token (never echoed to logs)

## Entrypoint MODE Dispatch Pattern

**Source**: Production service running server/consumer/worker/cron from one image

```dockerfile
# ... (Dockerfile stages above)

ENTRYPOINT ["python", "entrypoint.py"]
```

**Corresponding entrypoint.py** (genericized):

```python
import asyncio
import os

from config.settings import loaded_config

def start_server():
    from app.main import main as server_main
    server_main()

def start_consumer():
    from services.kafka.consumer import main as consumer_main
    asyncio.run(consumer_main())

def start_temporal_worker():
    from services.temporal.run_workers import worker_main
    worker_mode = loaded_config.WORKER_MODE
    asyncio.run(worker_main(worker_mode))

def start_cron():
    from crons.setup import crons
    cron_job = loaded_config.CRON_JOB
    if cron_job:
        asyncio.run(crons[cron_job]())

mode_actions = {
    "server": start_server,
    "consumer": start_consumer,
    "temporal_worker": start_temporal_worker,
    "cron": start_cron,
}

if __name__ == "__main__":
    mode = loaded_config.MODE
    action = mode_actions.get(mode)
    if action:
        action()
    else:
        print(f"MODE {mode} not recognized")
```

**Key patterns**:
- MODE env var read from config (server/consumer/temporal_worker/cron)
- Lazy imports (only import the needed main function for the current MODE)
- asyncio.run() for async main functions
- Dictionary dispatch pattern (mode_actions map)
- Sub-mode env vars (WORKER_MODE, CRON_JOB) for finer-grained control

## Build Arg Secret Pattern (Anti-pattern, Included for Awareness)

**ANTI-PATTERN** (for learning purposes; DO NOT REPLICATE):

```dockerfile
# NEVER DO THIS: Hardcoded base64 token in Dockerfile
RUN curl -H "Authorization: Basic <HARDCODED_TOKEN>" \
    "https://internal-git.example.com/api/repos/infra/items?path=setup.sh" | sh
```

**Why this is dangerous**:
- Secrets leak into image layers (visible with `docker history`)
- Anyone with image access can extract the token
- Tokens can't be rotated without rebuilding all images

**Correct pattern** (use ARG but NEVER echo/print it):

```dockerfile
ARG PRIVATE_REGISTRY_TOKEN

# Fetch a setup script from private git (token used but never printed)
RUN curl -H "Authorization: Basic $PRIVATE_REGISTRY_TOKEN" \
    "https://internal-git.example.com/api/repos/infra/items?path=setup.sh" \
    2>&1 | sh
```

**Better pattern** (use multi-stage and don't persist the secret):

```dockerfile
ARG PRIVATE_REGISTRY_TOKEN

# Builder stage: use token to fetch dependencies
FROM python:3.11-slim AS builder
ARG PRIVATE_REGISTRY_TOKEN

RUN curl -H "Authorization: Basic $PRIVATE_REGISTRY_TOKEN" \
    "https://private-registry.example.com/api/packages/setup.sh" | sh && \
    pip install -r requirements.txt

# Runtime stage: secret not present
FROM python:3.11-slim
COPY --from=builder /opt/venv /opt/venv
# Secret is NOT in runtime stage
```

**Best pattern** (use Docker BuildKit secrets, never in layers):

```dockerfile
# syntax=docker/dockerfile:1.4
RUN --mount=type=secret,id=registry_token \
    curl -H "Authorization: Basic $(cat /run/secrets/registry_token)" \
    "https://private-registry.example.com/api/packages/setup.sh" | sh
```

Build with: `docker buildx build --secret id=registry_token,src=token.txt .`

**Key learning**: Never log or echo build-time secrets. Prefer BuildKit secrets or multi-stage builds where secrets live only in the builder stage.

## Non-Root User Pattern

**Source**: Production k8s deployment

```dockerfile
# ... (after COPY app and venv)

RUN groupadd --gid 1000 appuser && \
    useradd --uid 1000 --gid appuser --shell /bin/bash --create-home appuser && \
    mkdir -p /var/log/app && \
    chown -R appuser:appuser /srv/app /var/log/app

USER appuser

EXPOSE 8000
ENTRYPOINT ["python", "entrypoint.py"]
```

**Key patterns**:
- Fixed UID/GID (1000) for consistent permissions across environments
- chown application and log directories before switching users
- USER directive at the end (all subsequent commands run as appuser)
- Create home directory for appuser (needed for some libraries that write to ~/.cache)

## Health Check Pattern

**Source**: Production service deployed to ECS

```dockerfile
# Install curl in runtime stage
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*

# Add health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD curl --fail http://localhost:8000/health || exit 1
```

**Key patterns**:
- Separate curl install for health checks (only in runtime stage)
- `--fail` flag makes curl exit non-zero on HTTP errors
- `--start-period` gives the app time to start before health checks count toward failures
- `/health` endpoint is a standard convention (implement in FastAPI: `@app.get("/health")`)

## Summary of Real-World Patterns

1. **Multi-stage is standard** for production services (builder + runtime)
2. **Virtual environments in /opt/venv** for clean separation and volume compatibility
3. **git rev-parse + rm -rf .git** for versioning + security
4. **Comprehensive system deps upfront** (libpq, librdkafka, krb5, compression libs)
5. **entrypoint.py with MODE dispatch** for one-image-many-roles deployments
6. **Non-root users** for k8s security policies
7. **HEALTHCHECK in Dockerfile** for orchestrators (though k8s probes are preferred)
8. **Never hardcode secrets**; use ARG + multi-stage or BuildKit secrets

All patterns are production-tested and safe to replicate in new projects.
