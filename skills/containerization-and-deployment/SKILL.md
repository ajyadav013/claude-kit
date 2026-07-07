---
name: containerization-and-deployment
description: End-to-end containerization overview for Python/FastAPI services — entrypoint MODE dispatch (server/consumer/worker/cron), cert/keytab bootstrap from env vars, Cloud Run/k8s deploy, Makefile dev workflow. Start here for the whole picture; for focused work use dockerfile-backend or dockerfile-frontend (image builds), docker-compose (local dev), or docker-shared (base images).
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

### Makefile developer workflow

**Composite docker-compose commands**: Use `make up` and `make down` to wrap multi-file docker-compose invocations (base + override configs); reduces typos and standardizes local dev startup across team members.

**Shell access shortcuts**: `make enter` and `make enter-worker` exec into server/worker containers with `/bin/bash`; no need to remember container names or lookup `docker ps` output.

**Log tailing targets**: `make logs-server` and `make logs-worker` follow logs for specific containers; filter multi-container compose output to the service you're debugging.

**Build and deploy targets**: `make build` wraps `docker build`, `make run` wraps `docker-compose up`, `make k8s-deploy` wraps `kubectl apply -f k8s/`; CI/CD scripts can reference these stable targets even if underlying commands evolve.

**Why**: A Makefile consolidates project-specific docker-compose file paths, container names, and kubectl deployment configs into discoverable, self-documenting targets. New team members run `make help` or inspect the Makefile to learn the workflow; no need to hunt through README or CI YAML for the "right" docker-compose invocation.

**Example pattern**:

```makefile
.PHONY: help up down restart enter enter-worker logs-server logs-worker build k8s-deploy

help:
	@echo "Available commands:"
	@echo "  make up            - Start all services"
	@echo "  make down          - Stop all services"
	@echo "  make enter         - Shell into server container"
	@echo "  make enter-worker  - Shell into worker container"
	@echo "  make logs-server   - Follow server logs"
	@echo "  make logs-worker   - Follow worker logs"
	@echo "  make k8s-deploy    - Deploy to k8s"

up:
	docker-compose -f docker-compose.base.yml -f docker-compose.override.yml up --build -d
	docker-compose -f docker-compose.base.yml -f docker-compose.override.yml logs -f server

down:
	docker-compose -f docker-compose.base.yml -f docker-compose.override.yml down

restart: down up

enter:
	docker-compose -f docker-compose.base.yml -f docker-compose.override.yml exec server /bin/bash

enter-worker:
	docker-compose -f docker-compose.base.yml -f docker-compose.override.yml exec worker /bin/bash

logs-server:
	docker-compose -f docker-compose.base.yml -f docker-compose.override.yml logs -f server

logs-worker:
	docker-compose -f docker-compose.base.yml -f docker-compose.override.yml logs -f worker

build:
	docker build -t app:latest .

k8s-deploy:
	kubectl apply -f k8s/
```

### Kerberos runtime bootstrap (kinit)

**krb5.conf patching**: At container startup, read the repo-bundled `krb5.conf`, strip `includedir` directives (unavailable in minimal container images), and rewrite the credential cache type from `KEYRING:persistent:%{uid}` to `FILE:/tmp/krb5cc_%{uid}` (KEYRING not supported in many container runtimes).

**kinit with keytab**: After writing the patched `krb5.conf`, run `kinit -kt /path/to/service.keytab service-principal@EXAMPLE.COM` to authenticate the service principal; this populates the credential cache for GSSAPI-based Kafka SASL_SSL connections.

**Env var pointing**: Set `KRB5_CONFIG=/tmp/krb5_patched.conf` before running `kinit`; ensures the Kerberos library uses the container-friendly config instead of system-wide `/etc/krb5.conf`.

**Why**: Kerberos libraries expect `krb5.conf` with system-specific paths and KEYRING credential caches; containers (especially alpine-based or Cloud Run) lack those dependencies. This bootstrap pattern rewrites the config for container compatibility, authenticates via keytab (no interactive password prompt), and establishes a credential cache that Kafka clients (confluent-kafka-python, kafka-python with GSSAPI) can use.

**Where to call**: In `entrypoint.py`, before starting the Kafka consumer or any service that connects to Kerberos-authenticated Kafka; alternatively, in a dedicated `bootstrap.sh` script sourced by the Dockerfile `ENTRYPOINT`.

**Example pattern**:

```python
import os
import subprocess
from pathlib import Path

CERT_DIR = Path("/tmp/kafka_certificates")
KEYTAB_PATH = CERT_DIR / "service.keytab"
KRB5_CONF_SRC = Path(__file__).resolve().parent / "config" / "krb5.conf"
KRB5_CONF_PATCHED = Path("/tmp/krb5_patched.conf")
KERBEROS_PRINCIPAL = "service-principal@EXAMPLE.COM"

def setup_kerberos():
    """Patch krb5.conf and authenticate via kinit."""
    # Read repo-bundled krb5.conf
    with KRB5_CONF_SRC.open("r") as f:
        content = f.read()

    # Strip includedir, replace KEYRING with FILE credential cache
    lines = []
    for line in content.splitlines():
        if line.strip().startswith("includedir"):
            continue
        line = line.replace("KEYRING:persistent:%{uid}", "FILE:/tmp/krb5cc_%{uid}")
        lines.append(line)

    # Write patched config
    KRB5_CONF_PATCHED.write_text("\n".join(lines) + "\n")
    os.environ["KRB5_CONFIG"] = str(KRB5_CONF_PATCHED)
    print(f"[setup_kerberos] KRB5_CONFIG={KRB5_CONF_PATCHED}", flush=True)

    # Authenticate with keytab (use list args to avoid shell injection)
    result = subprocess.run(
        ["kinit", "-kt", str(KEYTAB_PATH), KERBEROS_PRINCIPAL],
        capture_output=True,
        text=True
    )
    if result.returncode == 0:
        print("[setup_kerberos] kinit succeeded.", flush=True)
    else:
        print(f"[setup_kerberos] kinit failed: {result.stderr.strip()}", flush=True)

# In entrypoint.py, before starting Kafka consumer:
def start_consumer():
    setup_kerberos()  # Authenticate before connecting to Kafka
    from services.kafka.consumer import main as consumer_main
    consumer_main()
```

**Generic krb5.conf snippet** (what gets patched):

```ini
[libdefaults]
    default_realm = EXAMPLE.COM
    default_ccache_name = FILE:/tmp/krb5cc_%{uid}

[realms]
    EXAMPLE.COM = {
        kdc = kdc.example.com:88
        admin_server = kdc.example.com:749
    }

[domain_realm]
    .example.com = EXAMPLE.COM
    example.com = EXAMPLE.COM
```

## Skeleton / example

Every worked skeleton for this skill already lives, in full, in the references — each one is the
complete file to copy and adapt:

- **Multi-stage Dockerfile** (alpine builder + runtime, venv copy, git-SHA capture) →
  [dockerfile-and-compose.md](./references/dockerfile-and-compose.md)
- **`entrypoint.py` MODE dispatch** (server/consumer/worker/cron/temporal_worker via the
  `mode_actions` map) → [entrypoint-and-modes.md](./references/entrypoint-and-modes.md)
- **Cert/keytab writing from env vars** (`_restore_pem`, `_write_kafka_certificates`, `0o600` to
  `/tmp/`) → [deployment-and-secrets.md](./references/deployment-and-secrets.md)
- **docker-compose with health checks + YAML-anchored shared env** →
  [dockerfile-and-compose.md](./references/dockerfile-and-compose.md)
- **Cloud Run deployment via GitHub Actions** (`gcloud run deploy` with CloudSQL socket, VPC
  connector, env-var secrets) → [deployment-and-secrets.md](./references/deployment-and-secrets.md)

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
- [makefile-dev-workflow.md](./references/makefile-dev-workflow.md) — Makefile targets wrapping docker-compose, shell access, log tailing, k8s deploy
- [kerberos-kinit-bootstrap.md](./references/kerberos-kinit-bootstrap.md) — Kerberos kinit runtime bootstrap, krb5.conf patching for containers, GSSAPI Kafka auth
