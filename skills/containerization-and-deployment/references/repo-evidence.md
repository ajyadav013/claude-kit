# Example Patterns

Production containerization patterns extracted from real-world Python/FastAPI services.

## Multi-Stage Dockerfiles

### Alpine Multi-Stage Pattern

**Example from a production service**:

```dockerfile
ARG PYTHON_VERSION=3.10.15-alpine3.20

FROM python:${PYTHON_VERSION} AS builder
# ... build dependencies (g++, git, openssh)
RUN python -m venv /opt/venv
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN git rev-parse HEAD > gitsha && rm -rf .git

FROM python:${PYTHON_VERSION}
# ... runtime dependencies only (librdkafka-dev)
COPY --from=builder /srv/app .
COPY --from=builder /opt/venv /opt/venv
ENTRYPOINT ["python", "entrypoint.py"]
```

**Pattern**: Two-stage build with builder and runtime; virtual environment copied from builder; git SHA captured then .git removed.

### Slim Single-Stage Pattern

**Example from a production service**:

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

CMD ["gunicorn", "app.application:get_app()", \
     "--worker-class", "uvicorn.workers.UvicornWorker", \
     "--workers", "4", \
     "--bind", "0.0.0.0:8000"]
```

**Pattern**: Single-stage Dockerfile with gunicorn + uvicorn workers; installs from `pyproject.toml`.

### Custom Base Image Pattern

**Example from a production service**:

```dockerfile
FROM registry.example.com/base-images/app:v12 AS builder
COPY . .
EXPOSE 80
ENTRYPOINT ["python", "entrypoint.py"]
```

**Pattern**: Minimal Dockerfile using custom base image that pre-bundles dependencies.

## Entrypoint MODE Dispatch

### Complete Multi-Mode Pattern

**Example from a production service**:

```python
MODE = os.environ.get("MODE")

if MODE == "server":
    from src.main import main as server_main
    server_main()

elif MODE == "consumer":
    from src.services.kafka.consumer.consumer import main as consumer_main
    asyncio.run(execute_mode(consumer_main))

elif MODE == "worker":
    worker_mode = loaded_config.WORKER_MODE
    asyncio.run(execute_mode(worker_main))

elif MODE == "cron":
    cron_job = loaded_config.CRON_JOB
    asyncio.run(execute_mode(cron_main))

elif MODE == "temporal_worker":
    worker_mode = loaded_config.WORKER_MODE
    temporal_queue = loaded_config.TEMPORAL_QUEUE
    asyncio.run(execute_mode(worker_main, worker_mode, temporal_queue))
```

**Pattern**: Five modes (server, consumer, worker, cron, temporal_worker); worker and cron use secondary env vars (`WORKER_MODE`, `CRON_JOB`).

### Extended Mode Pattern

**Example from a production service**:

```python
mode_actions = {
    "server": start_server,
    "webhook_server": start_server,
    "test": start_server,
    "consumer": start_consumer,
    "temporal_worker": start_temporal_worker,
    "orchestrator_worker": start_orchestrator_worker,
    "signal_forwarder": start_signal_forwarder,
    "cron": start_cron,
}

if __name__ == "__main__":
    action = mode_actions.get(loaded_config.MODE)
    if action:
        action()
```

**Pattern**: Eight modes including mode aliases (`server` / `webhook_server` / `test` all start server); orchestrator_worker for workflow execution; signal_forwarder for signal consumer.

### Minimal Two-Mode Pattern

**Example from a production service**:

```python
if loaded_config.MODE == "server":
    from app.main import main as server_main
    server_main()

elif loaded_config.MODE == "consumer":
    from services.kafka.consumer.consumer import main as consumer_main
    asyncio.run(consumer_main())

else:
    print("MODE not available")
```

**Pattern**: Two modes (server, consumer); minimal pattern for simpler services.

## Cert/Keytab Writing from Env Vars

### Kafka SASL_SSL + Kerberos Pattern

**Example from a production service**:

```python
CERT_DIR = Path("/tmp/kafka_certificates")

def _restore_pem(env_value: str) -> str:
    """Restore PEM file content from a space-separated env var."""
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
    CERT_DIR.mkdir(parents=True, exist_ok=True)

    pem_files = {
        "server.pem": loaded_config.KAFKA_SERVER_PEM,
        "ca-certificate.pem": loaded_config.KAFKA_CA_CERTIFICATE_PEM,
        "ca-certificate.key": loaded_config.KAFKA_CA_CERTIFICATE_KEY,
    }
    for filename, content in pem_files.items():
        path = CERT_DIR / filename
        path.write_text(_restore_pem(content))
        os.chmod(path, 0o600)
        print(f"[entrypoint] Wrote {path}", flush=True)

    keytab_path = CERT_DIR / "service.keytab"
    keytab_path.write_bytes(
        base64.b64decode(loaded_config.KAFKA_KEYTAB_BASE64)
    )
    os.chmod(keytab_path, 0o600)

    os.environ["KAFKA_SSL_CA_FILE"] = str(CERT_DIR / "server.pem")
    os.environ["KAFKA_KEYTAB_PATH"] = str(CERT_DIR / "service.keytab")
```

**Pattern**: PEM restoration from space-separated env var; keytab from base64; write to `/tmp/` with `0o600`; update env vars to point at generated files.

### PEM Escape Pattern

**Example from a production service**:

```python
def download_certificates():
    public_certificate = loaded_config.API_PUBLIC_CERTIFICATE
    private_key = loaded_config.API_PRIVATE_KEY

    cert_directory = "/srv/app/certificates"
    os.makedirs(cert_directory, exist_ok=True)
    
    public_certificate = public_certificate.replace("\\n", "\n")
    private_key = private_key.replace("\\n", "\n")

    with open(public_cert_file, "w") as pub_file:
        pub_file.write(public_certificate)

    with open(private_key_file, "w") as private_file:
        private_file.write(private_key)
```

**Pattern**: Replace `\n` literal with actual newlines; write certs to filesystem.

## Docker Compose Patterns

### Health Checks and Dependencies Pattern

**Example from a production service**:

```yaml
services:
  api:
    depends_on:
      db:
        condition: service_healthy
      redis:
        condition: service_healthy
      kafka:
        condition: service_healthy

  db:
    healthcheck:
      test: pg_isready -U app
      interval: 2s
      timeout: 3s
      retries: 40

  redis:
    healthcheck:
      test: redis-cli ping
      interval: 1s
      timeout: 3s
      retries: 50

  kafka:
    healthcheck:
      test: kafka-topics.sh --list --bootstrap-server localhost:9092
      interval: 1s
      timeout: 3s
      retries: 30
```

**Pattern**: `depends_on` with `condition: service_healthy`; health checks for postgres, redis, kafka.

### One Image, Many Containers Pattern

**Example from a production service**:

```yaml
x-environment: &common-environment-variables
  ENV: DEV
  POSTGRES_READ_WRITE: postgresql://admin:<REDACTED>@app-postgres:5432/app_db
  REDIS_READ_WRITE: redis://app-redis:6379/9

services:
  app-server:
    image: app:latest
    environment:
      <<: *common-environment-variables
      MODE: server
      DEBUG_PORT: 5679

  db-events-worker:
    image: app:latest
    environment:
      <<: *common-environment-variables
      MODE: worker
      WORKER_MODE: db_events_publisher
      DEBUG_PORT: 5680

  audit-consumer:
    image: app:latest
    environment:
      <<: *common-environment-variables
      MODE: consumer
      CONSUMER_NAME: audit_consumer
      DEBUG_PORT: 5681

  scheduled-job:
    image: app:latest
    environment:
      <<: *common-environment-variables
      MODE: cron
      CRON_JOB: daily_sync
      DEBUG_PORT: 5683
```

**Pattern**: Same `image: app:latest` reused for server, worker, consumer, cron; YAML anchor for shared env; unique debug ports.

## Cloud Run Deployment

### GitHub Actions Workflow Pattern

**Example from a production service**:

```yaml
- name: Build and push Docker image
  run: |
    docker build -t gcr.io/${{ vars.GCP_PROJECT_ID }}/app-backend-dev:${{ github.sha }} .
    docker push gcr.io/${{ vars.GCP_PROJECT_ID }}/app-backend-dev:${{ github.sha }}

- name: Deploy server to Cloud Run
  run: |
    gcloud run deploy app-backend-dev \
      --image gcr.io/${{ vars.GCP_PROJECT_ID }}/app-backend-dev:${{ github.sha }} \
      --memory 2Gi \
      --cpu 2 \
      --min-instances 0 \
      --max-instances 3 \
      --timeout 600 \
      --add-cloudsql-instances ${{ vars.CLOUDSQL_INSTANCE_CONNECTION }} \
      --vpc-connector ${{ vars.VPC_CONNECTOR }} \
      --set-env-vars="MODE=server,\
        POSTGRES_HOST=/cloudsql/${{ vars.CLOUDSQL_INSTANCE_CONNECTION }},\
        POSTGRES_PASSWORD=${{ vars.POSTGRES_PASSWORD }},\
        REDIS_URL=${{ vars.REDIS_URL }},\
        JWT_SECRET_KEY=${{ vars.JWT_SECRET_KEY }}"
```

**Pattern**: MODE=server env var; CloudSQL socket connection; VPC connector; secrets as env vars; autoscaling config.

## Summary

| Pattern | Description |
|---------|-------------|
| Multi-stage Dockerfile | Alpine builder + runtime separation |
| Slim Dockerfile | Python:3.12-slim + gunicorn |
| Custom base image | Minimal Dockerfile using custom registry base |
| MODE dispatch (5 modes) | server/consumer/worker/cron/temporal_worker |
| MODE dispatch (8 modes) | Extended with orchestrator_worker, signal_forwarder |
| MODE dispatch (2 modes) | Minimal server/consumer pattern |
| Cert/keytab writing | PEM restoration and keytab base64 decode |
| PEM `\n` replacement | Literal `\n` to newline conversion |
| docker-compose health checks | pg_isready, redis-cli ping, kafka-topics.sh |
| One image, many containers | YAML anchor + MODE env pattern |
| Cloud Run deployment | gcloud run deploy with CloudSQL/VPC/secrets |

All snippets redacted for secrets (passwords, API keys, service account tokens).
