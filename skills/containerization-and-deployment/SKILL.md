---
name: containerization-and-deployment
description: Docker containerization patterns from production Python/FastAPI microservices — multi-stage builds, entrypoint.py MODE dispatch (server/consumer/worker/cron), cert/keytab writing from env vars + kinit, docker-compose for local dev (postgres/redis/kafka), health checks, and secrets hygiene. Use when containerizing Python services, implementing multi-role deployments from one image, setting up local dev infrastructure, handling Kerberos auth in containers, or deploying to Cloud Run/k8s with env-based secrets.
---

# Containerization and Deployment

Docker containerization, multi-role dispatch, secrets handling, and local dev infrastructure patterns from production services.

## When to use

- Containerizing FastAPI/Python backend services
- Implementing one-image-many-roles pattern (server/consumer/worker/cron from same Dockerfile)
- Writing certs/keytabs from environment variables for Kafka SASL_SSL/Kerberos
- Setting up local dev with docker-compose (postgres/redis/kafka/temporal)
- Deploying to Cloud Run, GKE, or other container platforms
- Handling secrets and credentials in containerized environments
- Configuring health checks and readiness probes

## Core conventions

### Multi-Stage Dockerfile Pattern

**Builder + runtime separation**: Use a builder stage to install build dependencies and compile wheels; copy only the virtual environment and application code to a minimal runtime stage.

**Alpine for minimal footprint**: Use `python:3.10-alpine` or `python:3.11-slim` base images; install only runtime dependencies in the final stage. Alpine offers minimal footprint; slim provides broader compatibility.

**Dependency caching**: Copy `requirements.txt` before application code; leverage Docker layer caching to avoid reinstalling dependencies on every code change.

**Security hardening**: Remove `.git` directory after capturing commit SHA; use `--no-cache-dir` with pip; set `PYTHONUNBUFFERED=1` for immediate log output.

### Entrypoint MODE Dispatch

**Single entrypoint, multiple roles**: `entrypoint.py` reads `MODE` env var and dispatches to server, consumer, worker, cron, or temporal_worker.

**Mode-specific worker/cron config**: For `MODE=worker`, read `WORKER_MODE` env var to determine which worker pool; for `MODE=cron`, read `CRON_JOB` to select cron function.

**Why**: Deploy the same Docker image to multiple services (API server, Kafka consumer, background worker, cron job) with only env var changes; simplifies CI/CD (one build, many deploys).

**Standard modes**: `server` → FastAPI/uvicorn, `consumer` → Kafka consumer, `worker` or `temporal_worker` → background task worker, `cron` → scheduled job, `webhook_server` → webhook endpoint variant.

### Cert/Keytab Writing from Env Vars (Kerberos Pattern)

**PEM cert restoration**: Store PEM files as space-separated env vars; restore newlines around `-----BEGIN/END-----` markers and write to `/tmp/` directory with `0o600` permissions.

**Keytab from base64**: Store keytab as base64-encoded env var; decode and write to `/tmp/` with `0o600` permissions.

**Entrypoint cert bootstrap**: Call `_write_kafka_certificates()` in entrypoint before starting consumer; write certs/keytabs, copy `krb5.conf` from repo, then update env vars to point at generated files.

**Why**: Cloud platforms (Cloud Run, k8s) expose secrets as env vars, not mounted volumes; this pattern converts env secrets to filesystem files for libraries that require file paths (Kafka SASL_SSL, Kerberos).

### Docker Compose for Local Dev

**Service dependencies with health checks**: Use `depends_on` with `condition: service_healthy`; define `healthcheck` for postgres (`pg_isready`), redis (`redis-cli ping`), kafka (`kafka-topics.sh --list`).

**One image, many containers**: Build the application image once; spin up separate containers for server, consumer, workers, cron jobs by varying `MODE` and `WORKER_MODE`/`CRON_JOB` env vars.

**Volume mounts for hot reload**: Mount `..:/srv/{service_name}` to enable code changes without rebuilding; mount `$HOME/.config/gcloud` for local GCP auth.

**Debug ports**: Expose unique debugpy ports for each container (5679, 5680, 5681...) to attach VSCode/PyCharm debuggers.

**Shared env with anchors**: Use YAML `x-environment: &common-environment-variables` anchor to define shared env once and reference with `<<: *common-environment-variables`.

**External network for cross-service communication**: Connect to an external network for local services (Kafka, Redis) shared across multiple repos.

### Cloud Run / k8s Deployment

**MODE env var in deployment**: Set `MODE=server` for API service, `MODE=consumer` for Kafka consumers, `MODE=temporal_worker` for workers.

**Secrets as env vars**: Pass database credentials, API keys, JWT secrets as `--set-env-vars` in Cloud Run or as `env` in k8s deployment YAML.

**CloudSQL socket connection**: Use `--add-cloudsql-instances` and set `POSTGRES_HOST=/cloudsql/{INSTANCE_CONNECTION}` for Cloud Run managed Postgres access.

**VPC connector for private resources**: Use `--vpc-connector` to access private Redis/Kafka instances from Cloud Run.

**Memory/CPU/autoscaling**: Set `--memory 2Gi`, `--cpu 2`, `--min-instances 0`, `--max-instances 3` for autoscaling; adjust per service needs.

### Secrets and Env Hygiene

**Never commit secrets**: All credentials live in env vars or secret managers; never hardcode in code or Dockerfiles.

**Base64-encode binary secrets**: For keytabs, SSL certs, encode as base64 in env vars; decode at runtime.

**Escape `\n` in PEM strings**: Store multi-line PEM certs with `\n` literal in env vars; replace with actual newlines at runtime.

**Use `.env` for local dev**: Docker Compose reads `.env` file; never commit it (`.gitignore`).

### API Versioning for Deployment Compatibility

**Path-based versioning**: Prefix all API routes with `/v1/`, `/v2/`; allows rolling deployments with backward compatibility (old clients hit `/v1/`, new clients hit `/v2/`). _(cross-referenced from backend-repo-architecture)_

## Skeleton / example

```dockerfile
# Multi-stage Dockerfile (alpine pattern)
ARG PYTHON_VERSION=3.10.15-alpine3.20

FROM python:${PYTHON_VERSION} AS builder

ENV PYTHONUNBUFFERED=1

RUN apk update && apk upgrade && \
    apk add --no-cache curl git librdkafka-dev g++ && \
    rm -rf /var/cache/apk/*

WORKDIR /srv/service_name

COPY ./requirements/requirements.txt .

# Create virtual environment in builder
RUN python -m venv /opt/venv
ENV VIRTUAL_ENV=/opt/venv
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

RUN pip install --upgrade --no-cache-dir pip wheel && \
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

WORKDIR /srv/service_name
COPY --from=builder /srv/service_name .
COPY --from=builder /opt/venv /opt/venv

ENV VIRTUAL_ENV=/opt/venv
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

EXPOSE 80

RUN mkdir -p /var/log/app && chmod 777 /var/log/app

ENTRYPOINT ["python", "entrypoint.py"]
```

```python
# entrypoint.py MODE dispatch
import os
import asyncio
from config.docker_config import loaded_config

MODE = os.environ.get("MODE")

def start_server():
    from app.main import main as server_main
    server_main()

def start_consumer():
    from services.kafka.consumer.consumer import main as consumer_main
    asyncio.run(consumer_main())

def start_worker():
    from workers.run import main as worker_main
    worker_mode = loaded_config.WORKER_MODE
    print(f"Starting {worker_mode} Worker")
    asyncio.run(worker_main(worker_mode))

def start_cron():
    from crons.run import main as cron_main
    cron_job = loaded_config.CRON_JOB
    print(f"Starting {cron_job} Cron Job")
    asyncio.run(cron_main(cron_job))

def start_temporal_worker():
    from temporal.run import worker_main
    worker_mode = loaded_config.WORKER_MODE
    temporal_queue = loaded_config.TEMPORAL_QUEUE
    asyncio.run(worker_main(worker_mode, temporal_queue))

mode_actions = {
    "server": start_server,
    "consumer": start_consumer,
    "worker": start_worker,
    "cron": start_cron,
    "temporal_worker": start_temporal_worker,
}

if __name__ == "__main__":
    action = mode_actions.get(MODE)
    if action:
        action()
    else:
        print(f"MODE {MODE} not available")
```

```python
# Cert/keytab writing pattern
import base64
import os
import re
from pathlib import Path

CERT_DIR = Path("/tmp/kafka_certificates")

def _restore_pem(env_value: str) -> str:
    """Restore PEM file content from space-separated env var."""
    result = re.sub(r'(-----(?:BEGIN|END) [A-Z ]+-----)', r'\n\1\n', env_value)
    lines = result.strip().split('\n')
    rebuilt = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if line.startswith('-----'):
            rebuilt.append(line)
        else:
            rebuilt.extend(line.split())
    return '\n'.join(rebuilt) + '\n'

def _write_kafka_certificates() -> None:
    """Write Kafka certificate files from env-var secrets."""
    CERT_DIR.mkdir(parents=True, exist_ok=True)

    # PEM files from env vars
    pem_files = {
        "server.pem": os.environ.get("KAFKA_SERVER_PEM"),
        "ca-certificate.pem": os.environ.get("KAFKA_CA_CERT_PEM"),
        "ca-certificate.key": os.environ.get("KAFKA_CA_KEY"),
    }
    for filename, content in pem_files.items():
        if content:
            path = CERT_DIR / filename
            path.write_text(_restore_pem(content))
            os.chmod(path, 0o600)
            print(f"[entrypoint] Wrote {path}", flush=True)

    # Keytab from base64
    keytab_b64 = os.environ.get("KAFKA_KEYTAB_BASE64")
    if keytab_b64:
        keytab_path = CERT_DIR / "service.keytab"
        keytab_path.write_bytes(base64.b64decode(keytab_b64))
        os.chmod(keytab_path, 0o600)
        print(f"[entrypoint] Wrote {keytab_path}", flush=True)

    # Update env vars to point at generated files
    os.environ["KAFKA_SSL_CA_FILE"] = str(CERT_DIR / "server.pem")
    os.environ["KAFKA_SSL_CERT_FILE"] = str(CERT_DIR / "ca-certificate.pem")
    os.environ["KAFKA_SSL_KEY_FILE"] = str(CERT_DIR / "ca-certificate.key")
    os.environ["KAFKA_KEYTAB_PATH"] = str(CERT_DIR / "service.keytab")
```

```yaml
# docker-compose.yml
version: '3.9'

x-environment: &common-env
  ENV: DEV
  POSTGRES_URL: postgresql://user:pass@app-db:5432/dbname
  REDIS_URL: redis://app-redis:6379/0
  KAFKA_BROKERS: app-kafka:9092

services:
  server:
    build:
      context: .
      dockerfile: Dockerfile
    image: app:latest
    ports:
      - '8000:80'
      - '5678:5678'  # debugpy
    environment:
      <<: *common-env
      MODE: server
      DEBUG_PORT: 5678
    volumes:
      - .:/srv/app
      - $HOME/.config/gcloud:/root/.config/gcloud
    depends_on:
      db:
        condition: service_healthy
      redis:
        condition: service_healthy
    networks:
      - app-net

  consumer:
    image: app:latest
    environment:
      <<: *common-env
      MODE: consumer
    volumes:
      - .:/srv/app
    depends_on:
      kafka:
        condition: service_healthy
    networks:
      - app-net

  worker:
    image: app:latest
    environment:
      <<: *common-env
      MODE: worker
      WORKER_MODE: background_tasks
    volumes:
      - .:/srv/app
    networks:
      - app-net

  db:
    image: postgres:13.8-bullseye
    environment:
      POSTGRES_PASSWORD: "password"
      POSTGRES_USER: "user"
      POSTGRES_DB: "dbname"
    volumes:
      - db-data:/var/lib/postgresql/data
    healthcheck:
      test: pg_isready -U user
      interval: 2s
      timeout: 3s
      retries: 40

  redis:
    image: bitnami/redis:6.2.5
    environment:
      ALLOW_EMPTY_PASSWORD: "yes"
    healthcheck:
      test: redis-cli ping
      interval: 1s
      timeout: 3s
      retries: 50

  kafka:
    image: bitnami/kafka:3.2.0
    environment:
      KAFKA_BROKER_ID: "1"
      ALLOW_PLAINTEXT_LISTENER: "yes"
      KAFKA_CFG_LISTENERS: "PLAINTEXT://0.0.0.0:9092"
      KAFKA_CFG_ADVERTISED_LISTENERS: "PLAINTEXT://app-kafka:9092"
    healthcheck:
      test: kafka-topics.sh --list --bootstrap-server localhost:9092
      interval: 1s
      timeout: 3s
      retries: 30

networks:
  app-net:

volumes:
  db-data:
```

```yaml
# Cloud Run deployment (GitHub Actions)
- name: Deploy server to Cloud Run
  run: |
    gcloud run deploy app-backend-dev \
      --image gcr.io/${{ vars.GCP_PROJECT_ID }}/app-backend:${{ github.sha }} \
      --platform managed \
      --region ${{ vars.GCP_REGION }} \
      --allow-unauthenticated \
      --port 80 \
      --memory 2Gi \
      --cpu 2 \
      --min-instances 0 \
      --max-instances 3 \
      --timeout 600 \
      --add-cloudsql-instances ${{ vars.CLOUDSQL_INSTANCE_CONNECTION }} \
      --vpc-connector ${{ vars.VPC_CONNECTOR }} \
      --service-account ${{ vars.GCP_SA_NAME }} \
      --set-env-vars="MODE=server,\
        POSTGRES_HOST=/cloudsql/${{ vars.CLOUDSQL_INSTANCE_CONNECTION }},\
        POSTGRES_USER=${{ secrets.POSTGRES_USER }},\
        POSTGRES_PASSWORD=${{ secrets.POSTGRES_PASSWORD }},\
        REDIS_URL=${{ secrets.REDIS_URL }},\
        JWT_SECRET_KEY=${{ secrets.JWT_SECRET_KEY }}"
```

## Anti-patterns to avoid

- **Installing build tools in the runtime stage** — use multi-stage builds; only runtime deps in the final stage.
- **Hardcoding MODE in Dockerfile** — use `ENV MODE` or `--set-env-vars` at deploy time; one image, many roles.
- **Committing secrets to `.env` or code** — always use secret managers or encrypted GitHub secrets; never commit `.env`.
- **Missing health checks in docker-compose** — services start before dependencies are ready; use `healthcheck` + `depends_on: condition: service_healthy`.
- **Writing certs to the repo directory** — write to `/tmp/` with `0o600`; never commit generated certs or keytabs.
- **Using `COPY . .` before `COPY requirements.txt`** — breaks Docker layer caching; copy deps first, then code.
- **Exposing the same debugpy port for all containers** — each container needs a unique debug port (5678, 5679, 5680...).
- **Forgetting `PYTHONUNBUFFERED=1`** — logs buffer in Docker; set this env var for immediate output.
- **Using production secrets in docker-compose** — use dummy credentials for local dev; never mount prod secrets locally.

## References

- [repo-evidence.md](./references/repo-evidence.md) — Real file paths and snippets from source repos
- [dockerfile-and-compose.md](./references/dockerfile-and-compose.md) — Multi-stage builds, docker-compose patterns, health checks
- [entrypoint-and-modes.md](./references/entrypoint-and-modes.md) — MODE dispatch, worker/cron config, one-image-many-roles
- [deployment-and-secrets.md](./references/deployment-and-secrets.md) — Cloud Run/k8s deployment, cert/keytab writing, secrets hygiene
