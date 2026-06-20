# Backend Dockerfile Anatomy

Detailed breakdown of each layer in a multi-stage Python backend Dockerfile and the reasoning behind every line.

## Multi-Stage Pattern: Builder + Runtime

The core insight: **separate build-time dependencies from runtime dependencies** to keep the final image small and secure.

### Builder Stage: Full Build Environment

```dockerfile
ARG PYTHON_VERSION=3.11-slim-bookworm
FROM python:$PYTHON_VERSION AS builder
```

**Why ARG + FROM**: ARG defines a build-time variable; FROM uses it to parameterize the base image. This allows changing the Python version at build time: `docker build --build-arg PYTHON_VERSION=3.12-slim .`

**Why AS builder**: Names the stage so the runtime stage can reference it with `COPY --from=builder`.

```dockerfile
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
```

**PYTHONUNBUFFERED=1**: Forces Python to write stdout/stderr immediately without buffering. Critical for Docker logs; without this, logs may not appear until the process exits or the buffer fills.

**PYTHONDONTWRITEBYTECODE=1**: Prevents Python from writing .pyc bytecode files. In Docker, bytecode files are written to the same directory as .py files; if you mount a volume over the source directory, .pyc files can cause permission issues or cache staleness. Disabling bytecode slightly slows imports but avoids these issues.

```dockerfile
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
```

**Why all these packages**: Many Python packages with C extensions require compilation during `pip install`. Each package here serves a purpose:

- `build-essential gcc g++ make python3-dev`: Core C/C++ compilation toolchain; required for any package with C extensions (psycopg2, cryptography, numpy, etc.)
- `libpq-dev`: PostgreSQL client library headers; required to build psycopg2 or psycopg3
- `librdkafka-dev`: Kafka C library; required to build confluent-kafka-python (the high-performance Kafka client)
- `libkrb5-dev`: Kerberos headers; required for GSSAPI/Kerberos authentication (e.g., Kafka with SASL_GSSAPI)
- `libffi-dev libssl-dev pkg-config`: Required for cryptography, PyOpenSSL, and other security libraries
- `zlib1g-dev liblz4-dev libzstd-dev`: Compression libraries; required for Kafka producer/consumer compression (gzip, lz4, zstd)
- `git`: Required if your requirements.txt includes git+https:// dependencies
- `curl`: Useful for health checks and debugging

**--no-install-recommends**: Skips "recommended" packages (e.g., documentation, man pages); reduces image size by ~100-200MB.

**rm -rf /var/lib/apt/lists/\***: Removes apt package cache; reduces image size by ~50-100MB. Always do this in the same RUN command as `apt-get install` to ensure the cache doesn't persist in the layer.

**Why chain with `&&` and `\`**: Docker creates one layer per RUN command. Chaining commands with `&&` keeps them in a single layer, reducing image size and build time. The `\` allows splitting across multiple lines for readability.

```dockerfile
WORKDIR /srv/app
```

**Why /srv/app**: Standard convention for application code. `/srv` is intended for "data served by the system" (per Linux FHS). `/app` is also common; choose one and be consistent.

```dockerfile
COPY requirements/requirements.txt .
```

**Why copy requirements FIRST**: Docker layer caching. If requirements.txt hasn't changed, Docker reuses the cached layer from the next RUN command (pip install). If you `COPY . .` first, any code change invalidates the cache and forces reinstalling all dependencies.

**Why `requirements/requirements.txt` not `requirements.txt`**: Many projects organize dependencies into subdirectories: `requirements/requirements.txt` (prod), `requirements/dev-requirements.txt` (local dev), `requirements/test-requirements.txt` (CI). This pattern keeps the Dockerfile installing only prod dependencies.

```dockerfile
RUN python -m venv /opt/venv
ENV VIRTUAL_ENV=/opt/venv
ENV PATH="$VIRTUAL_ENV/bin:$PATH"
```

**Why create a virtual environment in Docker**: It seems redundant (Docker already isolates the environment), but it serves two purposes:

1. **Clean separation for multi-stage builds**: You can COPY only `/opt/venv` to the runtime stage, leaving system Python and site-packages behind.
2. **Consistency with local dev**: If developers use venvs locally, using one in Docker keeps behavior consistent.

**Why /opt/venv**: Standard location for shared venvs (outside the application directory). If you mount the application directory as a volume during local dev, the venv won't be overwritten.

**Setting PATH**: Prepending `$VIRTUAL_ENV/bin` activates the venv; all subsequent `python` and `pip` commands use the venv's Python.

```dockerfile
RUN pip install --upgrade --no-cache-dir pip wheel setuptools && \
    pip install --no-cache-dir -r requirements.txt
```

**Why upgrade pip/wheel/setuptools first**: Older versions may not support modern wheel formats (PEP 517/518). Upgrading first avoids obscure build failures.

**--no-cache-dir**: Skips pip's download cache (normally `~/.cache/pip`). In Docker, the cache directory is inside the image layer, adding ~100-200MB. Since Docker layers already cache the result, pip's cache is redundant.

**Why separate RUN commands**: You could merge with the previous venv creation, but separating makes it clearer which step failed if the build breaks.

```dockerfile
COPY . .
```

**Copy application code AFTER installing dependencies**: Layer caching. Code changes frequently; dependencies change rarely. By copying code last, you maximize cache hits.

```dockerfile
RUN git rev-parse HEAD > gitsha && rm -rf .git
```

**Capture git SHA**: Writes the current commit hash to a `gitsha` file. Useful for versioning/logging (e.g., include commit SHA in API `/version` endpoint or Sentry tags).

**Remove .git**: The .git directory is large (can be 10-100MB+) and may contain sensitive history (old secrets, internal comments). Removing it reduces image size and avoids leaking information.

**Why in the same RUN**: If you split across two RUN commands, the first layer includes .git, and the second layer only marks it deleted (Docker layers are additive). Chaining in one RUN ensures .git never persists in any layer.

### Runtime Stage: Minimal Production Environment

```dockerfile
FROM python:$PYTHON_VERSION
```

**Same base image as builder**: Ensures glibc/musl version matches. Using a different base (e.g., alpine for builder, slim for runtime) can cause shared library version mismatches.

```dockerfile
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
```

**Repeat ENV from builder**: ENV commands are stage-specific; they don't carry over from builder to runtime. Always set these in the runtime stage too.

```dockerfile
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        libpq5 \
        librdkafka-dev \
        krb5-user \
        postgresql-client \
        vim \
        curl && \
    rm -rf /var/lib/apt/lists/*
```

**Runtime-only dependencies**: Notice the difference from the builder stage:

- `libpq5` (not `libpq-dev`): Runtime library for PostgreSQL; psycopg2 needs this to connect to Postgres at runtime, but not the headers (-dev) to compile.
- `librdkafka-dev`: Still needed at runtime for confluent-kafka-python (the library dynamically links to librdkafka.so). **Note**: This is a runtime dep, not just build-time for Kafka.
- `krb5-user`: Runtime Kerberos tools (kinit, klist); required for GSSAPI authentication at runtime.
- `postgresql-client`: Provides `psql` command-line tool; useful for debugging database issues in production (exec into container, run `psql`).
- `vim curl`: Debugging tools. In production, you may omit these to minimize attack surface; in dev/staging images, they're invaluable for troubleshooting.

**No build-essential, gcc, g++**: These are build-time only; omitting them saves ~150-200MB.

```dockerfile
WORKDIR /srv/app
COPY --from=builder /srv/app .
COPY --from=builder /opt/venv /opt/venv
```

**COPY --from=builder**: Copies files from the builder stage to the runtime stage. Only the application code and venv are transferred; all build tools and intermediate files are left behind.

**Two separate COPY commands**: You could combine into one, but separating makes it clear what's being copied from where.

```dockerfile
ENV VIRTUAL_ENV=/opt/venv
ENV PATH="$VIRTUAL_ENV/bin:$PATH"
```

**Re-activate the venv in runtime**: Even though we copied the venv, we need to set PATH again to use it (ENV from builder doesn't carry over).

```dockerfile
RUN groupadd --gid 1000 appuser && \
    useradd --uid 1000 --gid appuser --shell /bin/bash --create-home appuser && \
    mkdir -p /var/log/app && \
    chown -R appuser:appuser /srv/app /var/log/app

USER appuser
```

**Non-root user**: By default, Docker containers run as root (UID 0). Running as root is a security risk; if an attacker exploits your application, they have root inside the container. Kubernetes security policies often block root containers.

**UID/GID 1000**: Standard first non-system user ID. Using a consistent UID across images makes volume permission management easier.

**chown directories**: The application and log directories must be writable by appuser; chown transfers ownership from root.

**USER appuser**: All subsequent commands (and the ENTRYPOINT) run as appuser, not root.

**When to skip**: If your service doesn't need to write files (e.g., a read-only API that logs to stdout), you can skip creating a user. But best practice is to always use a non-root user.

```dockerfile
EXPOSE 8000
```

**EXPOSE**: Documents which port the application listens on. Doesn't actually publish the port (that's `docker run -p`), but it's metadata for `docker run -P` and orchestrators like k8s.

**Why 8000**: Common FastAPI/Django port. Services often use 80 internally and rely on the orchestrator to map 80 → 8000 in production.

```dockerfile
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD curl --fail http://localhost:8000/health || exit 1
```

**HEALTHCHECK**: Tells Docker how to test if the container is healthy. Docker periodically runs the CMD; if it fails `retries` times, the container is marked unhealthy.

**--interval=30s**: Check every 30 seconds.

**--timeout=10s**: Give the health check command 10 seconds to complete.

**--start-period=5s**: Give the container 5 seconds to start before health checks count toward retries (avoids false failures during slow startup).

**--retries=3**: Mark unhealthy after 3 consecutive failures.

**curl --fail http://localhost:8000/health**: Makes an HTTP request to `/health` endpoint; `--fail` exits non-zero on HTTP errors (4xx/5xx).

**When to skip**: HEALTHCHECK is optional. Kubernetes/ECS/Cloud Run have their own health check mechanisms (liveness/readiness probes). You can skip HEALTHCHECK in the Dockerfile and configure health checks in the orchestrator instead.

```dockerfile
ENTRYPOINT ["python", "entrypoint.py"]
```

**ENTRYPOINT vs CMD**: ENTRYPOINT sets the main command that always runs; CMD sets default arguments (can be overridden). For application containers, ENTRYPOINT is clearer (this container ALWAYS runs `python entrypoint.py`).

**entrypoint.py**: A Python script that reads the `MODE` env var (server, consumer, worker, cron) and dispatches to the appropriate main function. See the containerization-and-deployment skill for full entrypoint.py patterns.

**Why not CMD ["gunicorn", ...]**: Hardcoding gunicorn in CMD/ENTRYPOINT limits flexibility. entrypoint.py allows deploying the same image as a server, Kafka consumer, or background worker by changing only the MODE env var.

## Single-Stage Pattern: Simpler Services

For services that don't need multi-stage optimization (e.g., prototypes, internal tools, or services where image size isn't critical), a single-stage Dockerfile is simpler:

```dockerfile
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml .
RUN pip install --no-cache-dir ".[prod]"

COPY . .
ENV PYTHONPATH=/app

EXPOSE 8000
CMD ["gunicorn", "app.main:app", \
     "--worker-class", "uvicorn.workers.UvicornWorker", \
     "--workers", "4", \
     "--bind", "0.0.0.0:8000"]
```

**Trade-offs**:
- **Pros**: Simpler, fewer layers, faster builds (no stage copying).
- **Cons**: Larger final image (includes build tools), slightly less secure (build deps in production image).

Use single-stage for local dev images or rapid prototyping; use multi-stage for production deployments where image size and security matter.

## Alpine vs Slim: Detailed Comparison

### Python Slim (Debian-based)

**Base size**: ~150MB (python:3.11-slim)

**Pros**:
- Broader compatibility: Most wheels on PyPI are built for Debian/Ubuntu (manylinux).
- Easier to install system packages: apt-get has a huge package repository.
- Fewer build issues: psycopg2, cryptography, numpy, scipy all have pre-built wheels.

**Cons**:
- Larger base image.
- More attack surface (more installed packages).

**Use when**: You have complex dependencies (numpy, pandas, ML libraries) or you want fast builds without worrying about compilation issues.

### Python Alpine

**Base size**: ~50MB (python:3.10-alpine)

**Pros**:
- Minimal footprint: 1/3 the size of slim.
- Faster image pulls/pushes.
- Smaller attack surface (fewer installed packages).

**Cons**:
- Uses musl libc (not glibc): Some packages have compatibility issues.
- Fewer pre-built wheels: Many packages require compilation from source.
- More build dependencies required: gcc, g++, musl-dev, libffi-dev, etc.
- Longer build times: Installing packages that require compilation (cryptography, psycopg2) is slower.

**Use when**: Image size is critical (e.g., lambda functions, edge deployments) and you've verified all dependencies build correctly.

**Recommendation**: Start with slim; only switch to alpine if image size is a measurable problem and you've tested the build end-to-end.
