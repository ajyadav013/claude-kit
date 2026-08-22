# Repo Evidence

This document contains genericized code snippets from real production services demonstrating the configargparse-yaml-env-layering pattern. All internal identifiers, service names, URLs, and secrets have been removed or replaced with placeholders.

## Pattern overview

The pattern appears across multiple Python backend services with common structure:

- `config/config_parser.py` — configargparse setup
- `config/default.yaml` — YAML defaults
- `config/docker_config.py` — Pydantic BaseSettings wrapper
- `entrypoint.py` — MODE-based dispatch

## config_parser.py structure

**Generic example**:

```python
# config/config_parser.py
import os
import sys
import configargparse

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FILE_FORMAT = "{0}/{1}"
YAML_FILE = "default.yaml"

default_config_file = FILE_FORMAT.format(BASE_DIR, YAML_FILE)

parser = configargparse.ArgParser(
    config_file_parser_class=configargparse.YAMLConfigFileParser,
    default_config_files=[default_config_file],
    auto_env_var_prefix="",
)

# Environment
parser.add("--ENV", help="ENV")
parser.add("--DEBUG", help="DEBUG")

# Mode
parser.add("--MODE", help="MODE")
parser.add("--WORKER_MODE", help="WORKER_MODE")
parser.add("--CONSUMER_NAME", help="CONSUMER_NAME")
parser.add("--CRON_JOB", help="CRON_JOB")

# Server
parser.add("--HOST", help="host")
parser.add("--PORT", help="PORT")

# Database
parser.add("--POSTGRES_DB_URL", help="PostgreSQL database URL")
parser.add("--REDIS_URL", help="Redis URL")

# Kafka
parser.add("--KAFKA_BROKER_LIST", help="KAFKA_BROKER_LIST")

# Temporal
parser.add("--TEMPORAL_HOST", help="TEMPORAL_HOST")
parser.add("--TEMPORAL_NAMESPACE", help="TEMPORAL_NAMESPACE")

# GCP
parser.add("--GOOGLE_CLOUD_PROJECT", help="GOOGLE_CLOUD_PROJECT")
parser.add("--GCS_BUCKET", help="GCS_BUCKET")

# BigQuery
parser.add("--BQ_PROJECT_ID", type=str, help="BQ_PROJECT_ID")
parser.add("--BQ_LOCATION", type=str, help="BQ_LOCATION")
parser.add("--BQ_DATASET_ID", type=str, help="BQ_DATASET_ID")

# Vertex AI
parser.add("--VERTEX_PROJECT_ID", type=str, help="VERTEX_PROJECT_ID")
parser.add("--VERTEX_LOCATION", type=str, help="VERTEX_LOCATION")
parser.add("--VERTEX_MODEL", type=str, help="VERTEX_MODEL")

# Sentry
parser.add("--SENTRY_DSN", help="SENTRY_DSN")
parser.add("--ENABLE_SENTRY", help="ENABLE_SENTRY")
parser.add("--SENTRY_ENVIRONMENT", help="SENTRY_ENVIRONMENT")

# Prometheus
parser.add("--PROMETHEUS", help="PROMETHEUS")

# Kubernetes
parser.add("--K8S_POD_NAME", help="K8S_POD_NAME")
parser.add("--K8S_POD_NAMESPACE", help="K8S_POD_NAMESPACE")
parser.add("--K8S_NODE_NAME", help="K8S_NODE_NAME")

# Observability
parser.add("--OTLP_ENDPOINT", help="OpenTelemetry OTLP endpoint")
parser.add("--SERVICE_NAME", help="Service name for observability")
parser.add("--LOG_LEVEL", help="Logging level")
parser.add("--LOG_FORMAT", help="Log format (json or text)")

arguments = sys.argv
argument_options = parser.parse_known_args(arguments)

docker_args = argument_options[0]
```

**Key patterns observed**:

- Consistent use of `auto_env_var_prefix=""` for automatic env var discovery
- `parse_known_args(sys.argv)` to capture both known and unknown args
- `docker_args` namespace exposes parsed config
- Grouped parser.add calls by domain (Environment, Mode, Database, etc.)
- Help strings are often terse (just the key name) or descriptive

## default.yaml structure

**Generic example**:

```yaml
# config/default.yaml

# Environment
ENV: development
DEBUG: true
HOST: localhost
PORT: 8000

# Mode
MODE: server
CRON_JOB: default_job
WORKER_MODE: default_worker
CONSUMER_NAME: default_consumer

# Database
POSTGRES_DB_URL: postgresql+asyncpg://postgres:postgres@localhost/mydb
REDIS_URL: redis://localhost:6379

# Kafka
KAFKA_BROKER_LIST: localhost:9092

# Temporal
TEMPORAL_HOST: localhost:7233
TEMPORAL_NAMESPACE: default

# GCP
GOOGLE_CLOUD_PROJECT: my-local-project
GCS_BUCKET: my-local-bucket

# BigQuery
BQ_PROJECT_ID: my-local-project
BQ_LOCATION: US
BQ_DATASET_ID: my_dataset

# Vertex AI
VERTEX_PROJECT_ID: my-local-project
VERTEX_LOCATION: us-central1
VERTEX_MODEL: gemini-1.5-flash

# Sentry
ENABLE_SENTRY: false
SENTRY_ENVIRONMENT: development
SENTRY_DSN: https://<REDACTED>@sentry.io/123456

# Prometheus
PROMETHEUS: false

# Kubernetes (placeholders for local dev)
K8S_POD_NAME: local
K8S_POD_NAMESPACE: default
K8S_NODE_NAME: local

# Observability
OTLP_ENDPOINT: http://localhost:4317
SERVICE_NAME: my-service
LOG_LEVEL: INFO
LOG_FORMAT: json
```

**Key patterns observed**:

- Development-friendly defaults (localhost, local ports)
- All config keys documented in one place
- Secrets/DSNs use placeholders or redacted strings
- Grouped by domain matching config_parser.py structure
- Boolean flags default to false for expensive features (Sentry, Prometheus)
- Kubernetes env vars have placeholder values for local dev

## docker_config.py structure

**Generic example**:

```python
# config/docker_config.py
import enum
from pydantic_settings import BaseSettings
from config.config_parser import docker_args

args = docker_args

class LogLevel(enum.Enum):
    NOTSET = "NOTSET"
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    FATAL = "FATAL"

class Settings(BaseSettings):
    # Environment
    ENV: str = args.ENV
    DEBUG: bool = args.DEBUG
    HOST: str = args.HOST
    PORT: int = args.PORT

    # Mode
    MODE: str = args.MODE
    CRON_JOB: str = args.CRON_JOB
    WORKER_MODE: str = args.WORKER_MODE or "default_worker"
    CONSUMER_NAME: str = args.CONSUMER_NAME or "default_consumer"

    # Database
    POSTGRES_DB_URL: str = args.POSTGRES_DB_URL
    db_url: str = args.POSTGRES_DB_URL  # alias for ORM
    DB_ECHO: bool = args.DEBUG
    REDIS_URL: str = args.REDIS_URL

    # Kafka
    KAFKA_BROKER_LIST: str = args.KAFKA_BROKER_LIST

    # Temporal
    TEMPORAL_HOST: str = args.TEMPORAL_HOST
    TEMPORAL_NAMESPACE: str = args.TEMPORAL_NAMESPACE

    # GCP
    GOOGLE_CLOUD_PROJECT: str = args.GOOGLE_CLOUD_PROJECT
    GCS_BUCKET: str = args.GCS_BUCKET

    # BigQuery
    BQ_PROJECT_ID: str = args.BQ_PROJECT_ID
    BQ_LOCATION: str = args.BQ_LOCATION
    BQ_DATASET_ID: str = args.BQ_DATASET_ID

    # Vertex AI
    VERTEX_PROJECT_ID: str = args.VERTEX_PROJECT_ID
    VERTEX_LOCATION: str = args.VERTEX_LOCATION
    VERTEX_MODEL: str = args.VERTEX_MODEL

    # Sentry
    SENTRY_DSN: str = args.SENTRY_DSN
    ENABLE_SENTRY: bool = args.ENABLE_SENTRY
    SENTRY_ENVIRONMENT: str = args.SENTRY_ENVIRONMENT

    # Prometheus
    PROMETHEUS: str = args.PROMETHEUS

    # Kubernetes
    K8S_POD_NAME: str = args.K8S_POD_NAME
    K8S_POD_NAMESPACE: str = args.K8S_POD_NAMESPACE
    K8S_NODE_NAME: str = args.K8S_NODE_NAME

    # Observability (with getattr for optional keys)
    OTLP_ENDPOINT: str = getattr(args, 'OTLP_ENDPOINT', 'http://localhost:4317')
    SERVICE_NAME: str = getattr(args, 'SERVICE_NAME', 'my-service')
    LOG_LEVEL: str = getattr(args, 'LOG_LEVEL', 'INFO')
    LOG_FORMAT: str = getattr(args, 'LOG_FORMAT', 'json')

    # Computed fields
    WORKERS_COUNT: int = 1

# Module-level singleton
loaded_config = Settings()
```

**Key patterns observed**:

- `from config.config_parser import docker_args` and `args = docker_args` alias
- Each field: `KEY: type = args.KEY_NAME`
- Optional fields use `getattr(args, 'KEY', 'default')`
- Derived fields (e.g., `db_url` as alias for `POSTGRES_DB_URL`)
- `DB_ECHO` often derived from `DEBUG`
- `WORKER_MODE` and `CONSUMER_NAME` have fallback defaults via `or`
- Module-level singleton: `loaded_config = Settings()`

## Temporal-safe imports

**Pattern for Temporal-incompatible imports**:

```python
# config/docker_config.py
from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from global_utils.http import AsyncHTTPClient
    from global_utils.bigquery_utils import BigQueryUtils

class Settings(BaseSettings):
    # ... config fields
    http: AsyncHTTPClient | None = None
    big_query_client: BigQueryUtils | None = None

loaded_config = Settings()
```

**Why**: Temporal workflows serialize all imports. Heavy clients (HTTP, BigQuery) can't be serialized, so wrap them in `workflow.unsafe.imports_passed_through()` to prevent serialization.

## entrypoint.py structure

**Generic example**:

```python
# entrypoint.py
import asyncio
from config.docker_config import loaded_config
from app.main import main as server_main
from services.kafka.consumer import main as consumer_main
from services.temporal.run_workers import worker_main
from services.crons.setup import crons

def start_server():
    server_main()

def start_consumer():
    asyncio.run(consumer_main())

def start_temporal_worker():
    worker_mode = loaded_config.WORKER_MODE
    asyncio.run(worker_main(worker_mode))

def start_cron():
    cron_job = crons.get(loaded_config.CRON_JOB)
    if cron_job:
        asyncio.run(cron_job())

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
```

**Key patterns observed**:

- `from config.docker_config import loaded_config` at top
- One function per mode: `start_server()`, `start_consumer()`, etc.
- `mode_actions` dict maps MODE value to function
- `asyncio.run()` for async main functions (consumer, worker, cron)
- Temporal worker often reads `loaded_config.WORKER_MODE` for further dispatch
- Cron reads `loaded_config.CRON_JOB` and looks up in `crons` dict
- Multiple MODE values can map to same function (e.g., `server`, `webhook_server`, `test`)

## Entrypoint with telemetry

**Pattern for Sentry and OpenTelemetry**:

```python
# entrypoint.py
import asyncio
import sentry_sdk
from config.docker_config import loaded_config
from config.logging import initialize_opentelemetry
from app.main import main as server_main
from services.kafka.consumer import main as consumer_main
from services.temporal.run_workers import worker_main
from services.crons.setup import crons

def initialize_telemetry_and_error_tracking():
    initialize_opentelemetry()
    if loaded_config.ENABLE_SENTRY:
        sentry_sdk.init(
            dsn=loaded_config.SENTRY_DSN,
            environment=loaded_config.SENTRY_ENVIRONMENT,
        )

def start_server():
    server_main()

def start_consumer():
    asyncio.run(consumer_main())

def start_temporal_worker():
    worker_mode = loaded_config.WORKER_MODE
    asyncio.run(worker_main(worker_mode))

def start_cron():
    cron_job = crons.get(loaded_config.CRON_JOB)
    if cron_job:
        asyncio.run(cron_job())

mode_actions = {
    "server": start_server,
    "consumer": start_consumer,
    "temporal_worker": start_temporal_worker,
    "cron": start_cron,
}

if __name__ == "__main__":
    initialize_telemetry_and_error_tracking()
    action = mode_actions.get(loaded_config.MODE)
    if action:
        action()
```

## Optional settings wrapper

**Some services wrap loaded_config in a domain-specific settings class**:

```python
# packages/common/settings.py
from config.docker_config import loaded_config

class Settings:
    """Application settings using loaded_config."""

    # Database
    @property
    def database_url(self) -> str:
        return loaded_config.POSTGRES_DB_URL

    # Kafka
    @property
    def kafka_broker_list(self) -> str:
        return loaded_config.KAFKA_BROKER_LIST

    # Temporal
    @property
    def temporal_host(self) -> str:
        return loaded_config.TEMPORAL_HOST

    @property
    def temporal_namespace(self) -> str:
        return loaded_config.TEMPORAL_NAMESPACE

    # Observability
    @property
    def environment(self) -> str:
        return loaded_config.ENV

    @property
    def service_name(self) -> str:
        return loaded_config.SERVICE_NAME

    # Consumer Configuration
    @property
    def consumer_name(self) -> str | None:
        return loaded_config.CONSUMER_NAME

    # Worker Configuration
    @property
    def worker_mode(self) -> str | None:
        return loaded_config.WORKER_MODE

# Global settings instance
settings = Settings()
```

**Usage**:

```python
from packages.common.settings import settings

db_url = settings.database_url
env = settings.environment
```

**Note**: This is optional. Most services access `loaded_config` directly without a wrapper.

## Common config keys observed

**Across all services**:

- `ENV` (development/staging/production)
- `DEBUG` (bool)
- `MODE` (server/consumer/temporal_worker/cron)
- `WORKER_MODE` (for temporal_worker mode)
- `CONSUMER_NAME` (for consumer mode)
- `CRON_JOB` (for cron mode)
- `POSTGRES_*_READ_WRITE` (database URL)
- `REDIS_*_READ_WRITE` (Redis URL)
- `KAFKA_BROKER_LIST`
- `TEMPORAL_HOST`, `TEMPORAL_NAMESPACE`
- `GOOGLE_CLOUD_PROJECT`
- `SENTRY_DSN`, `ENABLE_SENTRY`, `SENTRY_ENVIRONMENT`
- `PROMETHEUS` (bool or string)
- `K8S_POD_NAME`, `K8S_POD_NAMESPACE`, `K8S_NODE_NAME`

**GCP-specific**:

- `BQ_PROJECT_ID`, `BQ_LOCATION`, `BQ_DATASET_ID`
- `VERTEX_PROJECT_ID`, `VERTEX_LOCATION`, `VERTEX_MODEL`
- `GCS_BUCKET`

**Service-specific examples**:

- `OTLP_ENDPOINT`, `SERVICE_NAME`, `LOG_LEVEL`, `LOG_FORMAT`
- `API_HOST`, `API_PORT`, `API_WORKERS`
- `QUERY_GCS_FILE_PATH`, `QUERY_GCS_BUCKET_NAME`

## File paths

**Typical file structure**:

```
service-root/
├── config/
│   ├── config_parser.py
│   ├── default.yaml
│   ├── docker_config.py
│   └── logging.py (optional, for OpenTelemetry setup)
├── entrypoint.py
├── app/
│   └── main.py
├── services/
│   ├── kafka/
│   │   └── consumer/
│   │       └── consumer.py
│   ├── temporal/
│   │   └── run_workers.py
│   └── crons/
│       └── setup.py
└── packages/ (optional)
    └── common/
        └── settings.py
```

## Summary

The pattern is remarkably consistent across services:

1. **config_parser.py**: configargparse with `auto_env_var_prefix=""`, YAML default file, `docker_args` namespace
2. **default.yaml**: flat structure with development defaults, no secrets
3. **docker_config.py**: Pydantic BaseSettings wrapping `docker_args`, `loaded_config` singleton
4. **entrypoint.py**: MODE-based dispatch to server/consumer/worker/cron main functions

The three-layer hierarchy (YAML < env < CLI) and MODE-based entrypoint dispatch are the defining features.
