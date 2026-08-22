# Example Patterns from Production Services

Representative code examples demonstrating the design patterns and conventions encoded in this skill.

---

## Example: Response Envelope Pattern

**Key concepts:**
- `app/utils.py` — ResponseData envelope

**What to adopt:** The `ResponseData` response envelope pattern with `.ok()` and `.error()` class methods; use this for uniform API responses across all endpoints.

### Snippet: ResponseData envelope

```python
# app/utils.py
from pydantic import BaseModel, Field
from typing import Any

class ResponseData(BaseModel):
    """Uniform response wrapper for all API responses."""
    success: bool = False
    data: Any = None
    message: str = ""
    errors: list[str] = Field(default_factory=list)

    @classmethod
    def ok(cls, data: Any = None, message: str = "Success") -> "ResponseData":
        return cls(success=True, data=data, message=message)

    @classmethod
    def error(cls, errors: list[str] | None = None, message: str = "Error") -> "ResponseData":
        return cls(success=False, errors=errors or [], message=message)
```

---

## Example: Comprehensive FastAPI Service Patterns

**Key concepts:**
- `app/connection.py` — Singleton ConnectionManager, async_scoped_session, get_connection_handler_for_app Depends pattern
- `app/routing.py` — CustomRequestRoute for centralized logging/error handling
- `app/router.py` — Multi-mode router registration (MODE-driven include_router)
- `config/docker_config.py` — loaded_config singleton (Pydantic BaseSettings)
- `entrypoint.py` — Multi-mode entrypoint (server/consumer/temporal_worker/cron)

**What to adopt:** The ConnectionManager singleton with async_scoped_session (current_task), CustomRequestRoute wrapping all endpoints, loaded_config pattern, and multi-mode entrypoint branching on MODE.

### Snippet: Singleton ConnectionManager with async_scoped_session

```python
# app/connection.py
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_scoped_session, AsyncEngine
from sqlalchemy.orm import sessionmaker
from asyncio import current_task
from global_utils.metaclasses import Singleton
from config.docker_config import loaded_config

class ConnectionManager(metaclass=Singleton):
    _db_engine: AsyncEngine
    _db_session_factory: Callable[..., AsyncSession]

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

class ConnectionHandler:
    def __init__(self):
        self._session = None
        self._connection_manager = ConnectionManager()

    @property
    def session(self) -> AsyncSession:
        if not self._session:
            session_factory = self._connection_manager.get_session_factory()
            self._session = session_factory()
        return self._session

    async def close(self):
        if self._session:
            await self._session.close()

async def get_connection_handler_for_app():
    connection_handler = ConnectionHandler()
    try:
        yield connection_handler
    finally:
        await connection_handler.close()
```

### Snippet: CustomRequestRoute (centralized logging and error handling)

```python
# app/routing.py
import time, orjson
from fastapi import Request, Response
from fastapi.routing import APIRoute
from fastapi.responses import ORJSONResponse
from app.utils import ResponseData
from config.logging import get_logger

logger = get_logger()

class CustomRequestRoute(APIRoute):
    def get_route_handler(self):
        original_route_handler = super().get_route_handler()

        async def custom_route_handler(request: Request) -> Response:
            request_body_bytes = await request.body()
            route_name = request.scope["route"].name
            request_data = {"client_host": request.client, "url": request.url, ...}
            try:
                start_time = time.perf_counter()
                # Parse JSON body, set request.state.user_data if x-user-data header present
                request_data["request_body"] = orjson.loads(request_body_bytes) if request_body_bytes else {}
                response: Response = await original_route_handler(request)
                end_time = time.perf_counter()
                logger.info(f"HTTP request for {route_name}", extra={"request_data": request_data, "response_data": ...})
                return response
            except (RequestValidationError, ValidationError) as exc:
                error_response = ResponseData.model_construct(errors=[...], success=False).dict()
                return ORJSONResponse(content=error_response, status_code=400)
            except Exception as exc:
                error_response = ResponseData.model_construct(errors=[str(exc)], success=False).dict()
                return ORJSONResponse(content=error_response, status_code=500)
        return custom_route_handler
```

### Snippet: Multi-mode entrypoint

```python
# entrypoint.py
from config.docker_config import loaded_config
from app.main import main as server_main
from services.kafka.consumer.consumer import main as consumer_main
from services.temporal.run_workers import worker_main
from app.v1.crons.setup import crons

if loaded_config.MODE == "server":
    server_main()
elif loaded_config.MODE == "consumer":
    consumer_main()
elif loaded_config.MODE == "temporal_worker":
    worker_main()
elif loaded_config.MODE == "cron":
    crons()
```

### Snippet: loaded_config (Pydantic BaseSettings singleton)

```python
# config/docker_config.py
from pydantic_settings import BaseSettings
from config.config_parser import docker_args

class Settings(BaseSettings):
    HOST: str = docker_args.HOST
    ENV: str = docker_args.ENV
    MODE: str = docker_args.MODE
    POSTGRES_READ_WRITE: str = docker_args.POSTGRES_READ_WRITE
    KAFKA_BROKER_LIST: str = docker_args.KAFKA_BROKER_LIST
    TEMPORAL_HOST: str = docker_args.TEMPORAL_HOST
    # ... all config fields ...

loaded_config = Settings()
```

### Snippet: Multi-mode router registration

```python
# app/router.py
from fastapi.routing import APIRouter
from app.routing import CustomRequestRoute
from config.docker_config import loaded_config

api_router = APIRouter(route_class=CustomRequestRoute)

if loaded_config.MODE == "server":
    api_router_prefix.include_router(api_v1_router, tags=["API v1.0"])
if loaded_config.MODE == "webhook_server":
    api_router_prefix.include_router(webhook_router, tags=["Webhook Routes"])
```

---

## Example: Router Aggregation (with anti-patterns to avoid)

**Key concepts:**
- `src/routers.py` — Central router aggregation; **ANTI-PATTERN: duplicate webhook_callback_router registration**; **ANTI-PATTERN: deprecated @api_router.on_event("startup")** instead of lifespan

**What to adopt:** The pattern of aggregating all domain routers in one place; **AVOID: duplicate include_router calls and deprecated lifecycle hooks**.

### Snippet: Duplicate router registration (anti-pattern)

```python
# src/routers.py
api_router_v1_prefix.include_router(external_router, prefix="/external/api", tags=["external"])
api_router_v1_prefix.include_router(webhook_callback_router, prefix="/webhooks", tags=["webhooks-callback"])
api_router_v1_prefix.include_router(
    supplier_router, prefix="/external/supplier", tags=["supplier api"]
)
api_router_v1_prefix.include_router(webhook_callback_router, prefix="/webhooks", tags=["webhooks-callback"])  # <-- DUPLICATE
```

### Snippet: Deprecated on_event lifecycle hook (anti-pattern)

```python
# src/routers.py
@api_router.on_event("startup")  # <-- DEPRECATED; use lifespan context manager instead
def list_routes():
    # ...
```

---

## Example: Singleton Metaclass

**Key concepts:**
- `global_utils/metaclasses.py` — Singleton metaclass

**What to adopt:** The Singleton metaclass for global, single-instance resources (ConnectionManager, AsyncEventBridge).

### Snippet: Singleton metaclass

```python
# global_utils/metaclasses.py
class Singleton(type):
    _instances = {}

    def __call__(cls, *args, **kwargs):
        if cls not in cls._instances:
            cls._instances[cls] = super().__call__(*args, **kwargs)
        return cls._instances[cls]
```

Usage:
```python
class ConnectionManager(metaclass=Singleton):
    def __init__(self):
        # Initialized only once, even if called multiple times
        pass
```

---

## Example: Unscoped Sessionmaker (anti-pattern to avoid)

**Key concepts:**
- `core/connection_manager.py` — **ANTI-PATTERN: unscoped sessionmaker** (no scopefunc, risk of session leaks in async concurrent requests)

**What to adopt:** The general structure of ConnectionManager; **AVOID: unscoped sessionmaker in async contexts**.

### Snippet: Unscoped sessionmaker (anti-pattern)

```python
# core/connection_manager.py
def _setup_db(self):
    async_engine = create_async_engine(str(self.db_url), echo=self.db_echo, pool_size=10, pool_pre_ping=True)
    async_session_factory = sessionmaker(
        async_engine,
        expire_on_commit=False,
        class_=AsyncSession,
    )  # <-- NO scopefunc; concurrent async requests may share sessions unsafely
    return async_engine, async_session_factory
```

**Fix:** Use `async_scoped_session(async_session_factory, scopefunc=current_task)` as shown in the ConnectionManager example above.

---

## Summary table

| Example | Pattern demonstrated | File path | Anti-pattern? |
|---------|----------------------|-----------|---------------|
| Response envelope | ResponseData envelope | `app/utils.py` | No |
| Connection management | Singleton ConnectionManager + async_scoped_session | `app/connection.py` | No |
| Custom routing | CustomRequestRoute | `app/routing.py` | No |
| Configuration | loaded_config singleton | `config/docker_config.py` | No |
| Multi-mode deployment | Multi-mode entrypoint | `entrypoint.py` | No |
| Conditional routing | Multi-mode router registration | `app/router.py` | No |
| Singleton pattern | Singleton metaclass | `global_utils/metaclasses.py` | No |
| Router aggregation | Duplicate router registration | `src/routers.py` | **Yes** |
| Lifecycle hooks | Deprecated on_event | `src/routers.py` | **Yes** |
| Session management | Unscoped sessionmaker | `core/connection_manager.py` | **Yes** |
