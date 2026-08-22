---
name: configargparse-yaml-env-layering
description: Three-layer service config — YAML defaults, configargparse CLI/env override, Pydantic BaseSettings singleton. Use for Python services with multiple runtime modes and precedence-ordered config sources.
---

Standardize service configuration using a three-layer hierarchy with YAML defaults, configargparse CLI/env merging, and a Pydantic BaseSettings singleton.

## When to use

- Setting up configuration for a new Python backend service or microservice
- Building services with multiple runtime modes (server, consumer, temporal_worker, cron)
- Implementing precedence-ordered configuration (YAML defaults < environment variables < CLI arguments)
- Migrating from flat .env files to structured, type-safe configuration
- Configuring services that need different entrypoints based on MODE environment variable
- Setting up mode-specific dispatch via entrypoint.py pattern
- Building container-deployable services that override defaults via environment variables
- Needing a module-level config singleton accessible throughout the codebase
- Implementing auto-prefixed environment variable parsing for all config keys
- Setting up services with database, Kafka, Temporal, Redis, and other infrastructure dependencies

## Core conventions

1. **Three-layer config hierarchy**: (1) `config/default.yaml` contains structured defaults for all environments; (2) `configargparse.ArgParser` with `auto_env_var_prefix=""` merges CLI args and env vars over YAML; (3) `config/docker_config.py` wraps parsed args in Pydantic `BaseSettings` and exports a module-level singleton `loaded_config`. Precedence: YAML < env vars < CLI args.

2. **YAML defaults in `config/default.yaml`**: define all config keys with development-friendly defaults. Structure groups logically (Environment, Mode, Database, Kafka, Temporal, Sentry, etc.). Use scalar types (string, int, bool). Common sections: `ENV`, `MODE`, `DEBUG`, `POSTGRES_*`, `REDIS_*`, `KAFKA_BROKER_LIST`, `TEMPORAL_HOST`, `TEMPORAL_NAMESPACE`, `GOOGLE_CLOUD_PROJECT`. Never commit production secrets; use placeholder values.

3. **configargparse parser in `config/config_parser.py`**: create `parser = configargparse.ArgParser(config_file_parser_class=configargparse.YAMLConfigFileParser, default_config_files=[default_config_file], auto_env_var_prefix="")`. Add each config key via `parser.add("--KEY_NAME", help="...")`. The empty `auto_env_var_prefix` means every `--KEY_NAME` can be set via `KEY_NAME` env var. Parse with `argument_options = parser.parse_known_args(sys.argv)` and expose namespace as `docker_args = argument_options[0]`.

4. **Pydantic BaseSettings wrapper in `config/docker_config.py`**: define `class Settings(BaseSettings)` with fields `KEY: type = args.KEY_NAME` for each config key. Use type annotations (str, int, bool) for validation. Import `from config.config_parser import docker_args` and alias as `args = docker_args`. Export singleton `loaded_config = Settings()` at module level. All application code imports this singleton: `from config.docker_config import loaded_config`.

5. **MODE-based entrypoint dispatch**: `entrypoint.py` imports `loaded_config` and defines `mode_actions = {"server": start_server, "consumer": start_consumer, "temporal_worker": start_temporal_worker, "cron": start_cron}`. Main block: `if __name__ == "__main__": action = mode_actions.get(loaded_config.MODE); if action: action()`. Each mode function delegates to the appropriate main (e.g., `app.main.main`, `services.kafka.consumer.main`, `services.temporal.run_workers.worker_main`).

6. **Common MODE values**: `server` (FastAPI app), `consumer` (Kafka consumer), `temporal_worker` (Temporal worker), `cron` (scheduled job), `webhook_server`, `test`. Worker modes often read `loaded_config.WORKER_MODE` or `loaded_config.CONSUMER_NAME` for further dispatch.

7. **docker_args namespace access pattern**: in `docker_config.py`, use `args.KEY_NAME` to access parsed config. For optional keys with defaults, use `getattr(args, 'KEY_NAME', 'default_value')`. Example: `SERVICE_NAME: str = getattr(args, 'SERVICE_NAME', 'my-service')`.

8. **Import singleton everywhere**: application code never re-parses config. Always `from config.docker_config import loaded_config` and access fields as `loaded_config.DATABASE_URL`, `loaded_config.MODE`, etc. The singleton is initialized once at module import time.

9. **Type-safe config access**: Pydantic validates types at `loaded_config = Settings()` instantiation. If a boolean env var is set to a non-boolean string, instantiation fails. Use explicit type coercion in parser if needed (`parser.add("--DEBUG", type=bool, ...)`).

10. **Optional proxy settings layer**: some services add a `packages/common/settings.py` that wraps `loaded_config` in domain-specific properties. Example: `class Settings` with `@property def database_url(self) -> str: return loaded_config.DATABASE_URL`. This is optional; direct `loaded_config` access is more common.

11. **No .env file dependency**: configargparse's `auto_env_var_prefix=""` makes .env files unnecessary. Container orchestration (Docker Compose, Kubernetes) injects env vars directly. YAML provides local defaults. Never use `python-dotenv`.

12. **Config file location convention**: `config/` directory at service root contains `config_parser.py`, `default.yaml`, `docker_config.py`. Some repos use `config/docker_config.py`, others `config/settings.py`, but the pattern is identical.

13. **Temporal-safe imports**: if using Temporal workflows, wrap heavyweight imports in `with workflow.unsafe.imports_passed_through():` to prevent serialization issues. Example: HTTP clients, BigQuery utils.

14. **Common config keys**: `ENV` (development/staging/production), `MODE` (server/consumer/temporal_worker/cron), `DEBUG` (bool), `POSTGRES_*_READ_WRITE` (database URL), `REDIS_*_READ_WRITE` (Redis URL), `KAFKA_BROKER_LIST`, `TEMPORAL_HOST`, `TEMPORAL_NAMESPACE`, `GOOGLE_CLOUD_PROJECT`, `SENTRY_DSN`, `ENABLE_SENTRY`, `K8S_POD_NAME` / `K8S_POD_NAMESPACE` / `K8S_NODE_NAME` (injected by Kubernetes).

15. **Contrast with plain .env loading**: unlike `python-dotenv`, this pattern supports CLI arg override, YAML structure, type validation, and auto env-var discovery without explicit `.env` file. Cross-reference `pydantic-schema-patterns` for BaseSettings usage and `backend-repo-architecture` for service structure.

## Skeleton / example

```python
# config/config_parser.py
import os
import sys
import configargparse

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
YAML_FILE = "default.yaml"
default_config_file = f"{BASE_DIR}/{YAML_FILE}"

parser = configargparse.ArgParser(
    config_file_parser_class=configargparse.YAMLConfigFileParser,
    default_config_files=[default_config_file],
    auto_env_var_prefix="",
)

# Environment
parser.add("--ENV", help="Environment name")
parser.add("--DEBUG", type=bool, help="Enable debug mode")

# Mode
parser.add("--MODE", help="Runtime mode: server/consumer/temporal_worker/cron")
parser.add("--WORKER_MODE", help="Worker mode for temporal_worker")
parser.add("--CONSUMER_NAME", help="Consumer name for Kafka consumer mode")

# Database
parser.add("--POSTGRES_DB_URL", help="PostgreSQL database URL")
parser.add("--REDIS_URL", help="Redis URL")

# Kafka
parser.add("--KAFKA_BROKER_LIST", help="Kafka broker list")

# Temporal
parser.add("--TEMPORAL_HOST", help="Temporal server host:port")
parser.add("--TEMPORAL_NAMESPACE", help="Temporal namespace")

# GCP
parser.add("--GOOGLE_CLOUD_PROJECT", help="GCP project ID")

arguments = sys.argv
argument_options = parser.parse_known_args(arguments)
docker_args = argument_options[0]
```

```yaml
# config/default.yaml
ENV: development
DEBUG: true
MODE: server

POSTGRES_DB_URL: postgresql+asyncpg://postgres:postgres@localhost/mydb
REDIS_URL: redis://localhost:6379

KAFKA_BROKER_LIST: localhost:9092

TEMPORAL_HOST: localhost:7233
TEMPORAL_NAMESPACE: default

GOOGLE_CLOUD_PROJECT: my-local-project
```

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

class Settings(BaseSettings):
    # Environment
    ENV: str = args.ENV
    DEBUG: bool = args.DEBUG

    # Mode
    MODE: str = args.MODE
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

    # Optional with getattr
    SERVICE_NAME: str = getattr(args, 'SERVICE_NAME', 'my-service')
    LOG_LEVEL: str = getattr(args, 'LOG_LEVEL', 'INFO')

# Module-level singleton
loaded_config = Settings()
```

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
    "consumer": start_consumer,
    "temporal_worker": start_temporal_worker,
    "cron": start_cron,
}

if __name__ == "__main__":
    action = mode_actions.get(loaded_config.MODE)
    if action:
        action()
```

```python
# app/main.py (server mode example)
from fastapi import FastAPI
from config.docker_config import loaded_config

def get_app() -> FastAPI:
    app = FastAPI(debug=loaded_config.DEBUG)
    # ... configure app
    return app

def main():
    import uvicorn
    app = get_app()
    uvicorn.run(app, host="0.0.0.0", port=8000)
```

```python
# services/kafka/consumer.py (consumer mode example)
from config.docker_config import loaded_config

async def main():
    consumer_name = loaded_config.CONSUMER_NAME
    kafka_brokers = loaded_config.KAFKA_BROKER_LIST
    # ... set up consumer and run
```

```python
# Any application module
from config.docker_config import loaded_config

def some_function():
    if loaded_config.DEBUG:
        print(f"Running in {loaded_config.ENV} environment")
    db_url = loaded_config.POSTGRES_DB_URL
    # ... use config
```

## Anti-patterns to avoid

1. **Using python-dotenv for env loading**: configargparse with `auto_env_var_prefix=""` makes .env files redundant. Avoid mixing both.
2. **Hardcoding defaults in Settings class**: put all defaults in `default.yaml`, not in Pydantic field defaults.
3. **Re-parsing config in multiple places**: always import the singleton `loaded_config`, never create new `Settings()` instances.
4. **Committing secrets to default.yaml**: use placeholder values or redacted strings, override via env vars in production.
5. **Not using type annotations in Settings**: Pydantic requires type hints for validation; `KEY = args.KEY` without `: str` won't validate.
6. **Missing keys in YAML but present in parser**: ensure every `parser.add("--KEY")` has a corresponding YAML entry, or handle with `getattr(args, 'KEY', None)`.
7. **Forgetting `auto_env_var_prefix=""`**: without this, env vars must be prefixed (e.g., `APP_DEBUG` instead of `DEBUG`).
8. **Mode dispatch with missing mode handlers**: if a MODE value is deployed but not in `mode_actions`, the service silently does nothing. Log a warning or raise an error.
9. **Complex nested config structures in YAML**: keep YAML flat (key: value pairs). Nested dicts complicate configargparse parsing.
10. **Not wrapping Temporal-incompatible imports**: if using Temporal, wrap heavy imports (HTTP clients, BigQuery) in `with workflow.unsafe.imports_passed_through():` to avoid serialization errors.
11. **Using mutable defaults in Settings**: avoid `list` or `dict` defaults; use scalar types only.
12. **Inconsistent naming conventions**: stick to UPPER_SNAKE_CASE for all config keys (both YAML and Settings fields).

## References

- [config-layering-anatomy.md](references/config-layering-anatomy.md) — layer-by-layer breakdown of YAML → configargparse → Pydantic
- [mode-dispatch-and-precedence.md](references/mode-dispatch-and-precedence.md) — MODE-based entrypoint pattern and config precedence order
- [repo-evidence.md](references/repo-evidence.md) — genericized real-world examples
