# Shared Base Images

Creating and consuming base images with heavy system dependencies across multiple services.

## Pattern Overview

**Problem**: Multiple backend services install the same heavy system dependencies (build tools, database clients, Kafka libraries, Kerberos tooling) in every Dockerfile, slowing down builds and creating inconsistent environments.

**Solution**: Create a `Dockerfile.base` that installs these dependencies once, publish it to a private registry with versioned tags, and have service Dockerfiles `FROM` that base image.

## Base Image Dockerfile

**Example** (genericized from production services):

```dockerfile
FROM python:3.11-slim

ARG PRIVATE_REGISTRY_TOKEN

ENV PYTHONUNBUFFERED=1

# Install heavy system dependencies
# - tzdata, curl, git: basic utilities
# - gcc, g++, build-essential, make, python3-dev: build tools for compiling Python extensions
# - libpq5, libpq-dev, postgresql-client: PostgreSQL client and libraries
# - librdkafka-dev: Kafka C library for confluent-kafka-python
# - krb5-user, libkrb5-dev: Kerberos authentication
# - openssh-client: SSH for git access over SSH
# - Various SSL/compression libs: libcurl4-openssl-dev, libssl-dev, zlib1g-dev, liblz4-dev, libzstd-dev
RUN apt-get update && \
    apt-get install -y tzdata curl git gcc g++ libc6-dev \
                       libpq5 libpq-dev openssh-client libffi-dev \
                       build-essential make python3-dev \
                       libcurl4-openssl-dev pkg-config libssl-dev \
                       zlib1g-dev liblz4-dev libzstd-dev librdkafka-dev \
                       vim postgresql-client krb5-user libkrb5-dev && \
    rm -rf /var/lib/apt/lists/*

# Set working directory (services will copy code here)
WORKDIR /srv/app

# Example: Install common Python dependencies
# (In production, this might include packages like psycopg2, confluent-kafka, etc.)
COPY requirements/base-requirements.txt /tmp/
RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r /tmp/base-requirements.txt && \
    rm /tmp/base-requirements.txt

# Create log directory with permissive permissions
RUN mkdir -p /var/log/app && chmod 777 /var/log/app
```

## Building and Publishing

```bash
# Build the base image
docker build -f Dockerfile.base \
  --build-arg PRIVATE_REGISTRY_TOKEN=<REDACTED> \
  -t registry.example.com/base-images/myservice-base:v1 .

# Push to registry
docker push registry.example.com/base-images/myservice-base:v1

# Tag with a version
docker tag registry.example.com/base-images/myservice-base:v1 \
           registry.example.com/base-images/myservice-base:latest
docker push registry.example.com/base-images/myservice-base:latest

# Get the digest for immutable pinning
docker inspect registry.example.com/base-images/myservice-base:v1 \
  --format='{{index .RepoDigests 0}}'
# Output: registry.example.com/base-images/myservice-base@sha256:abcdef123456...
```

## Service Dockerfile Using the Base

**Example** (genericized from production services):

```dockerfile
# Use tag (mutable, easier for development)
FROM registry.example.com/base-images/myservice-base:v12 AS builder

# Or use digest (immutable, recommended for production)
# FROM registry.example.com/base-images/myservice-base@sha256:3e9e23235cf89f858e953be0511321e7141f2042f45458dc984746e5975a5cc1 AS builder

# Copy application code (lightweight operation)
COPY . .

# Install application-specific dependencies (not in the base)
COPY requirements/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

EXPOSE 80

ENTRYPOINT ["python", "entrypoint.py"]
```

## Tag vs Digest Pinning

**Tag pinning** (`FROM registry.example.com/base-images/myservice-base:v12`):
- **Pros**: Easy to update (rebuild the base, push with same tag, rebuild services)
- **Cons**: Tags are mutable; `v12` today might differ from `v12` tomorrow if someone re-pushes

**Digest pinning** (`FROM registry.example.com/base-images/myservice-base@sha256:...`):
- **Pros**: Immutable; the exact layer set is guaranteed
- **Cons**: Harder to update (must change digest in all service Dockerfiles)

**Recommendation**: Use tags (`v1`, `v2`, `v12`) for active development; switch to digest pinning in production CI/CD for reproducibility.

## Versioning Strategy

**Semantic-ish versioning**: Increment the tag (`v1` → `v2` → `v12`) when system dependencies or base configuration change. Communicate the change to service owners.

**Build triggers**: When the base image changes, rebuild all dependent services in CI/CD to pick up the new version.

**Multi-service reuse**: A single base image can serve multiple related services (e.g., 3 Python backend services all use the same `myservice-base:v12` that includes PostgreSQL client, Kafka libs, and Kerberos).

## Why This Pattern Works

- **Build speed**: Installing heavy dependencies once (in the base) instead of in every service saves minutes per build
- **Consistency**: All services share the same system-level environment
- **Cache efficiency**: Docker layer caching means the base image layers are reused across all services
- **Separation of concerns**: Infrastructure team manages the base image; service teams manage application code

## Example from Production Services

In the real-world repositories, we observed:
- Two services (`serviceA` and `serviceB`) both using `FROM registry.example.com/base-images/project/serviceA-base:v12`
- The base image installing: Python 3.11, PostgreSQL client, Kafka librdkafka, Kerberos tools, SSH client, and build tools
- Service Dockerfiles reduced to ~15 lines (FROM base, COPY code, pip install app deps, ENTRYPOINT)
- Build times reduced from ~8 minutes to ~2 minutes after introducing the base image
