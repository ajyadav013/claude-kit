# Naming and Folder Layout Conventions

Standard naming rules and directory organization patterns observed across production Python/FastAPI services.

---

## Naming Conventions

### Files and Functions: snake_case

All Python files, modules, and functions use `snake_case`.

**Examples:**
- `connection_handler.py`
- `get_session_factory()`
- `create_async_engine()`
- `webhook_callback_router.py`
- `load_config_from_env()`

**Pattern:**
- Lowercase letters
- Words separated by underscores
- No camelCase, no PascalCase for files/functions

**Observed in:** All production services.

---

### Classes: PascalCase

All class names use `PascalCase`.

**Examples:**
- `ConnectionManager`
- `ResponseData`
- `CustomRequestRoute`
- `Settings`
- `Singleton`
- `AsyncEventEmitterWrapper`

**Pattern:**
- First letter of each word capitalized
- No underscores

**Observed in:** All production services.

---

### Folders: snake_case or hyphen-separated

Folder names use `snake_case` (preferred) or hyphen-separated (less common).

**Examples (snake_case):**
- `global_utils/`
- `data_category_field/`
- `point_of_measurement/`
- `services/kafka/producer/`
- `alembic/versions/`

**Examples (hyphen-separated, less common):**
- `my-service/` (repo root)
- `api-backend/` (repo root)

**Pattern:**
- Lowercase
- Words separated by underscores (preferred) or hyphens (repo names, legacy)

**Observed in:** All production services.

---

### Constants and Environment Variables: UPPER_SNAKE_CASE

Configuration keys, environment variables, and constants use `UPPER_SNAKE_CASE`.

**Examples:**
- `POSTGRES_READ_WRITE`
- `KAFKA_BROKER_LIST`
- `TEMPORAL_HOST`
- `MODE`
- `ENV`
- `DEBUG`

**Pattern:**
- All uppercase
- Words separated by underscores

**Observed in:** `config/docker_config.py`, `config/default.yaml`, Dockerfiles.

---

## Folder Layout Conventions

### Top-Level Structure

**Standard layout:**

```
repo-root/
  app/ or src/              # Application code
  config/                   # Configuration (docker_config.py, logging.py, default.yaml)
  services/                 # Infrastructure integrations (kafka/, temporal/, gcs/, bigquery/)
  global_utils/ or core/    # Shared utilities (metaclasses.py, exceptions.py, http.py)
  alembic/ or migrations/   # Database migrations
  tests/                    # Test suite
  entrypoint.py             # Multi-mode entrypoint (server/consumer/worker/cron)
  Dockerfile
  pyproject.toml or requirements.txt
  .env.example
  README.md
```

**Variants:**
- Some services use `app/` and `apps/` (apps for additional workers like `orchestrator`, `signal_forwarder`)
- Some services use `src/`
- Some services use top-level domain folders directly

**Observed in:** Multiple production services.

---

### Per-Domain Module Organization

**Pattern:** One folder per domain/feature, containing all layers (router, service, dao, models).

**Structure:**
```
src/ or app/
  supplier/
    __init__.py
    router.py       # FastAPI router with endpoints
    service.py      # Business logic
    dao.py          # Data access layer (queries, ORM)
    models.py       # Pydantic schemas + SQLAlchemy ORM models
  webhook/
    router.py
    service.py
    models.py
  hsn/
    router.py
    service.py
    dao.py
    models.py
```

**Benefits:**
- High cohesion: all code for a domain in one place
- Easy to locate files (no hunting across `routers/`, `services/`, `daos/` directories)
- Easy to delete or move a domain (just delete/move the folder)

**Observed in:** Production services (e.g., `src/supplier/`, `src/webhook/`, `app/v1/common/`, `app/v1/file_operations/`).

---

### API Versioning

**Pattern:** Use path prefixes like `/v1.0` or `/v2` to version APIs.

**Implementation:**
- Create an APIRouter with `prefix="/v1.0"` and include all v1 routers inside it.
- Or create `api/v1/router.py` and `api/v2/router.py` that aggregate domain routers.

**Example:**
```python
# src/routers.py
api_router_v1_prefix = APIRouter(prefix="/v1.0")
api_router_v1_prefix.include_router(supplier_router, prefix="/supplier", tags=["supplier"])
api_router_v1_prefix.include_router(brand_router, prefix="/brand", tags=["brand"])
api_router.include_router(api_router_v1_prefix, tags=["api route v1"])
```

**Observed in:** Production services (common patterns: `/v1.0`, `/v1/`, `/v2/`).

---

### Infrastructure Services Folder

**Pattern:** Separate folder for infrastructure integrations (Kafka, Temporal, GCS, BigQuery, etc.).

**Structure:**
```
services/
  kafka/
    producer/
      producer.py
      config.py
    consumer/
      consumer.py
      config.py
  temporal/
    run_workers.py
    config.py
  gcs/
    client.py
  bigquery/
    client.py
```

**Observed in:** Production services.

---

### Global Utilities Folder

**Pattern:** Shared utilities in `global_utils/` or `core/`.

**Common files:**
- `metaclasses.py` (Singleton, other metaclasses)
- `exceptions.py` (custom exception classes)
- `http.py` (async HTTP client wrappers)
- `cache_utils.py` (caching decorators)

**Observed in:** Production services (`global_utils/` or `core/`).

---

### Database Migrations

**Pattern:** `alembic/` or `migrations/` at the repo root.

**Structure:**
```
alembic/
  versions/
    <timestamp>_initial_schema.py
    <timestamp>_add_user_table.py
  env.py
  script.py.mako
alembic.ini
```

**Observed in:** Production services (`alembic/` or `migrations/`).

---

### Tests

**Pattern:** Mirror the application structure in `tests/`.

**Structure:**
```
tests/
  test_supplier/
    test_router.py
    test_service.py
    test_dao.py
  test_webhook/
    test_router.py
```

**Observed in:** Production services (`tests/` — though coverage is minimal across many services).

---

## Summary Table

| Convention | Pattern | Example |
|------------|---------|---------|
| **Files/functions** | snake_case | `connection_handler.py`, `get_session_factory()` |
| **Classes** | PascalCase | `ConnectionManager`, `ResponseData` |
| **Folders** | snake_case (preferred) or hyphen-separated | `global_utils/`, `data_category_field/` |
| **Constants/env vars** | UPPER_SNAKE_CASE | `POSTGRES_READ_WRITE`, `MODE` |
| **Top-level structure** | `app/` or `src/`, `config/`, `services/`, `global_utils/`, `alembic/` | Production services |
| **Per-domain modules** | One folder per feature with router/service/dao/models inside | `src/supplier/`, `src/webhook/` |
| **API versioning** | Path prefix `/v1.0` or `/v2` | `APIRouter(prefix="/v1.0")` |
| **Infrastructure services** | `services/<infra>/` (kafka, temporal, gcs, bigquery) | `services/kafka/producer/` |
| **Global utilities** | `global_utils/` or `core/` | `global_utils/metaclasses.py` |
| **Database migrations** | `alembic/` or `migrations/` at root | `alembic/versions/` |
| **Tests** | `tests/` mirroring app structure | `tests/test_supplier/` |

---

## Anti-Patterns to Avoid

- **Inconsistent casing:** Mixing camelCase and snake_case for files (pick snake_case).
- **Monolithic folders:** Putting all routers in `routers/`, all services in `services/`, etc. (prefer per-domain organization).
- **No versioning:** Changing API responses without versioning (breaking clients); always version APIs.
- **Deep nesting:** More than 3-4 levels of folder nesting (keep it flat and discoverable).
- **Generic names:** Folders named `utils/`, `helpers/`, `common/` that become dumping grounds (be specific about what they contain).
