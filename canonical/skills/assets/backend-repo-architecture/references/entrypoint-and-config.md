# Entrypoint and Config Patterns

Details on the MODE-based entrypoint dispatcher and the config chain (docker_config/loaded_config/config_parser).

## MODE-based entrypoint dispatcher

All services use a single `entrypoint.py` at the repo root to dispatch on the `MODE` environment variable. This allows a single Docker image to run in multiple modes (server, consumer, worker, cron).

### MODE dispatch table

| MODE | Invocation | Purpose |
|------|------------|---------|
| `server` | `uvicorn app.application:get_app --factory=True` or `app.main.main()` | FastAPI HTTP server |
| `consumer` | `asyncio.run(services.kafka.consumer.consumer.main())` | Kafka consumer (infinite loop) |
| `temporal_worker` | `asyncio.run(services.temporal.run.worker_main(worker_mode, queue))` | Temporal workflow/activity worker |
| `worker` | `asyncio.run(workers.run.main())` | Background task worker (non-Temporal) |
| `cron` | `asyncio.run(crons.run.main())` | Scheduled cron job (one-shot or loop) |
| `webhook_server` | `uvicorn webhook.application:get_app --factory=True` | Separate webhook receiver server |

### Entrypoint pattern example

```python
import os
from opentelemetry.instrumentation import auto_instrumentation
import sentry_config
from config.docker_config import loaded_config
from metrics.service_init import execute_mode, init_metrics_for_service, log_metrics_status

MODE = os.environ.get("MODE")

# Initialize telemetry for all modes
sentry_config.initialize()
auto_instrumentation.initialize()

# Initialize metrics for all service modes
print(f"Initializing metrics for service mode: {MODE}")
metrics_port = init_metrics_for_service(MODE or "unknown")
log_metrics_status(MODE or "unknown", metrics_port)

if MODE == "server":
    import asyncio
    from src.main import main as server_main
    
    if __name__ == "__main__":
        server_main()  # Calls uvicorn.run(...)

elif MODE == "consumer":
    import asyncio
    from src.services.kafka.consumer.consumer import main as consumer_main
    
    print("Starting Consumer")
    asyncio.run(execute_mode(consumer_main))

elif MODE == "worker":
    import asyncio
    from src.workers.run import main as worker_main
    
    worker_mode = loaded_config.WORKER_MODE
    print(f"Starting {worker_mode} Worker")
    asyncio.run(execute_mode(worker_main))

elif MODE == "cron":
    import asyncio
    from src.crons.run import main as cron_main
    
    cron_job = loaded_config.CRON_JOB
    print(f"Starting {cron_job} Cron Job")
    asyncio.run(execute_mode(cron_main))

elif MODE == "temporal_worker":
    import asyncio
    from src.temporal.run import worker_main
    
    print("Starting Temporal Worker")
    worker_mode = loaded_config.WORKER_MODE
    temporal_queue = loaded_config.TEMPORAL_QUEUE
    asyncio.run(execute_mode(worker_main, worker_mode, temporal_queue))

else:
    print(f"MODE {MODE} not available")
```

### Entrypoint pattern (simplified variant)

```python
from opentelemetry.instrumentation import auto_instrumentation

auto_instrumentation.initialize()

from config.docker_config import loaded_config

if loaded_config.MODE == "server":
    from app.main import main as server_main
    
    if __name__ == "__main__":
        server_main()

elif loaded_config.MODE == "consumer":
    import asyncio
    from services.kafka.consumer.consumer import main as consumer_main
    
    print("Starting Consumer")
    asyncio.run(consumer_main())

else:
    print("MODE not available")
```

### Key principles

1. **No business logic in entrypoint.py**: Only imports and dispatch. All logic lives in domain modules.
2. **Lazy imports**: Import service modules inside the if/elif blocks to avoid loading unused code.
3. **Telemetry init before dispatch**: Sentry, OpenTelemetry, metrics init happens before MODE dispatch so all modes are instrumented.
4. **asyncio.run for workers/consumers**: Server mode uses uvicorn.run (which handles its own event loop). Worker/consumer modes use asyncio.run.
5. **Graceful defaults**: If MODE is not set or invalid, print an error and exit (do not start the server).

---

## Config patterns

### Pattern A: pydantic-settings only

**File**: `config/settings.py`

```python
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    # Core
    DATABASE_URL: str = "postgresql+asyncpg://app:<REDACTED>@localhost:5432/app_db"
    REDIS_URL: str = "redis://localhost:6379/0"
    SECRET_KEY: str = "change-me-in-production"
    DEBUG: bool = False
    DB_ECHO: bool = False
    DB_POOL_SIZE: int = 30
    DB_MAX_OVERFLOW: int = 40
    DB_POOL_RECYCLE: int = 3600
    
    # Sessions
    SESSION_TTL_SECONDS: int = 604800
    SESSION_COOKIE_NAME: str = "app_sid"
    
    # CORS
    CORS_ORIGINS: list[str] = ["http://localhost:3000", "http://localhost:5173"]
    
    # Kafka
    KAFKA_ENABLED: bool = False
    KAFKA_BOOTSTRAP_SERVERS: str = "kafka:9092"
    KAFKA_CONSUMER_GROUP: str = "myservice-consumer"
    
    # Temporal
    TEMPORAL_ENABLED: bool = False
    TEMPORAL_HOST: str = "temporal:7233"
    TEMPORAL_NAMESPACE: str = "myservice"
    TEMPORAL_TASK_QUEUE: str = "myservice-tasks"
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

# Module-level singleton
settings = Settings()
```

**Usage**:

```python
from config.settings import settings

app = FastAPI(debug=settings.DEBUG)
engine = create_async_engine(settings.DATABASE_URL, pool_size=settings.DB_POOL_SIZE)
```

**Pros**: Simple, type-safe, auto-loads from .env, validation on startup.

**Cons**: No YAML support, no command-line arg override.

---

### Pattern B: pydantic-settings + configargparse

**File**: `config/config_parser.py`

```python
import configargparse

parser = configargparse.ArgParser(default_config_files=["config.yaml"])
parser.add("-c", "--config", is_config_file=True, help="Config file path")
parser.add("--ENV", env_var="ENV", default="Test")
parser.add("--HOST", env_var="HOST", default="localhost")
parser.add("--PORT", env_var="PORT", type=int, default=8000)
# ... more args

docker_args, _ = parser.parse_known_args()
```

**File**: `config/docker_config.py`

```python
import os
from pydantic_settings import BaseSettings
from dotenv import load_dotenv
from config.config_parser import docker_args

args = docker_args

# Load .env from root folder
root_folder = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../"))
dotenv_path = os.path.join(root_folder, ".env")
load_dotenv(dotenv_path)

ENV = os.environ.get("ENV", "Test")

class Settings(BaseSettings):
    class Config:
        env_file = "../../.env"
        env_file_encoding = "utf-8"
    
    CORS_ORIGIN: Optional[str] = None
    ENV: str = args.ENV
    HOSTNAME: str = args.HOST
    
    POSTGRES_READ_WRITE: str
    POSTGRES_READ_WRITE = os.environ.get("POSTGRES_READ_WRITE", "<REDACTED>")
    
    REDIS_READ_WRITE: str
    REDIS_READ_WRITE = os.environ.get("REDIS_READ_WRITE", "<REDACTED>")
    
    # ... more env vars

# Module-level singleton
loaded_config = Settings()
```

**Usage**:

```python
from config.docker_config import loaded_config

app = FastAPI(debug=loaded_config.DEBUG)
worker_mode = loaded_config.WORKER_MODE
```

**Pros**: Supports YAML config files, command-line args, environment variables (precedence: CLI > env > YAML > defaults). Gradual migration from YAML to env.

**Cons**: More complex, two-step config loading, harder to reason about precedence.

---

### Config loading order (Pattern B)

1. `config_parser.py` parses CLI args and YAML (via configargparse)
2. `docker_config.py` imports `docker_args`, loads .env via `load_dotenv()`
3. `Settings(BaseSettings)` merges `docker_args.*` fields with `os.environ.get()` for secrets
4. Module-level `loaded_config = Settings()` singleton created on first import

**Precedence** (highest to lowest):
1. Command-line arguments (`--ENV=Prod`)
2. Environment variables (`export ENV=Prod`)
3. YAML config file (`config.yaml`)
4. Default values in `parser.add()`

---

## Environment variable naming conventions

All services follow these conventions:

| Variable | Type | Example | Purpose |
|----------|------|---------|---------|
| `MODE` | str | `server`, `consumer`, `temporal_worker` | Entrypoint dispatcher |
| `ENV` | str | `Dev`, `Staging`, `Prod` | Environment name |
| `DEBUG` | bool | `True`, `False` | Enable debug mode, verbose logs |
| `DATABASE_URL` | str | `postgresql+asyncpg://user:pass@host:port/db` | Primary database connection |
| `REDIS_URL` | str | `redis://host:port/db` | Redis connection |
| `KAFKA_BOOTSTRAP_SERVERS` | str | `kafka1:9092,kafka2:9092` | Kafka brokers |
| `KAFKA_CONSUMER_GROUP` | str | `myservice-consumer` | Kafka consumer group ID |
| `TEMPORAL_HOST` | str | `temporal:7233` | Temporal server |
| `TEMPORAL_NAMESPACE` | str | `myservice` | Temporal namespace |
| `TEMPORAL_QUEUE` | str | `myservice-tasks` | Temporal task queue |
| `WORKER_MODE` | str | `data_worker`, `processing_worker` | Which worker to run |
| `CRON_JOB` | str | `sync_data`, `cleanup_cache` | Which cron job to run |
| `SERVER_TYPE` | str | `public`, `internal`, `platform`, `webhook` | Multi-deployment gating |
| `DEPLOYMENT_NAME` | str | `us-east`, `eu-west` | Region/deployment-specific routing |
| `CORS_ORIGINS` | list[str] | `["http://localhost:3000"]` | Allowed CORS origins |
| `SECRET_KEY` | str | `<REDACTED>` | JWT signing key, session encryption |

---

## Best practices

1. **Always set MODE**: Never rely on default MODE. Explicitly set it in Dockerfile/docker-compose/k8s deployment.
2. **Validate required env vars on startup**: Use pydantic-settings validation to fail fast if required vars are missing.
3. **Never commit secrets**: Use .env (gitignored) or secret management (Vault, k8s secrets, AWS Secrets Manager).
4. **Use typed config**: pydantic-settings provides type validation, auto-conversion, IDE autocomplete.
5. **Single source of truth**: All config in one Settings class. Avoid scattered `os.environ.get()` calls.
6. **Module-level singleton**: Create `settings = Settings()` or `loaded_config = Settings()` once, import everywhere.
7. **Environment-specific defaults**: Use different .env files (.env.dev, .env.staging, .env.prod) or k8s ConfigMaps per environment.
