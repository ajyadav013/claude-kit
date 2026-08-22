---
name: async-python-patterns
description: Async Python for high-performance services. Use when implementing FastAPI/Temporal/Kafka async handlers, AsyncSession database access, asyncio.gather concurrency, or diagnosing event loop blocking.
---

Async programming patterns for high-performance Python services.

## When to use

- Implementing async FastAPI handlers, Temporal activities, or Kafka message processors
- Setting up database access with AsyncSession (SQLAlchemy 2.0 + asyncpg)
- Running multiple workers, consumers, or health tasks concurrently with asyncio.gather
- Bridging sync and async code (blocking Kafka consumer dispatching async handlers, or calling sync cloud clients from async activities)
- Diagnosing event loop blocking or performance issues (the sync-in-async trap)
- Implementing graceful shutdown for workers with SIGTERM/SIGINT handlers
- Choosing or implementing an async HTTP client wrapper

## Core conventions

1. **Fully async stack:** Use `async def` handlers, `AsyncSession` over asyncpg, aiokafka for producers/consumers (when SASL_SSL+GSSAPI Kerberos is not required), aiohttp for HTTP clients. For Kerberos auth, use kafka-python with the sync→async bridge pattern.
2. **Lifespan for FastAPI apps:** Use `@asynccontextmanager async def lifespan(app)` to initialize connections on startup and close them on shutdown; pass `lifespan=lifespan` to `FastAPI()`.
3. **AsyncSession setup:** Create async engine with `create_async_engine(url.replace("postgresql://", "postgresql+asyncpg://"), pool_pre_ping=True, ...)`, use `async_scoped_session(sessionmaker(..., expire_on_commit=False, class_=AsyncSession), scopefunc=current_task)` for task-local sessions. The `current_task` scope ensures each asyncio task gets its own session.
4. **asyncio.gather for concurrency:** Run multiple Temporal workers, Kafka consumers, or health tasks together with `await asyncio.gather(*tasks, return_exceptions=True)`. No TaskGroup observed.
5. **Sync-in-async BRIDGE pattern (Kafka consumer):** When a blocking library (kafka-python) must dispatch async handlers, run the sync consumer in a thread via `asyncio.to_thread(_run_kafka_consumer, loop, state)` and dispatch coroutines back to the event loop with `asyncio.run_coroutine_threadsafe(coro, loop).result()`.
6. **AVOID the sync-in-async TRAP:** NEVER call sync cloud clients (google-cloud-bigquery, google-cloud-storage) directly from async code without wrapping in `asyncio.to_thread(...)` or `loop.run_in_executor(None, ...)`. They block the event loop. Use async clients (gcloud-aio-storage) or offload to a thread.
7. **Graceful worker shutdown:** Use `loop.add_signal_handler(signal.SIGTERM, on_signal_received)` to trigger `await worker.shutdown()` then `await asyncio.gather(*worker_tasks, return_exceptions=True)`.
8. **Async HTTP clients:** Prefer lightweight wrappers over aiohttp (e.g., AsyncHTTPClient pattern) or an async request library with unified protocol interface, circuit breaker, retry, and pydantic models.
9. **uvloop for performance (optional):** Some services add uvloop as a dependency; it's not universal but improves event loop throughput.

## Skeleton / example

```python
# FastAPI lifespan pattern
from contextlib import asynccontextmanager
from fastapi import FastAPI

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    ConnectionManager()  # init DB pools
    yield
    # Shutdown
    await ConnectionManager().close_connections()

app = FastAPI(lifespan=lifespan)

# AsyncSession setup
from sqlalchemy.ext.asyncio import create_async_engine, async_scoped_session, AsyncSession
from sqlalchemy.orm import sessionmaker
from asyncio import current_task

engine = create_async_engine(
    "postgresql+asyncpg://user:pass@host/db",
    echo=False,
    pool_pre_ping=True
)
session_factory = async_scoped_session(
    sessionmaker(engine, expire_on_commit=False, class_=AsyncSession),
    scopefunc=current_task
)

# Worker concurrency with graceful shutdown
import asyncio
import signal

async def worker_main():
    client = await initialize_client()
    worker_tasks = await get_worker_tasks(client)
    health_task = asyncio.create_task(_healthz())
    worker_tasks.append((None, health_task))

    async def async_shutdown():
        for worker_obj, task in worker_tasks:
            if worker_obj:
                await worker_obj.shutdown()
            task.cancel()
        await asyncio.gather(*[t for _, t in worker_tasks], return_exceptions=True)

    def on_signal_received(*args):
        asyncio.create_task(async_shutdown())

    loop = asyncio.get_running_loop()
    loop.add_signal_handler(signal.SIGTERM, on_signal_received)
    loop.add_signal_handler(signal.SIGINT, on_signal_received)

    await asyncio.gather(*[t for _, t in worker_tasks], return_exceptions=True)

# Sync-in-async bridge for blocking consumer
from kafka import KafkaConsumer as SyncKafkaConsumer

def _run_kafka_consumer(loop: asyncio.AbstractEventLoop, state: dict):
    consumer = SyncKafkaConsumer(...)
    for msg in consumer:
        coro = process_message_async(msg)
        future = asyncio.run_coroutine_threadsafe(coro, loop)
        future.result()  # block thread until handler completes

async def main():
    loop = asyncio.get_running_loop()
    await asyncio.gather(
        asyncio.to_thread(_run_kafka_consumer, loop, {}),
        _healthz()
    )

# WRONG: sync client blocking event loop (anti-pattern)
from google.cloud import bigquery

async def temporal_activity():
    client = bigquery.Client(project="my-project")  # BLOCKS
    job = client.query("SELECT ...")  # BLOCKS
    return [dict(row) for row in job.result()]  # BLOCKS

# RIGHT: offload to thread
async def temporal_activity():
    client = bigquery.Client(project="my-project")
    def _query():
        job = client.query("SELECT ...")
        return [dict(row) for row in job.result()]
    return await asyncio.to_thread(_query)

# OR use async client (gcloud-aio-storage pattern)
from gcloud.aio.storage import Storage

async def temporal_activity():
    async with Storage() as client:
        blob = await client.download("bucket", "key")
        return blob

# Async HTTP client pattern
import aiohttp

class AsyncHTTPClient:
    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None

    async def close(self):
        if self.session:
            await self.session.close()

    async def fetch(self, method: str, url: str, retries: int = 1, **kwargs):
        if not self.session:
            self.session = aiohttp.ClientSession()
        for attempt in range(retries):
            try:
                async with self.session.request(method, url, **kwargs) as resp:
                    return await resp.json()
            except Exception as e:
                if attempt == retries - 1:
                    raise
                await asyncio.sleep(0.5)
```

## Anti-patterns to avoid

1. **Calling sync cloud clients from async code without offloading:** `bigquery.Client().query(...)` or `storage.Client().get_bucket(...)` directly in an async function blocks the event loop. Wrap in `asyncio.to_thread(...)` or use async clients.
2. **Creating a new event loop per handler in a threaded context:** Use `asyncio.run_coroutine_threadsafe(coro, loop)` to dispatch onto the existing loop, not `asyncio.run(coro)` which spawns a second loop.
3. **Ignoring signal handlers in workers:** Workers without SIGTERM/SIGINT handlers will be killed mid-flight. Always call `worker.shutdown()` and await pending tasks with `return_exceptions=True`.
4. **Not using `return_exceptions=True` in gather:** Omitting this causes gather to raise on the first exception, leaving other tasks dangling. Always use it for concurrent worker/health tasks.
5. **Mixing sync and async session factories:** Don't use `sessionmaker(..., class_=Session)` in async code. Always `class_=AsyncSession` and `create_async_engine` with the `postgresql+asyncpg://` driver.
6. **Using kafka-python when aiokafka is available:** The blocking kafka-python consumer requires the complex sync→async bridge pattern. Prefer aiokafka (fully async) unless you need GSSAPI/Kerberos auth (not yet supported by aiokafka as of 0.7.x).

## References

- [repo-evidence.md](references/repo-evidence.md)
- [async-boundaries.md](references/async-boundaries.md)
- [lifecycle-and-gather.md](references/lifecycle-and-gather.md)
