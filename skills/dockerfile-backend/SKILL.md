---
name: dockerfile-backend
description: Writing multi-stage Dockerfiles for Python/FastAPI backend services — builder vs runtime stages, slim vs alpine base image trade-offs, system dependency patterns (libpq/librdkafka/krb5), dependency caching with layer optimization, non-root users, multi-mode entrypoints, and health checks. Use when containerizing Python backend services, optimizing Docker build times and image sizes, handling Kafka/Postgres/Kerberos system dependencies, or implementing secure production-ready container images.
---

# Dockerfile for Python Backend Services

Multi-stage Dockerfile patterns for Python/FastAPI backend services, covering base image selection, system dependencies, layer caching, security hardening, and multi-mode entrypoints.

## When to use

- Containerizing Python backend services (FastAPI, Flask, Django)
- Optimizing Docker build times through effective layer caching
- Minimizing production image sizes with multi-stage builds
- Installing system dependencies for Kafka clients, PostgreSQL, or Kerberos authentication
- Implementing secure container images with non-root users
- Setting up multi-mode entrypoints (server/consumer/worker/cron from one image)
- Debugging production Dockerfile build failures or runtime issues

## Core conventions

### Base Image Selection: Slim vs Alpine

**Python slim (Debian-based)**: Use `python:3.11-slim` or `python:3.12-slim` for broader compatibility with compiled extensions (psycopg2, cryptography, numpy). Larger base (~150MB) but fewer build issues.

**Python alpine**: Use `python:3.10-alpine3.20` or `python:3.11-alpine` for minimal footprint (~50MB). Requires more build dependencies (g++, musl-dev, libffi-dev) and may have compatibility issues with some wheels.

**Recommendation**: Start with slim for faster development; switch to alpine only if image size is critical and you've verified all dependencies build correctly.

### Multi-Stage Builds: Builder + Runtime

**Builder stage**: Install all build tools, compile dependencies, create virtual environment. This stage can be large.

**Runtime stage**: Copy only the compiled venv and application code. Install minimal runtime-only dependencies.

**Why**: Keeps the final image small by excluding build tools (gcc, g++, git, build-essential) that are only needed during pip install.

**Key pattern**: Use `COPY --from=builder /opt/venv /opt/venv` to transfer the virtual environment from builder to runtime.

### System Dependencies for Python Backend Stacks

**PostgreSQL client**: 
- Slim: `libpq-dev` (build), `libpq5` (runtime)
- Alpine: `postgresql-dev` (build), `libpq` (runtime)

**Kafka (confluent-kafka, kafka-python with librdkafka)**:
- Slim: `librdkafka-dev` (build + runtime), plus `libssl-dev zlib1g-dev liblz4-dev libzstd-dev` for compression
- Alpine: `librdkafka-dev` (build + runtime)

**Kerberos (for GSSAPI/Kafka SASL_GSSAPI)**:
- Slim: `libkrb5-dev krb5-user` (build), `krb5-user` (runtime)
- Alpine: `krb5-dev` (build), `krb5-libs` (runtime)

**Common build dependencies**:
- Slim: `build-essential gcc g++ make python3-dev libffi-dev libssl-dev pkg-config`
- Alpine: `gcc g++ make musl-dev libffi-dev openssl-dev`

**Always clean up**: `rm -rf /var/lib/apt/lists/*` (slim) or `rm -rf /var/cache/apk/*` (alpine) after installing to reduce layer size.

### Dependency Caching and Layer Optimization

**Copy dependency manifest FIRST**: `COPY requirements.txt .` or `COPY pyproject.toml .` before `COPY . .`. Docker caches layers; if only application code changes, dependencies won't reinstall.

**For requirements.txt projects**:
```dockerfile
COPY requirements/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
```

**For pyproject.toml projects**:
```dockerfile
COPY pyproject.toml .
RUN pip install --no-cache-dir ".[prod]"
COPY . .
```

**For Poetry projects**:
```dockerfile
COPY pyproject.toml poetry.lock ./
RUN poetry install --no-dev --no-root
COPY . .
RUN poetry install --no-dev  # Install the project itself
```

**Use `--no-cache-dir`**: Skips pip's download cache, reducing image size by ~100-200MB.

### Virtual Environments in Docker

**Builder pattern**: Create venv in `/opt/venv`, activate it in builder, then copy to runtime stage.

**Why use venv in Docker**: Isolates dependencies from system Python; makes COPY from builder to runtime stage clean.

**Activation pattern**:
```dockerfile
RUN python -m venv /opt/venv
ENV VIRTUAL_ENV=/opt/venv
ENV PATH="$VIRTUAL_ENV/bin:$PATH"
```

**Alternative**: Skip venv and install directly to system Python if using single-stage builds for simpler services.

### Security Hardening

**Non-root user**: Create and use a non-root user for running the application (especially important for k8s/Cloud Run production deployments).

**Remove .git directory**: After capturing commit SHA for versioning, remove .git to avoid leaking history/secrets: `RUN git rev-parse HEAD > gitsha && rm -rf .git`

**Set `PYTHONUNBUFFERED=1`**: Forces Python stdout/stderr to be unbuffered; critical for seeing logs in Docker/k8s.

**Set `PYTHONDONTWRITEBYTECODE=1`**: Prevents Python from writing .pyc files, reducing image size and avoiding permission issues.

**Use specific image tags**: Never use `:latest` in production; pin to `python:3.11-slim-bookworm` or `python:3.10.15-alpine3.20`.

### Multi-Mode Entrypoint Pattern

**Single image, multiple roles**: Use `entrypoint.py` that reads `MODE` env var and dispatches to different main functions (server, consumer, worker, cron).

**Why**: Deploy the same Docker image to multiple services by varying only env vars; simplifies CI/CD (one build, many deploys).

**Standard modes**: `server` → FastAPI/uvicorn/gunicorn, `consumer` → Kafka consumer, `worker` or `temporal_worker` → background task worker, `cron` → scheduled job.

**See the broader containerization-and-deployment skill for full entrypoint.py patterns.**

### Gunicorn + Uvicorn for FastAPI

**Production pattern**: Use gunicorn with uvicorn workers (ASGI support).

**Example CMD**:
```dockerfile
CMD ["gunicorn", "app.main:app", \
     "--worker-class", "uvicorn.workers.UvicornWorker", \
     "--workers", "4", \
     "--bind", "0.0.0.0:8000", \
     "--timeout", "120", \
     "--graceful-timeout", "30", \
     "--access-logfile", "-"]
```

**For entrypoint.py pattern**: Use `ENTRYPOINT ["python", "entrypoint.py"]` instead of CMD.

### Health Checks

**Add HEALTHCHECK to Dockerfile** (optional but recommended for k8s/ECS):
```dockerfile
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD curl --fail http://localhost:8000/health || exit 1
```

**Install curl in runtime stage**: `apt-get install -y curl` (slim) or `apk add curl` (alpine).

**Alternative**: Use k8s liveness/readiness probes instead of Dockerfile HEALTHCHECK.

## Skeleton / example

### Multi-Stage Slim Dockerfile (PostgreSQL + Kafka + Kerberos)

```dockerfile
ARG PYTHON_VERSION=3.11-slim-bookworm

# Builder stage
FROM python:$PYTHON_VERSION AS builder

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Install build dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        build-essential \
        gcc \
        g++ \
        make \
        python3-dev \
        libpq-dev \
        librdkafka-dev \
        libkrb5-dev \
        libffi-dev \
        libssl-dev \
        pkg-config \
        zlib1g-dev \
        liblz4-dev \
        libzstd-dev \
        git \
        curl && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /srv/app

# Copy dependency manifest first for layer caching
COPY requirements/requirements.txt .

# Create and activate virtual environment
RUN python -m venv /opt/venv
ENV VIRTUAL_ENV=/opt/venv
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

# Install dependencies
RUN pip install --upgrade --no-cache-dir pip wheel setuptools && \
    pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Capture git SHA and remove .git for security
RUN git rev-parse HEAD > gitsha && rm -rf .git

# Runtime stage
FROM python:$PYTHON_VERSION

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Install runtime-only dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        libpq5 \
        librdkafka-dev \
        krb5-user \
        postgresql-client \
        vim \
        curl && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /srv/app

# Copy virtual environment and application from builder
COPY --from=builder /srv/app .
COPY --from=builder /opt/venv /opt/venv

ENV VIRTUAL_ENV=/opt/venv
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

# Create non-root user (optional but recommended)
RUN groupadd --gid 1000 appuser && \
    useradd --uid 1000 --gid appuser --shell /bin/bash --create-home appuser && \
    mkdir -p /var/log/app && \
    chown -R appuser:appuser /srv/app /var/log/app

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD curl --fail http://localhost:8000/health || exit 1

ENTRYPOINT ["python", "entrypoint.py"]
```

### Multi-Stage Alpine Dockerfile (Minimal Footprint)

```dockerfile
ARG PYTHON_VERSION=3.10.15-alpine3.20

# Builder stage
FROM python:${PYTHON_VERSION} AS builder

ENV PYTHONUNBUFFERED=1

RUN apk update && apk upgrade && \
    apk add --no-cache \
        curl \
        git \
        gcc \
        g++ \
        musl-dev \
        libffi-dev \
        openssl-dev \
        librdkafka-dev \
        postgresql-dev && \
    rm -rf /var/cache/apk/*

WORKDIR /srv/app

COPY ./requirements/requirements.txt .

# Create virtual environment
RUN python -m venv /opt/venv
ENV VIRTUAL_ENV=/opt/venv
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

RUN pip install --upgrade --no-cache-dir pip wheel setuptools && \
    pip install --no-cache-dir -r requirements.txt

COPY . .
RUN git rev-parse HEAD > gitsha && rm -rf .git

# Runtime stage
FROM python:${PYTHON_VERSION}

ENV PYTHONUNBUFFERED=1

RUN apk update && apk upgrade && \
    apk add --no-cache \
        vim \
        librdkafka-dev \
        libpq \
        curl && \
    rm -rf /var/cache/apk/*

WORKDIR /srv/app
COPY --from=builder /srv/app .
COPY --from=builder /opt/venv /opt/venv

ENV VIRTUAL_ENV=/opt/venv
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

EXPOSE 80

RUN mkdir -p /var/log/app && chmod 777 /var/log/app

ENTRYPOINT ["python", "entrypoint.py"]
```

### Single-Stage Slim Dockerfile (Simpler Services)

```dockerfile
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy dependency manifest first
COPY pyproject.toml .
RUN pip install --no-cache-dir ".[prod]"

# Copy application code
COPY . .
ENV PYTHONPATH=/app

EXPOSE 8000

CMD ["gunicorn", "app.main:app", \
     "--worker-class", "uvicorn.workers.UvicornWorker", \
     "--workers", "4", \
     "--bind", "0.0.0.0:8000", \
     "--timeout", "120", \
     "--graceful-timeout", "30", \
     "--access-logfile", "-"]
```

## Anti-patterns to avoid

- **Installing build tools in the runtime stage** — use multi-stage builds; only runtime deps in the final stage (e.g., `libpq5` not `libpq-dev`).
- **Copying application code before dependencies** — breaks Docker layer caching; copy `requirements.txt` or `pyproject.toml` first, install, then copy code.
- **Not cleaning up package manager caches** — always `rm -rf /var/lib/apt/lists/*` (slim) or `rm -rf /var/cache/apk/*` (alpine) after `apt-get install` or `apk add`.
- **Using `:latest` tags in production** — pin to specific Python version tags like `3.11-slim-bookworm` or `3.10.15-alpine3.20`.
- **Forgetting `PYTHONUNBUFFERED=1`** — logs buffer in Docker; set this env var for immediate stdout/stderr output.
- **Not using `--no-cache-dir` with pip** — leaves ~100-200MB of pip cache in the image; always use `pip install --no-cache-dir`.
- **Running as root in production** — create a non-root user (especially important for k8s security policies).
- **Hardcoding secrets or credentials in Dockerfile** — always use env vars or secret managers; never `ENV API_KEY=<secret>` or `ARG` for runtime secrets.
- **Installing unnecessary packages** — audit your runtime stage; remove vim/curl/git if not needed (except for debugging images).
- **Not separating dev and prod requirements** — use `requirements/requirements.txt` for prod, `requirements/dev-requirements.txt` for local dev; never install pytest/black/mypy in production images.

## References

- [backend-dockerfile-anatomy.md](./references/backend-dockerfile-anatomy.md) — Detailed breakdown of each Dockerfile layer and why it's structured that way
- [system-deps-and-caching.md](./references/system-deps-and-caching.md) — System dependency patterns for Kafka, PostgreSQL, Kerberos; layer caching strategies
- [repo-evidence.md](./references/repo-evidence.md) — Real-world Dockerfile patterns from production services (genericized)
- [containerization-and-deployment skill](../containerization-and-deployment/SKILL.md) — Broader context: entrypoint.py MODE dispatch, docker-compose, Cloud Run deployment, secrets handling
