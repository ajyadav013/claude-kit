# Design Patterns Catalog

Detailed inventory of the design patterns used across production Python/FastAPI services, with intent, benefits, and real examples.

---

## 1. Layered Architecture

**Intent:** Separate concerns into distinct layers—routing, business logic, data access, and models—to improve maintainability, testability, and clarity.

**Structure:**
- **Router/View:** HTTP request/response handling, path parameters, query parameters, request validation
- **Service:** Business logic, orchestration, cross-cutting concerns (authorization, validation beyond schema)
- **Helper:** Utilities and helpers for common operations within a domain
- **DAO/Repository:** Data access layer; encapsulates SQL queries, ORM operations, and external data sources
- **Model:** Pydantic models (request/response schemas) and SQLAlchemy ORM models (database entities)

**Example:**
- `app/v1/common/router.py` → service layer → DAO
- `src/supplier/router.py` → `src/supplier/service.py` → `src/supplier/dao.py` → `src/supplier/models.py`

**Notes:**
- Service layer MAY be thin or absent for pure CRUD; router can delegate directly to DAO in simple cases.
- NEVER mix business logic into routers (they should only validate/transform HTTP) or into DAOs (they should only query/mutate data).

---

## 2. Dependency Injection (FastAPI Depends)

**Intent:** Provide request-scoped dependencies (database sessions, configuration, event emitters) to route handlers without globals or tight coupling.

**Pattern:**
- Define async generator functions that `yield` the dependency, then clean up in `finally`.
- Use `Depends()` in route signatures: `async def endpoint(handler: ConnectionHandler = Depends(get_connection_handler_for_app))`.

**Example:**
```python
# app/connection.py
async def get_connection_handler_for_app() -> AsyncGenerator[ConnectionHandler, None]:
    connection_handler = ConnectionHandler()
    try:
        yield connection_handler
    finally:
        await connection_handler.close()

# Usage in router:
@router.post("/example")
async def create_example(data: ExampleCreate, handler: ConnectionHandler = Depends(get_connection_handler_for_app)):
    session = handler.session
    # ... use session ...
```

**Benefits:**
- Automatic cleanup (session close, transaction rollback on exception if wrapped)
- Request-scoped isolation (each request gets its own session)
- Easy testing (mock the Depends)

**Alternatives NOT used:**
- No DI container (no `dependency-injector`, `injector`, or similar libraries)
- No global session objects

---

## 3. Configuration Singleton (Pydantic BaseSettings)

**Intent:** Centralize all configuration in one place; load from environment variables once at startup; import a single `loaded_config` instance everywhere.

**Pattern:**
- Create `config/docker_config.py` with a Pydantic `BaseSettings` class.
- Instantiate once: `loaded_config = Settings()`.
- Import `loaded_config` everywhere: `from config.docker_config import loaded_config`.

**Example:**
```python
# config/docker_config.py
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    ENV: str
    MODE: str
    POSTGRES_READ_WRITE: str
    KAFKA_BROKER_LIST: str
    TEMPORAL_HOST: str
    # ... all config fields ...

loaded_config = Settings()
```

**Benefits:**
- Type-safe configuration with validation
- Single source of truth
- Easy to override via environment variables (12-factor app)

**Anti-pattern:** Hardcoding secrets or default sensitive values in the Settings class.

---

## 4. Singleton Metaclass

**Intent:** Ensure exactly one instance of a class exists globally (for ConnectionManager, event bridge, or other shared resources).

**Pattern:**
- Define a `Singleton` metaclass in `global_utils/metaclasses.py`.
- Apply via `class MyClass(metaclass=Singleton)`.

**Example:**
```python
# global_utils/metaclasses.py
class Singleton(type):
    _instances = {}
    def __call__(cls, *args, **kwargs):
        if cls not in cls._instances:
            cls._instances[cls] = super().__call__(*args, **kwargs)
        return cls._instances[cls]

# Usage:
class ConnectionManager(metaclass=Singleton):
    def __init__(self):
        # Initialized only once
        self._db_engine, self._session_factory = self._setup_db()
```

**Benefits:**
- Global state for truly shared resources (DB connection pool, event bus)
- Lazy initialization on first access

**Anti-pattern:** Overusing singletons; prefer dependency injection for testability where possible.

---

## 5. Factory Pattern (Application Factory)

**Intent:** Decouple application construction from its use; enable multiple instances (for testing, multi-mode entrypoints) and cleaner configuration.

**Pattern:**
- Define `get_app()` or `create_app()` function that builds and configures the FastAPI instance.
- Apply middleware, register routers, set up lifespan context, and return the app.

**Example:**
```python
# app/main.py
def get_app() -> FastAPI:
    app = FastAPI(title="My API")
    app.add_middleware(CORSMiddleware, allow_origins=[...])
    app.include_router(api_router)
    return app
```

**Benefits:**
- Easy to test (instantiate a fresh app per test)
- Supports multiple modes (one factory for server, one for worker, etc.)
- Cleaner separation of app creation from app execution

---

## 6. Custom APIRoute (Cross-Cutting Concerns)

**Intent:** Centralize request/response logging, error handling, and response envelope wrapping in one place instead of repeating try/except in every route.

**Pattern:**
- Subclass `fastapi.routing.APIRoute`.
- Override `get_route_handler()` to wrap the original handler with logging, error handling, and envelope construction.
- Apply globally: `api_router = APIRouter(route_class=CustomRequestRoute)`.

**Example:**
```python
# app/routing.py
from fastapi.routing import APIRoute
from fastapi import Request, Response
from fastapi.responses import ORJSONResponse
import time, orjson
from app.utils import ResponseData

class CustomRequestRoute(APIRoute):
    def get_route_handler(self):
        original_route_handler = super().get_route_handler()
        async def custom_route_handler(request: Request) -> Response:
            request_body = await request.body()
            route_name = request.scope["route"].name
            try:
                start_time = time.perf_counter()
                response = await original_route_handler(request)
                duration = time.perf_counter() - start_time
                logger.info(f"HTTP request for {route_name}", extra={"duration": duration, ...})
                return response
            except Exception as exc:
                error_response = ResponseData.error(errors=[str(exc)]).dict()
                return ORJSONResponse(content=error_response, status_code=500)
        return custom_route_handler
```

**Benefits:**
- DRY: no per-route try/except boilerplate
- Consistent logging and error responses
- Easy to add request tracing, metrics, or authentication checks

---

## 7. Response Envelope (Uniform JSON Shape)

**Intent:** Return a consistent JSON structure from all endpoints to simplify client-side error handling and success detection.

**Pattern:**
- Define a `ResponseData` Pydantic model with fields: `success`, `data`, `message`, `errors`.
- Provide class methods `.ok(data, message)` and `.error(errors, message)`.
- Return `ResponseData` instances from all endpoints (or have CustomRequestRoute wrap raw responses).

**Example:**
```python
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

# Usage in router:
@router.post("/create")
async def create_item(item: ItemCreate):
    # ... business logic ...
    return ResponseData.ok(data=created_item, message="Item created successfully")
```

**Benefits:**
- Predictable client-side parsing
- Easier error handling (check `success` field)
- Consistent UX

---

## 8. Event-Driven Architecture (Kafka)

**Intent:** Decouple services via asynchronous messaging; publish events to Kafka topics, consume them in separate processes.

**Pattern:**
- **Producer:** Singleton `AsyncEventEmitterWrapper` or similar; sends events to Kafka topics.
- **Consumer:** Config-driven topic-to-handler map; consumer reads config, subscribes to topics, dispatches messages to registered handlers.
- Use async Kafka clients (aiokafka) in async FastAPI services.

**Example:**
- `services/kafka/producer/producer.py` (AsyncEventEmitterWrapper)
- `services/kafka/consumer/consumer.py` (reads topic-to-handler map from config, dispatches messages)

**Benefits:**
- Loose coupling
- Horizontal scaling (multiple consumer instances)
- Replay/audit trail

**Anti-pattern:** Mixing Kafka libraries (aiokafka + confluent-kafka + kafka-python in the same repo; pick one).

---

## 9. Workflow Orchestration (Temporal)

**Intent:** Model long-running, stateful business processes as durable workflows; handle retries, timeouts, and state persistence automatically.

**Pattern:**
- Define Temporal workflows and activities.
- A reference service includes a **JSON-DAG DSL interpreter** that converts declarative workflow JSON into Temporal execution graphs (config-as-data).

**Example:**
- `services/temporal/run_workers.py` (worker registration)
- Workflow DSL: JSON files define node types (task, decision, parallel) and edges; the interpreter builds Temporal workflows from these.

**Benefits:**
- Durable execution (survives process restarts)
- Retry/timeout logic built-in
- Config-driven workflows (non-developers can modify workflow JSON)

---

## 10. Multi-Mode Entrypoint

**Intent:** Deploy one Docker image that can run as server, consumer, worker, or cron job; select role via environment variable.

**Pattern:**
- Single `entrypoint.py` checks `loaded_config.MODE` and calls the appropriate `main()` function.
- Routers may conditionally register based on MODE to reduce attack surface.

**Example:**
```python
# entrypoint.py
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

**Benefits:**
- Single image to build, version, and deploy
- Consistent configuration across roles
- Easier orchestration (one Helm chart with multiple Deployments)

---

## 11. Naming Conventions

**Intent:** Consistent, readable code; reduce cognitive load when navigating the codebase.

**Rules:**
- **Files and functions:** `snake_case` (e.g., `connection_handler.py`, `get_session_factory()`)
- **Classes:** `PascalCase` (e.g., `ConnectionManager`, `ResponseData`)
- **Folders:** `snake_case` or hyphen-separated (`global_utils/`, `data_category_field/`)

**Observed across all production services.**

---

## 12. Folder Layout (Per-Domain Modules)

**Intent:** Organize code by domain/feature, not by layer; make it easy to find all code related to a single feature.

**Structure:**
```
src/ or app/
  supplier/
    router.py
    service.py
    dao.py
    models.py
  webhook/
    router.py
    service.py
    models.py
  ...
config/
  docker_config.py
  logging.py
services/
  kafka/
    producer/
    consumer/
  temporal/
  gcs/
global_utils/ or core/
  metaclasses.py
  exceptions.py
  http.py
alembic/ or migrations/
```

**Versioning:** API path prefixes like `/v1.0` or `/v2`; may group all v1 routers in `api/v1/router.py`.

**Example:**
- `app/v1/common/`, `app/v1/file_operations/`, `services/kafka/`, `services/temporal/`, `config/`, `global_utils/`
- `src/supplier/`, `src/webhook/`, `src/hsn/`, etc.

**Benefits:**
- High cohesion (all supplier code in one place)
- Easy to navigate (find router, service, DAO, models for a domain in one directory)
- Scalable (add new domains without polluting top-level structure)

---

## Summary Table

| Pattern | Intent | Observed In | Example file |
|---------|--------|-------------|--------------|
| Layered Architecture | Separate HTTP, business logic, data access | Production services | `src/supplier/router.py` → `service.py` → `dao.py` |
| Dependency Injection | Request-scoped resources via Depends | Production services | `app/connection.py` (get_connection_handler_for_app) |
| Configuration Singleton | Centralized, type-safe config | Production services | `config/docker_config.py` (loaded_config) |
| Singleton Metaclass | Global single-instance resources | Production services | `global_utils/metaclasses.py` (Singleton) |
| Factory Pattern | Decouple app creation from execution | Production services | `app/main.py` (get_app) |
| Custom APIRoute | Centralized logging, error handling, envelope | Production services | `app/routing.py` (CustomRequestRoute) |
| Response Envelope | Uniform JSON success/error shape | Production services | `app/utils.py` (ResponseData) |
| Event-Driven (Kafka) | Async messaging, decoupled services | Production services | `services/kafka/producer/`, `services/kafka/consumer/` |
| Workflow Orchestration | Durable long-running processes | Production services | `services/temporal/`, JSON-DAG DSL |
| Multi-Mode Entrypoint | One image, multiple roles (server/consumer/worker) | Production services | `entrypoint.py` (MODE branching) |
| Naming Conventions | Consistent naming (snake_case, PascalCase) | Production services | — |
| Folder Layout | Per-domain organization | Production services | `src/<domain>/` or `app/<domain>/` |
