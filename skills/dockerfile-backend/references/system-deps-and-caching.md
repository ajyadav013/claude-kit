# System Dependencies and Layer Caching

Deep dive into system dependency patterns for Python backend stacks (PostgreSQL, Kafka, Kerberos) and layer caching strategies to optimize build times.

## System Dependencies by Stack

### PostgreSQL (psycopg2 / psycopg3)

**Why system deps are needed**: psycopg2 is a C extension that links to libpq (PostgreSQL client library). Without libpq, pip install fails with `Error: pg_config not found`.

**Debian/Ubuntu (slim)**:
- **Build-time**: `libpq-dev` (headers + pg_config)
- **Runtime**: `libpq5` (shared library)
- **Optional**: `postgresql-client` (provides `psql` command for debugging)

**Alpine**:
- **Build-time**: `postgresql-dev`
- **Runtime**: `libpq`

**Example builder stage (slim)**:
```dockerfile
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev && \
    rm -rf /var/lib/apt/lists/*
```

**Example runtime stage (slim)**:
```dockerfile
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        libpq5 \
        postgresql-client && \
    rm -rf /var/lib/apt/lists/*
```

**Alternative: psycopg2-binary**: You can `pip install psycopg2-binary` to avoid building from source (it includes a bundled libpq). However, the PostgreSQL project recommends building from source for production (psycopg2-binary may have compatibility issues or missing features).

### Kafka (confluent-kafka-python)

**Why system deps are needed**: confluent-kafka-python wraps librdkafka (a high-performance C library for Kafka). Without librdkafka, pip install fails with `fatal error: librdkafka/rdkafka.h: No such file or directory`.

**Debian/Ubuntu (slim)**:
- **Build-time**: `librdkafka-dev` (headers)
- **Runtime**: `librdkafka-dev` (shared library + headers; package name is the same for runtime)

**Additional deps for compression**:
- `libssl-dev` (SSL/TLS for encrypted Kafka connections)
- `zlib1g-dev` (gzip compression)
- `liblz4-dev` (lz4 compression)
- `libzstd-dev` (zstd compression)

**Alpine**:
- **Build-time**: `librdkafka-dev`
- **Runtime**: `librdkafka-dev`

**Example builder stage (slim)**:
```dockerfile
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        build-essential \
        librdkafka-dev \
        libssl-dev \
        zlib1g-dev \
        liblz4-dev \
        libzstd-dev && \
    rm -rf /var/lib/apt/lists/*
```

**Example runtime stage (slim)**:
```dockerfile
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        librdkafka-dev && \
    rm -rf /var/lib/apt/lists/*
```

**Note**: Unlike libpq, librdkafka doesn't have separate -dev and runtime packages in Debian/Ubuntu. You install `librdkafka-dev` in both builder and runtime stages.

**Alternative: kafka-python**: If you use `kafka-python` (pure Python Kafka client), you don't need librdkafka. However, confluent-kafka-python is much faster (10x throughput in some benchmarks) due to the C implementation.

### Kerberos (for Kafka SASL_GSSAPI or HTTP Kerberos auth)

**Why system deps are needed**: Kerberos authentication requires the krb5 library. Python packages like `gssapi` (used for Kafka SASL_GSSAPI) wrap krb5 C bindings.

**Debian/Ubuntu (slim)**:
- **Build-time**: `libkrb5-dev` (headers for building gssapi)
- **Runtime**: `krb5-user` (kinit, klist commands + krb5 runtime libs)

**Alpine**:
- **Build-time**: `krb5-dev`
- **Runtime**: `krb5-libs krb5` (runtime libs + tools)

**Example builder stage (slim)**:
```dockerfile
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        build-essential \
        libkrb5-dev && \
    rm -rf /var/lib/apt/lists/*
```

**Example runtime stage (slim)**:
```dockerfile
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        krb5-user && \
    rm -rf /var/lib/apt/lists/*
```

**Keytab and krb5.conf**: At runtime, you need:
1. **Keytab file**: Binary file containing Kerberos credentials. Store as base64-encoded env var, decode at runtime, write to `/tmp/service.keytab` with `chmod 600`.
2. **krb5.conf**: Kerberos configuration (KDC addresses, realm names). Store as a file in your repo (e.g., `config/krb5.conf`), copy to `/etc/krb5.conf` in Dockerfile or entrypoint.
3. **kinit**: Run `kinit -kt /tmp/service.keytab principal@REALM` in entrypoint before starting Kafka consumer.

**Example entrypoint snippet**:
```python
import os
import base64
import subprocess
from pathlib import Path

# Write keytab from env var
keytab_b64 = os.environ.get("KAFKA_KEYTAB_BASE64")
if keytab_b64:
    keytab_path = Path("/tmp/service.keytab")
    keytab_path.write_bytes(base64.b64decode(keytab_b64))
    os.chmod(keytab_path, 0o600)
    
    # Run kinit to authenticate
    principal = os.environ.get("KAFKA_PRINCIPAL")  # e.g., "service/hostname@REALM"
    subprocess.run(["kinit", "-kt", str(keytab_path), principal], check=True)
```

### Other Common Dependencies

**Cryptography / SSL**:
- Slim: `libffi-dev libssl-dev` (build), `libffi libssl` (runtime)
- Alpine: `libffi-dev openssl-dev` (build), `libffi openssl` (runtime)

**NumPy / SciPy / Pandas**:
- Slim: `build-essential gfortran libopenblas-dev` (build)
- Alpine: Often problematic; consider using slim or pre-built wheels

**Pillow (image processing)**:
- Slim: `libjpeg-dev zlib1g-dev` (build)
- Alpine: `jpeg-dev zlib-dev` (build)

## Layer Caching Strategies

Docker caches layers by command; if a command hasn't changed and the previous layers haven't changed, Docker reuses the cached layer. This dramatically speeds up rebuilds.

### Strategy 1: Copy Dependency Manifest First

**Bad (no caching)**:
```dockerfile
COPY . .
RUN pip install --no-cache-dir -r requirements.txt
```

**Why bad**: Any code change (even a comment in a Python file) invalidates the COPY layer, which invalidates the RUN layer, forcing a full reinstall of all dependencies.

**Good (caching)**:
```dockerfile
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
```

**Why good**: Only changes to requirements.txt invalidate the pip install layer. Code changes don't trigger dependency reinstalls.

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

**Impact**: On a service with ~50 dependencies, this reduces rebuild time from ~5 minutes to ~30 seconds when only code changes.

### Strategy 2: Separate Slow Installs

If you have one slow dependency (e.g., tensorflow, torch, scikit-learn), install it separately to cache it independently:

```dockerfile
COPY requirements-base.txt .
RUN pip install --no-cache-dir -r requirements-base.txt

COPY requirements-ml.txt .
RUN pip install --no-cache-dir -r requirements-ml.txt

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
```

**Why**: If requirements.txt changes but requirements-ml.txt doesn't, Docker skips reinstalling tensorflow/torch. This is overkill for most projects but useful for ML services.

### Strategy 3: System Deps + Cleanup in One RUN

**Bad (bloated layer)**:
```dockerfile
RUN apt-get update
RUN apt-get install -y build-essential
RUN pip install -r requirements.txt
RUN apt-get clean
RUN rm -rf /var/lib/apt/lists/*
```

**Why bad**: Each RUN creates a layer. Even though the last two RUNs delete files, the earlier layers still contain them (Docker layers are additive). The apt cache persists in the image.

**Good (single layer)**:
```dockerfile
RUN apt-get update && \
    apt-get install -y --no-install-recommends build-essential && \
    rm -rf /var/lib/apt/lists/* && \
    pip install --no-cache-dir -r requirements.txt
```

**Why good**: All commands run in a single layer. The apt cache is deleted before the layer is committed, so it never persists in the image.

**Trade-off**: If pip install fails, you have to rerun apt-get update every time. For reliability, prefer:
```dockerfile
RUN apt-get update && \
    apt-get install -y --no-install-recommends build-essential && \
    rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir -r requirements.txt
```

This separates system deps (rarely change) from Python deps (change frequently), improving cache hit rate.

### Strategy 4: Use BuildKit Caching (Advanced)

Docker BuildKit supports `--mount=type=cache` to cache directories across builds (e.g., pip cache, apt cache). This is more advanced but very powerful.

**Example (cache pip downloads)**:
```dockerfile
# syntax=docker/dockerfile:1.4
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-cache-dir -r requirements.txt
```

**Why**: Even with `--no-cache-dir`, pip still downloads packages. `--mount=type=cache` caches the download directory across builds, so pip doesn't re-download unchanged packages.

**Enable BuildKit**: `export DOCKER_BUILDKIT=1` or `docker buildx build`.

**Trade-off**: More complex syntax, requires BuildKit. Only use if build times are critical (e.g., >5 min builds).

### Strategy 5: Multi-Stage Caching with Inline Cache

For CI/CD pipelines, Docker doesn't share layers across builds by default. Use `--cache-from` to pull a previous image and reuse its layers:

```bash
# Pull the latest image to use as cache
docker pull myregistry.example.com/app:latest || true

# Build with cache-from
docker build \
  --cache-from myregistry.example.com/app:latest \
  -t myregistry.example.com/app:$COMMIT_SHA \
  .
```

**In multi-stage builds**, also pull and cache the builder stage:
```bash
docker pull myregistry.example.com/app:latest-builder || true
docker pull myregistry.example.com/app:latest || true

docker build \
  --target builder \
  --cache-from myregistry.example.com/app:latest-builder \
  -t myregistry.example.com/app:$COMMIT_SHA-builder \
  .

docker build \
  --cache-from myregistry.example.com/app:latest-builder \
  --cache-from myregistry.example.com/app:latest \
  -t myregistry.example.com/app:$COMMIT_SHA \
  .
```

**Impact**: Reduces CI build times from ~10 minutes to ~2 minutes by reusing layers from the previous build.

## Common Dependency Pitfall: Order Matters

**Problem**: You install dependencies, then realize you need a system package, so you add it:

```dockerfile
RUN pip install --no-cache-dir -r requirements.txt
# Later, you realize psycopg2 needs libpq-dev
RUN apt-get update && apt-get install -y libpq-dev
```

**Result**: psycopg2 installation already failed; the second RUN doesn't help (pip install is cached from before libpq-dev was added).

**Fix**: Force rebuild from that point:
```dockerfile
RUN apt-get update && apt-get install -y libpq-dev
RUN pip install --no-cache-dir -r requirements.txt
```

Then rebuild with `--no-cache` or change requirements.txt to invalidate the cache:
```bash
docker build --no-cache .
```

**Prevention**: Install all system deps BEFORE pip install in the Dockerfile, even if you don't need them yet. Anticipate common needs (libpq, librdkafka, etc.).

## Summary Checklist

- [ ] Install system dependencies in builder stage BEFORE `pip install`
- [ ] Copy `requirements.txt` or `pyproject.toml` BEFORE `COPY . .`
- [ ] Use `--no-install-recommends` with apt-get
- [ ] Clean up apt cache with `rm -rf /var/lib/apt/lists/*` in the same RUN
- [ ] Use `--no-cache-dir` with pip
- [ ] Separate builder (build deps) and runtime (runtime-only deps) stages
- [ ] Use `COPY --from=builder` to transfer only venv + code to runtime
- [ ] Test the build with `docker build --no-cache` occasionally to catch caching issues
- [ ] If build times are critical, enable BuildKit and use `--mount=type=cache`
