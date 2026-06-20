---
name: design-patterns-and-conventions
description: Encodes the cross-cutting design patterns, naming conventions, folder layout, testing strategies, troubleshooting diagnostics, and catalogued anti-patterns observed across production Python/FastAPI backend services. Use when architecting new FastAPI services, refactoring code, reviewing structure, investigating technical debt, debugging session leaks or event loop blocks, setting up dependency injection, configuring multi-mode entrypoints (server/consumer/worker), implementing response envelopes, integrating Kafka or Temporal, organizing domain modules, or avoiding known anti-patterns (hardcoded secrets, CORS wildcards, sync clients in async code, unscoped sessions, deprecated lifecycle hooks). Particularly relevant for questions about layered architecture (router/service/dao), singleton patterns (ConnectionManager), CustomRequestRoute, loaded_config, naming standards (snake_case vs PascalCase), folder layout (per-domain modules), testing patterns (mocking, fixtures, TestClient), or troubleshooting common issues (session leaks, blocked event loop, duplicate routes, CORS errors, Kafka/Temporal problems).
---

Enforce consistent design patterns, naming conventions, and architectural decisions across FastAPI backends, derived from real-world production services.

## When to use

- Architecting new FastAPI services or major features
- Reviewing code structure and organization
- Establishing conventions for a new backend module
- Refactoring existing code for consistency
- Investigating or preventing technical debt
- Questions about layered architecture, dependency injection, or configuration management
- Setting up singleton instances, factory patterns, or custom API routes
- Organizing multi-mode entrypoints (server/consumer/worker in one image)
- Evaluating or auditing code for anti-patterns

## Core conventions

### Layered architecture
- **Router/View → Service → Helper → DAO/Repository → Model** is the canonical flow. Router handles HTTP concerns, service contains business logic, DAO/repository owns data access.
- Service layer MAY be thin or absent for pure CRUD operations where the router delegates directly to a DAO.
- Never mix business logic into routers or DAOs; keep separation strict.

### Dependency injection
- Use FastAPI `Depends()` for injecting context (database sessions, configuration, event emitters).
- Example pattern: `async def get_connection_handler_for_app() -> AsyncGenerator[ConnectionHandler, None]` yields a handler, then closes it in `finally`.
- NO dependency injection container; favor function-scoped generators and `Depends`.

### Configuration singleton
- Import a single `loaded_config` instance (a Pydantic `BaseSettings`) everywhere.
- Example: `from config.docker_config import loaded_config` then access `loaded_config.POSTGRES_READ_WRITE`.
- Settings are loaded once at startup; environment variables drive configuration.

### Singleton metaclass
- For truly global, single-instance objects (ConnectionManager, AsyncEventBridge), use a `Singleton` metaclass:
  ```python
  class Singleton(type):
      _instances = {}
      def __call__(cls, *args, **kwargs):
          if cls not in cls._instances:
              cls._instances[cls] = super().__call__(*args, **kwargs)
          return cls._instances[cls]
  ```
- Apply via `class ConnectionManager(metaclass=Singleton)`. Do NOT create duplicate instances elsewhere.

### Factory pattern
- Top-level factory functions: `get_app()` or `create_app()` constructs the FastAPI instance, applies middleware, wires routers, and returns it.
- Separate factory logic from the application object; enables clean testing and multi-mode entrypoints.

### Custom API route for cross-cutting concerns
- Centralize request/response logging, error handling, and envelope wrapping in a custom `APIRoute` class.
- Example: `CustomRequestRoute` inherits `fastapi.routing.APIRoute`, overrides `get_route_handler()`, wraps the original handler with try/except, logs request/response JSON, and returns a uniform `ResponseData` envelope.
- Apply globally: `api_router = APIRouter(route_class=CustomRequestRoute)`.

### Response envelope
- Return a uniform JSON shape from all endpoints: `{"success": bool, "data": Any, "message": str, "errors": list[str]}`.
- Use a Pydantic model `ResponseData` with class methods `.ok(data, message)` and `.error(errors, message)`.
- Custom route handlers catch exceptions and always return this envelope, even on validation errors or 500s.

### Event-driven architecture
- Kafka producer/consumer with **config-driven topic-to-handler maps**. The consumer reads a config mapping topic names to handler functions; no hardcoded dispatch logic.
- Favor async Kafka clients (aiokafka) for async FastAPI services; ensure producer is a singleton and consumer runs in its own process/MODE.

### Workflow orchestration
- Use Temporal for long-running, stateful workflows.
- A reference service includes a **JSON-DAG DSL interpreter** that turns declarative workflow JSON into Temporal execution graphs (config-as-data pattern).
- Workflow definitions are decoupled from business code.

### Multi-mode entrypoint
- One Docker image, many roles: server (FastAPI), consumer (Kafka), worker (Temporal), cron.
- `MODE` environment variable selects the main function in `entrypoint.py`:
  ```python
  if loaded_config.MODE == "server":
      server_main()
  elif loaded_config.MODE == "consumer":
      consumer_main()
  elif loaded_config.MODE == "temporal_worker":
      worker_main()
  ```
- Routers conditionally register based on MODE to reduce attack surface.

### Naming conventions
- **Files and functions:** `snake_case` (e.g., `connection_handler.py`, `get_session_factory()`).
- **Classes:** `PascalCase` (e.g., `ConnectionManager`, `ResponseData`).
- **Folders:** snake_case or hyphen-separated (`global_utils/`, `data_category_field/`).

### Folder layout
- **Per-domain modules:** Organize by domain/feature, not by layer. E.g., `src/supplier/`, `src/webhook/`, each with its own `router.py`, `service.py`, `dao.py`, `models.py`.
- **Top-level structure:**
  - `app/` or `src/` for application code
  - `config/` for settings, logging, uri parsing
  - `services/` for infrastructure integrations (Kafka, Temporal, GCS)
  - `global_utils/` or `core/` for shared utilities (metaclasses, exceptions, HTTP clients)
  - `alembic/` or `migrations/` for DB migrations
- **API versioning:** `v1/`, `v2/` as path prefixes; may group all v1 routers under `api/v1/router.py`.

## Skeleton / example

```python
# app/connection.py
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_scoped_session
from sqlalchemy.orm import sessionmaker
from asyncio import current_task
from global_utils.metaclasses import Singleton
from config.docker_config import loaded_config

class ConnectionManager(metaclass=Singleton):
    def __init__(self):
        self._db_engine, self._db_session_factory = self._setup_db()

    @staticmethod
    def _setup_db():
        db_url = str(loaded_config.POSTGRES_READ_WRITE)
        async_db_url = db_url.replace("postgresql://", "postgresql+asyncpg://")
        engine = create_async_engine(async_db_url, echo=loaded_config.DB_ECHO, pool_pre_ping=True)
        session_factory = async_scoped_session(
            sessionmaker(engine, expire_on_commit=False, class_=AsyncSession),
            scopefunc=current_task,
        )
        return engine, session_factory

    def get_session_factory(self):
        return self._db_session_factory

# app/utils.py
from pydantic import BaseModel, Field
from typing import Any

class ResponseData(BaseModel):
    success: bool = False
    data: Any = None
    message: str = ""
    errors: list[str] = Field(default_factory=list)

    @classmethod
    def ok(cls, data: Any = None, message: str = "Success"):
        return cls(success=True, data=data, message=message)

    @classmethod
    def error(cls, errors: list[str] | None = None, message: str = "Error"):
        return cls(success=False, errors=errors or [], message=message)

# entrypoint.py (multi-mode pattern)
from config.docker_config import loaded_config
from app.main import main as server_main
from services.kafka.consumer.consumer import main as consumer_main
from services.temporal.run_workers import worker_main

if loaded_config.MODE == "server":
    server_main()
elif loaded_config.MODE == "consumer":
    consumer_main()
elif loaded_config.MODE == "temporal_worker":
    worker_main()
```

## Anti-patterns to avoid

See [`references/anti-patterns.md`](references/anti-patterns.md) for the full catalogue. Key examples:

- **Hardcoded secrets** in Dockerfiles or config defaults (use environment variables or secret managers).
- **CORS `allow_origins=["*"]`** in production (restrict to known origins).
- **Sync cloud clients** (BigQuery, GCS) called inside async handlers (blocks the event loop; use async clients or run_in_executor).
- **Copy-pasted DAO/connection code** across services instead of a shared library (extract to a common package).
- **No transaction rollback** or unit-of-work pattern (manual `_commit` scattered; prefer context managers and rollback on exception).
- **Thin/empty service layer** where business logic leaks into routers or DAOs.
- **Mixed Kafka libraries** imported together (aiokafka + confluent-kafka + kafka-python in the same repo; pick one).
- **Duplicate router registration** (same router included twice; audit `include_router` calls).
- **Deprecated FastAPI lifecycle hooks** (`@app.on_event("startup")` instead of `lifespan`; migrate to lifespan context managers).
- **Unscoped sessionmaker** (global session without scoping; risk of session leaks in concurrent async; use `async_scoped_session` with `current_task`).

## Decision tree: Which pattern to use?

**Starting a new FastAPI service?**
1. Use the **factory pattern** (`get_app()` or `create_app()`) to construct the FastAPI instance.
2. Apply the **configuration singleton** (`loaded_config` from Pydantic BaseSettings).
3. Set up the **Singleton ConnectionManager** with `async_scoped_session(scopefunc=current_task)`.
4. Create a **Depends generator** (`get_connection_handler_for_app`) for database sessions.
5. Apply **CustomRequestRoute** globally to centralize logging, error handling, and response envelope wrapping.
6. Return **ResponseData** envelopes from all endpoints (`.ok()` for success, `.error()` for errors).

**Organizing code by feature/domain?**
- Use **per-domain modules**: one folder per feature with `router.py`, `service.py`, `dao.py`, `models.py` inside.
- Follow the **layered architecture**: Router → Service → DAO → Model.
- Never mix business logic into routers or DAOs; keep the separation strict.

**Need to run multiple roles (server/consumer/worker) from one image?**
- Use the **multi-mode entrypoint** pattern: branch on `loaded_config.MODE` in `entrypoint.py`.
- Conditionally register routers based on MODE to reduce attack surface.

**Integrating Kafka for event-driven messaging?**
- Use the **event-driven architecture** pattern: async producer (singleton), config-driven consumer (topic-to-handler map).
- Prefer `aiokafka` for async FastAPI services; avoid mixing Kafka libraries.

**Orchestrating long-running workflows?**
- Use **Temporal** for durable, stateful workflows.
- Consider a JSON-DAG DSL interpreter for config-driven workflows.

**Need a globally shared resource (connection pool, event bus)?**
- Use the **Singleton metaclass** pattern for truly global, single-instance objects.

**Common pitfalls to avoid:**
- See the [anti-patterns catalogue](references/anti-patterns.md) for hardcoded secrets, CORS wildcards, sync clients in async code, copy-pasted DAOs, missing rollback, and more.
- See the [troubleshooting guide](references/troubleshooting.md) for diagnosing session leaks, blocked event loops, duplicate routes, and other issues.

## References

- [repo-evidence.md](references/repo-evidence.md) — real file paths and short snippets from each source repo
- [patterns-catalog.md](references/patterns-catalog.md) — detailed pattern inventory with intent and examples
- [naming-and-layout.md](references/naming-and-layout.md) — naming and folder conventions
- [anti-patterns.md](references/anti-patterns.md) — full anti-pattern catalogue with fixes
- [testing-patterns.md](references/testing-patterns.md) — testing strategies for layered architecture, DI, multi-mode entrypoints, and Kafka/Temporal integration
- [troubleshooting.md](references/troubleshooting.md) — common issues and diagnostics (session leaks, blocked event loops, CORS errors, Kafka/Temporal problems)
