# Mode Dispatch and Precedence

This document covers MODE-based entrypoint dispatch and configuration precedence order.

## MODE-based entrypoint pattern

Services using this config pattern often have a single `entrypoint.py` that dispatches to different runtime modes based on the `MODE` config value.

### Common MODE values

| MODE | Purpose | Entry function |
|------|---------|----------------|
| `server` | FastAPI HTTP server | `app.main.main` or `uvicorn.run()` |
| `consumer` | Kafka consumer | `services.kafka.consumer.main` |
| `temporal_worker` | Temporal workflow worker | `services.temporal.run_workers.worker_main` |
| `cron` | Scheduled job runner | `services.crons.setup.crons.get(CRON_JOB)` |
| `webhook_server` | Webhook receiver (alias for server) | Same as `server` |
| `test` | Test mode (often same as server with test DB) | Same as `server` |

### Entrypoint structure

```python
# entrypoint.py
import asyncio
from config.docker_config import loaded_config
from app.main import main as server_main
from services.kafka.consumer import main as consumer_main
from services.temporal.run_workers import worker_main
from services.crons.setup import crons

def start_server():
    """Start FastAPI server via uvicorn."""
    server_main()

def start_consumer():
    """Start Kafka consumer."""
    asyncio.run(consumer_main())

def start_temporal_worker():
    """Start Temporal worker with worker_mode."""
    worker_mode = loaded_config.WORKER_MODE
    asyncio.run(worker_main(worker_mode))

def start_cron():
    """Run a specific cron job."""
    cron_job = crons.get(loaded_config.CRON_JOB)
    if cron_job:
        asyncio.run(cron_job())

# Mode dispatch table
mode_actions = {
    "server": start_server,
    "webhook_server": start_server,
    "test": start_server,
    "consumer": start_consumer,
    "temporal_worker": start_temporal_worker,
    "cron": start_cron,
}

if __name__ == "__main__":
    action = mode_actions.get(loaded_config.MODE)
    if action:
        action()
    else:
        print(f"Unknown MODE: {loaded_config.MODE}")
```

### How it works

1. Container/process starts with `python entrypoint.py`
2. `loaded_config.MODE` is read from YAML/env/CLI (e.g., `MODE=consumer`)
3. `mode_actions.get(loaded_config.MODE)` looks up the handler function
4. Handler function executes the appropriate main (e.g., `consumer_main()`)

### Deployment patterns

**Kubernetes Deployment**:

```yaml
# server deployment
apiVersion: apps/v1
kind: Deployment
metadata:
  name: myservice-server
spec:
  containers:
  - name: server
    image: myservice:latest
    env:
    - name: MODE
      value: server
    - name: ENV
      value: production
    - name: POSTGRES_DB_URL
      valueFrom:
        secretKeyRef:
          name: db-credentials
          key: url
```

```yaml
# consumer deployment (same image, different MODE)
apiVersion: apps/v1
kind: Deployment
metadata:
  name: myservice-consumer
spec:
  containers:
  - name: consumer
    image: myservice:latest
    env:
    - name: MODE
      value: consumer
    - name: CONSUMER_NAME
      value: invoice_consumer
    - name: KAFKA_BROKER_LIST
      value: kafka.kafka.svc.cluster.local:9092
```

**Docker Compose**:

```yaml
services:
  server:
    image: myservice:latest
    environment:
      MODE: server
      ENV: development
      DEBUG: true
    ports:
      - "8000:8000"

  consumer:
    image: myservice:latest
    environment:
      MODE: consumer
      CONSUMER_NAME: default_consumer
      KAFKA_BROKER_LIST: kafka:9092
```

## Worker mode and consumer name dispatch

Some modes support further dispatch via additional config keys.

### Temporal worker mode

```python
# entrypoint.py
def start_temporal_worker():
    worker_mode = loaded_config.WORKER_MODE  # e.g., "workflow_worker", "activity_worker"
    asyncio.run(worker_main(worker_mode))
```

```python
# services/temporal/run_workers.py
async def worker_main(worker_mode: str):
    if worker_mode == "workflow_worker":
        # Run workflows only
        worker = Worker(client, task_queue="workflows", workflows=[...])
    elif worker_mode == "activity_worker":
        # Run activities only
        worker = Worker(client, task_queue="activities", activities=[...])
    else:
        # Run both
        worker = Worker(client, task_queue="default", workflows=[...], activities=[...])
    await worker.run()
```

### Kafka consumer name

```python
# entrypoint.py
def start_consumer():
    asyncio.run(consumer_main())
```

```python
# services/kafka/consumer/consumer.py
from config.docker_config import loaded_config

async def main():
    consumer_name = loaded_config.CONSUMER_NAME  # e.g., "invoice_consumer", "event_consumer"
    handler = consumer_handlers.get(consumer_name)
    if handler:
        await handler.run()
    else:
        logger.error(f"Unknown consumer: {consumer_name}")
```

### Cron job name

```python
# entrypoint.py
def start_cron():
    cron_job = crons.get(loaded_config.CRON_JOB)  # e.g., "daily_sync", "hourly_cleanup"
    if cron_job:
        asyncio.run(cron_job())
```

```python
# services/crons/setup.py
from services.crons import daily_sync, hourly_cleanup

crons = {
    "daily_sync": daily_sync.run,
    "hourly_cleanup": hourly_cleanup.run,
}
```

## Configuration precedence order

### Precedence hierarchy

**Order** (rightmost wins):

```
YAML defaults < environment variables < CLI arguments
```

### Example precedence walkthrough

**config/default.yaml**:

```yaml
ENV: development
DEBUG: true
MODE: server
POSTGRES_DB_URL: postgresql+asyncpg://postgres:postgres@localhost/mydb
```

**Environment variables**:

```bash
export ENV=staging
export DEBUG=false
export POSTGRES_DB_URL=postgresql+asyncpg://postgres:postgres@staging-db/mydb
```

**CLI arguments**:

```bash
python entrypoint.py --ENV=production --DEBUG=true
```

**Result**:

```python
loaded_config.ENV == "production"  # CLI wins
loaded_config.DEBUG == True  # CLI wins
loaded_config.MODE == "server"  # YAML default (no override)
loaded_config.POSTGRES_DB_URL == "postgresql+asyncpg://postgres:postgres@staging-db/mydb"  # env var (no CLI override)
```

### Precedence rules

1. **YAML defaults always load first**: `default_config_files=[default_config_file]` in configargparse.
2. **Environment variables override YAML**: `auto_env_var_prefix=""` means `KEY_NAME` env var overrides `KEY_NAME` YAML key.
3. **CLI arguments override all**: `python entrypoint.py --KEY_NAME=value` is highest precedence.
4. **If a source doesn't specify a key, lower precedence wins**: if no env var or CLI arg for `MODE`, YAML default is used.

### Verification

To see final merged config, log `loaded_config` fields at startup:

```python
# entrypoint.py
if __name__ == "__main__":
    print(f"MODE: {loaded_config.MODE}")
    print(f"ENV: {loaded_config.ENV}")
    print(f"DEBUG: {loaded_config.DEBUG}")
    print(f"POSTGRES_DB_URL: {loaded_config.POSTGRES_DB_URL}")
    action = mode_actions.get(loaded_config.MODE)
    if action:
        action()
```

Or use `configargparse`'s `--help` to see all parsed values:

```bash
python entrypoint.py --help
```

## Testing mode dispatch

### Local development

```bash
# Run server mode locally
python entrypoint.py --MODE=server

# Run consumer mode locally
python entrypoint.py --MODE=consumer --CONSUMER_NAME=test_consumer

# Run temporal worker mode locally
python entrypoint.py --MODE=temporal_worker --WORKER_MODE=workflow_worker

# Run a specific cron job locally
python entrypoint.py --MODE=cron --CRON_JOB=daily_sync
```

### Container testing

```bash
# Test server mode in Docker
docker run -e MODE=server -e DEBUG=true myservice:latest

# Test consumer mode in Docker
docker run -e MODE=consumer -e CONSUMER_NAME=invoice_consumer myservice:latest
```

## Common mode dispatch patterns

### Conditional router inclusion

Some services conditionally include FastAPI routers based on MODE:

```python
# app/application.py
from config.docker_config import loaded_config

def get_app() -> FastAPI:
    app = FastAPI(debug=loaded_config.DEBUG)

    # Always include health check
    app.include_router(health_router)

    # Only include domain routers in server mode
    if loaded_config.MODE == "server":
        app.include_router(api_router)

    return app
```

### Telemetry initialization

Initialize telemetry (Sentry, OpenTelemetry) before mode dispatch:

```python
# entrypoint.py
from config.docker_config import loaded_config
from config.logging import initialize_opentelemetry
import sentry_sdk

def initialize_telemetry():
    initialize_opentelemetry()
    if loaded_config.ENABLE_SENTRY:
        sentry_sdk.init(dsn=loaded_config.SENTRY_DSN, environment=loaded_config.ENV)

if __name__ == "__main__":
    initialize_telemetry()
    action = mode_actions.get(loaded_config.MODE)
    if action:
        action()
```

### Lifespan management

Some modes (server) use FastAPI lifespan; others (consumer, worker) handle lifecycle directly:

```python
# app/lifetime.py (for server mode)
from contextlib import asynccontextmanager
from fastapi import FastAPI
from app.connection import ConnectionManager

@asynccontextmanager
async def lifespan(app: FastAPI):
    ConnectionManager()  # init DB/Redis pools
    yield
    await ConnectionManager().close_connections()
```

```python
# services/kafka/consumer.py (for consumer mode)
async def main():
    connection_manager = ConnectionManager()
    try:
        consumer = await get_consumer()
        async for message in consumer:
            await handle_message(message)
    finally:
        await connection_manager.close_connections()
```

## Error handling

### Unknown MODE

```python
if __name__ == "__main__":
    action = mode_actions.get(loaded_config.MODE)
    if action:
        action()
    else:
        raise ValueError(f"Unknown MODE: {loaded_config.MODE}")
```

### Missing secondary config

```python
def start_consumer():
    if not loaded_config.CONSUMER_NAME:
        raise ValueError("CONSUMER_NAME is required for consumer mode")
    asyncio.run(consumer_main())
```

### Validation at startup

```python
# config/docker_config.py
class Settings(BaseSettings):
    MODE: str = args.MODE
    WORKER_MODE: str = args.WORKER_MODE or "default_worker"

    def __post_init__(self):
        # Validate MODE
        valid_modes = ["server", "consumer", "temporal_worker", "cron"]
        if self.MODE not in valid_modes:
            raise ValueError(f"MODE must be one of {valid_modes}, got {self.MODE}")
```
