# Lifecycle and Gather Patterns

Patterns for managing async service lifecycle (startup/shutdown) and running concurrent tasks.

## FastAPI lifespan pattern

**Purpose:** Initialize connections (database, Kafka, external clients) on startup, close them on shutdown.

**Pattern:**

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI
from app.connection import ConnectionManager

def _init_connections() -> None:
    """Initialize ConnectionManagers for multiple databases."""
    ConnectionManager()  # Singleton pattern; __init__ sets up engine + session factory

async def _close_connections() -> None:
    """Close all registered ConnectionManagers."""
    await ConnectionManager().close_connections()

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifespan context manager for managing startup and shutdown events.
    
    :param app: the FastAPI application.
    """
    _init_connections()
    yield
    await _close_connections()

# In application.py:
app = FastAPI(
    title="My Service",
    lifespan=lifespan,  # Pass the context manager
    # ...
)
```

**Key points:**

- Use `@asynccontextmanager` from `contextlib`.
- Code before `yield` runs on startup; code after `yield` runs on shutdown.
- Pass `lifespan=lifespan` to `FastAPI()`.
- Do NOT use deprecated `@app.on_event("startup")` / `@app.on_event("shutdown")` decorators.

**ConnectionManager pattern:**

```python
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from asyncio import current_task

class ConnectionManager:
    _db_engine: AsyncEngine
    _db_session_factory: Callable[..., AsyncSession]

    def __init__(self) -> None:
        self._db_engine, self._db_session_factory = self._setup_db()

    @staticmethod
    def _setup_db():
        async_db_url = "postgresql+asyncpg://user:pass@host/db"
        engine = create_async_engine(async_db_url, echo=False, pool_pre_ping=True)
        session_factory = async_scoped_session(
            sessionmaker(engine, expire_on_commit=False, class_=AsyncSession),
            scopefunc=current_task
        )
        return engine, session_factory

    async def close_connections(self) -> None:
        await self._db_engine.dispose()
```

## asyncio.gather for concurrency

**Purpose:** Run multiple workers, consumers, or health tasks concurrently and wait for all to complete (or fail).

**Pattern (Temporal workers):**

```python
import asyncio
import signal

async def worker_main():
    await on_startup()

    # Health endpoints
    health_task = asyncio.create_task(_healthz())
    ready_task = asyncio.create_task(_readyz())

    # Temporal workers
    client = await initialize_client()
    worker_tasks = await get_worker_tasks(client)  # Returns [(worker_obj, task), ...]

    # Combine all tasks
    worker_tasks.extend([(None, health_task), (None, ready_task)])

    # ... setup signal handlers (see below) ...

    # Run all tasks concurrently
    try:
        await asyncio.gather(
            *[task for _, task in worker_tasks],
            return_exceptions=True
        )
    except asyncio.CancelledError:
        logger.info("All tasks shutdown gracefully")

    await on_shutdown()
```

**Key points:**

- Use `asyncio.gather(*tasks, return_exceptions=True)` to run tasks concurrently.
- `return_exceptions=True` prevents gather from raising on the first exception; instead, exceptions are returned in the result list.
- Without `return_exceptions=True`, an exception in one task cancels all others immediately (often not what you want for workers).

**No TaskGroup usage observed in repos.** `asyncio.gather` is the universal pattern.

## Graceful shutdown with signal handlers

**Purpose:** Handle SIGTERM (from Kubernetes) or SIGINT (Ctrl+C) to shut down workers cleanly.

**Pattern:**

```python
import asyncio
import signal

async def worker_main():
    # ... create worker_tasks as above ...

    async def async_shutdown():
        # Shutdown each worker and cancel related tasks
        for worker_obj, worker_task in worker_tasks:
            if worker_obj:
                await worker_obj.shutdown()  # Temporal worker graceful shutdown
            worker_task.cancel()

        # Wait for all tasks to exit
        try:
            await asyncio.gather(
                *[task for _, task in worker_tasks],
                return_exceptions=True
            )
        except asyncio.CancelledError:
            logger.info("Tasks cancelled")

    # Synchronous wrapper to schedule the asynchronous shutdown
    def on_signal_received(*args, **kwargs):
        asyncio.create_task(async_shutdown())

    # Register signal handlers
    loop = asyncio.get_running_loop()
    loop.add_signal_handler(signal.SIGTERM, on_signal_received, None)
    loop.add_signal_handler(signal.SIGINT, on_signal_received, None)

    # Run tasks
    try:
        await asyncio.gather(
            *[task for _, task in worker_tasks],
            return_exceptions=True
        )
    except asyncio.CancelledError:
        logger.info("All tasks shutdown gracefully")

    await on_shutdown()
```

**Key points:**

- `loop.add_signal_handler` registers a **synchronous** callback (runs in the main thread).
- The callback must not be async; instead, it schedules an async task via `asyncio.create_task(async_shutdown())`.
- `async_shutdown` calls `worker.shutdown()` (graceful) then `task.cancel()` (forceful after timeout).
- `await asyncio.gather(..., return_exceptions=True)` waits for all tasks to exit, even if they raise `CancelledError`.
- **Signal handlers only work on Unix** (Linux, macOS). On Windows, use `signal.signal(signal.SIGBREAK, ...)` or rely on process manager (pm2, supervisord).

**Shutdown flow:**

1. SIGTERM/SIGINT received → `on_signal_received()` called.
2. `async_shutdown()` scheduled as a task.
3. Each worker's `.shutdown()` called (tells it to stop accepting new work, finish current work).
4. All tasks cancelled (`.cancel()`).
5. `gather(..., return_exceptions=True)` waits for cancellation to propagate.
6. `on_shutdown()` called (close DB connections, Kafka producers, etc.).

## Async HTTP client patterns

### Lightweight wrapper (AsyncHTTPClient pattern)

**Purpose:** Reusable aiohttp session with retries and logging.

```python
import aiohttp
from typing import Optional, Literal

class AsyncHTTPClient:
    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None

    async def close(self) -> None:
        if self.session:
            await self.session.close()
            self.session = None

    async def fetch(
        self,
        method: str,
        url: str,
        retries: int = 1,
        delay: float = 0.5,
        payload: Optional[dict] = None,
        headers: Optional[dict] = None,
        content_type: Literal["str", "bytes"] | None = None,
        **kwargs
    ):
        if not self.session:
            self.session = aiohttp.ClientSession()

        for attempt in range(retries):
            try:
                async with self.session.request(method, url, json=payload, headers=headers, **kwargs) as response:
                    if content_type == "bytes":
                        result = await response.content.read()
                    elif content_type == "str":
                        result = await response.text()
                    else:
                        result = await response.json()

                    # Log and return
                    return {
                        "success": 200 <= response.status < 300,
                        "status": response.status,
                        "response": result,
                        # ...
                    }
            except Exception as e:
                if attempt == retries - 1:
                    return {
                        "success": False,
                        "error": str(e),
                        "status": 500,
                    }
                await asyncio.sleep(delay)
```

**Usage:**

```python
client = AsyncHTTPClient()
try:
    result = await client.fetch("GET", "https://api.example.com/data", retries=3)
    if result["success"]:
        return result["response"]
finally:
    await client.close()
```

### Async request library pattern

**Purpose:** Protocol-agnostic async request library with circuit breaker, retry, and pydantic models.

```python
from async_requests import request
from async_requests.models import ProtocolInfo, CircuitBreakerConfig, RetryConfig

protocol_info = ProtocolInfo(
    request_type="GET",
    timeout=30,
    headers={"Authorization": "Bearer <REDACTED>"},
    circuit_breaker_config=CircuitBreakerConfig(
        maximum_failures=5,
        timeout=60,
        retry_config=RetryConfig(
            name="my-retry",
            allowed_retries=3,
            delay=1,
            jitter=True
        )
    )
)

response = await request(
    url="https://api.example.com/data",
    protocol="HTTP",
    protocol_info=protocol_info
)

if response.error_message:
    logger.error(f"Request failed: {response.error_message}")
else:
    data = response.payload
```

**Features:**

- **Protocol plugins:** HTTP, FTP, SFTP (registered in `logic.protocol_mapping`).
- **Circuit breaker:** Tracks failures, opens circuit after threshold, retries with backoff.
- **Pre/post processors:** Custom transformation functions.
- **Pydantic models:** Type-safe request/response.

**When to use:**

- **AsyncHTTPClient:** Simple HTTP requests with retries, minimal dependencies.
- **Async request library:** Multi-protocol support, circuit breaker, or when you need advanced features like failsafe integration.
- **Raw aiohttp:** Full control over session, connection pooling, timeouts.

## Health check tasks

**Pattern:**

```python
async def _healthz(consumer_state: dict = None):
    """Liveness probe: is the process running?"""
    from aiohttp import web
    app = web.Application()
    app.router.add_get("/healthz", lambda _: web.Response(text="OK"))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", 8080)
    await site.start()
    # Run forever (cancelled on shutdown)
    await asyncio.Event().wait()

async def _readyz():
    """Readiness probe: is the service ready to accept traffic?"""
    # Similar pattern, separate port or endpoint
```

**Run with gather:**

```python
await asyncio.gather(
    main_worker(),
    _healthz(),
    _readyz(),
    return_exceptions=True
)
```
