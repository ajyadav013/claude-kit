# Config Layering Anatomy

This document breaks down the three-layer configuration hierarchy layer by layer.

## The three layers

### Layer 1: YAML defaults (`config/default.yaml`)

**Purpose**: Provide structured defaults for local development and document all config keys.

**Format**: Flat YAML file with scalar values (strings, integers, booleans).

**Location**: `config/default.yaml` in the service root.

**Example structure**:

```yaml
# Environment
ENV: development
DEBUG: true

# Mode
MODE: server
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

# Sentry
ENABLE_SENTRY: false
SENTRY_DSN: https://placeholder@sentry.io/123456
SENTRY_ENVIRONMENT: development

# Kubernetes (injected in production)
K8S_POD_NAME: local
K8S_POD_NAMESPACE: default
K8S_NODE_NAME: local
```

**Key characteristics**:

- All config keys are documented in one place
- Development-friendly defaults (localhost, local ports, debug enabled)
- Production secrets are placeholders or redacted
- Never committed with real credentials
- Groups keys logically (Environment, Mode, Database, etc.)

### Layer 2: configargparse CLI/env merging (`config/config_parser.py`)

**Purpose**: Parse YAML defaults and merge with environment variables and CLI arguments.

**Mechanism**: `configargparse.ArgParser` with `auto_env_var_prefix=""` enables automatic environment variable discovery.

**Location**: `config/config_parser.py`.

**Precedence**: YAML < env vars < CLI args (rightmost wins).

**Example**:

```python
import os
import sys
import configargparse

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
YAML_FILE = "default.yaml"
default_config_file = f"{BASE_DIR}/{YAML_FILE}"

parser = configargparse.ArgParser(
    config_file_parser_class=configargparse.YAMLConfigFileParser,
    default_config_files=[default_config_file],
    auto_env_var_prefix="",  # KEY_NAME env var maps to --KEY_NAME
)

# Add each config key
parser.add("--ENV", help="Environment name")
parser.add("--DEBUG", type=bool, help="Enable debug mode")
parser.add("--MODE", help="Runtime mode")
parser.add("--POSTGRES_DB_URL", help="PostgreSQL database URL")
parser.add("--KAFKA_BROKER_LIST", help="Kafka broker list")
parser.add("--TEMPORAL_HOST", help="Temporal server host:port")
# ... add all keys

arguments = sys.argv
argument_options = parser.parse_known_args(arguments)
docker_args = argument_options[0]
```

**Key characteristics**:

- `default_config_files=[default_config_file]` loads YAML defaults first
- `auto_env_var_prefix=""` means `--DEBUG` can be set via `DEBUG` env var (no prefix)
- `parser.parse_known_args(sys.argv)` merges CLI args over env vars over YAML
- `docker_args` namespace exposes parsed config (e.g., `docker_args.DEBUG`)
- No manual .env file loading needed

**How it works**:

1. Parse YAML defaults from `config/default.yaml`
2. Check environment variables for keys matching `--KEY_NAME` (e.g., `DEBUG`)
3. Parse CLI arguments (e.g., `--DEBUG=false`)
4. Merge with precedence: YAML < env < CLI

**Example precedence**:

```yaml
# config/default.yaml
DEBUG: true
```

```bash
# Environment variable override
export DEBUG=false

# CLI argument override (highest precedence)
python entrypoint.py --DEBUG=true
```

Result: `docker_args.DEBUG == True` (CLI wins).

### Layer 3: Pydantic BaseSettings singleton (`config/docker_config.py`)

**Purpose**: Wrap parsed config in a type-safe Pydantic model and expose as a module-level singleton.

**Location**: `config/docker_config.py`.

**Example**:

```python
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

    # Optional keys with getattr
    SERVICE_NAME: str = getattr(args, 'SERVICE_NAME', 'my-service')
    LOG_LEVEL: str = getattr(args, 'LOG_LEVEL', 'INFO')

# Module-level singleton
loaded_config = Settings()
```

**Key characteristics**:

- `BaseSettings` validates types at instantiation (fails fast on type errors)
- Fields use explicit type annotations (`: str`, `: bool`, `: int`)
- Optional keys use `getattr(args, 'KEY', 'default')` for fallback
- `loaded_config` is instantiated once at module import time
- All application code imports `from config.docker_config import loaded_config`

**Type validation**:

If `DEBUG` env var is set to `"not-a-bool"`, Pydantic raises `ValidationError` at `loaded_config = Settings()` instantiation. This fails fast and prevents runtime errors.

**Singleton pattern**:

```python
# Correct: import the singleton
from config.docker_config import loaded_config

def some_function():
    if loaded_config.DEBUG:
        print(f"Running in {loaded_config.ENV} environment")
```

```python
# WRONG: do not re-instantiate
from config.docker_config import Settings

def some_function():
    config = Settings()  # Don't do this!
```

## How the layers interact

**Startup flow**:

1. `entrypoint.py` imports `from config.docker_config import loaded_config`
2. `config/docker_config.py` imports `from config.config_parser import docker_args`
3. `config/config_parser.py` parses YAML, env vars, and CLI args → `docker_args` namespace
4. `config/docker_config.py` wraps `docker_args` in `Settings(BaseSettings)` → `loaded_config` singleton
5. `entrypoint.py` accesses `loaded_config.MODE` to dispatch to the correct runtime mode

**Runtime access**:

All application code imports `loaded_config` and accesses fields as properties:

```python
from config.docker_config import loaded_config

db_url = loaded_config.POSTGRES_DB_URL
kafka_brokers = loaded_config.KAFKA_BROKER_LIST
is_debug = loaded_config.DEBUG
```

## Why three layers?

**Why YAML defaults?**

- Documents all config keys in one place
- Provides local development defaults without .env files
- Structured format (groups, comments)
- Safe to commit (no secrets)

**Why configargparse?**

- Merges YAML, env vars, and CLI args with clear precedence
- Auto environment variable discovery (`auto_env_var_prefix=""`)
- No manual .env file loading
- Supports CLI override for testing and debugging

**Why Pydantic BaseSettings?**

- Type validation at startup (fail fast)
- IDE autocomplete for config fields
- Enforces config schema (required vs. optional)
- Module-level singleton for consistent access

## Comparison to alternatives

### vs. python-dotenv

| configargparse + YAML | python-dotenv |
|-----------------------|---------------|
| Three-layer precedence (YAML < env < CLI) | Two-layer (env file < env vars) |
| Structured YAML defaults | Flat .env file |
| Auto env var discovery | Manual `os.getenv()` or pydantic-settings |
| CLI override support | No CLI support |
| Type validation via Pydantic | Manual type coercion |

### vs. Pydantic BaseSettings alone

Pydantic `BaseSettings` can load env vars directly, but:

- No YAML defaults (must use env vars or .env file)
- No CLI override support
- Precedence is env vars only

Combining configargparse with Pydantic adds YAML structure and CLI override.

## Common patterns

### Optional config keys

Use `getattr(args, 'KEY', 'default')` for keys not always present:

```python
SERVICE_NAME: str = getattr(args, 'SERVICE_NAME', 'my-service')
LOG_LEVEL: str = getattr(args, 'LOG_LEVEL', 'INFO')
```

### Derived config values

Compute derived values in `Settings`:

```python
class Settings(BaseSettings):
    POSTGRES_DB_URL: str = args.POSTGRES_DB_URL
    db_url: str = args.POSTGRES_DB_URL  # alias for ORM
    DB_ECHO: bool = args.DEBUG  # derive from DEBUG
```

### Temporal-safe imports

Wrap heavy imports in `with workflow.unsafe.imports_passed_through():` to prevent Temporal serialization issues:

```python
from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from global_utils.http import AsyncHTTPClient

class Settings(BaseSettings):
    http: AsyncHTTPClient | None = None
```

### Mode-specific config

Use mode dispatch to load mode-specific dependencies:

```python
# entrypoint.py
if loaded_config.MODE == "consumer":
    consumer_name = loaded_config.CONSUMER_NAME
elif loaded_config.MODE == "temporal_worker":
    worker_mode = loaded_config.WORKER_MODE
```
