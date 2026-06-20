# async-python-patterns

Async programming patterns derived from production Python/FastAPI codebases.

## What this skill covers

This skill encodes async programming conventions observed across FastAPI microservices, Temporal workers, and Kafka consumers in real-world production services:

- **Async stack:** `async def` handlers, `AsyncSession` over asyncpg, aiokafka, aiohttp
- **Lifecycle:** FastAPI `lifespan` context manager for connection management
- **Concurrency primitive:** `asyncio.gather` for running workers/tasks together
- **Sync/async bridges:** `asyncio.to_thread` and `run_coroutine_threadsafe` for crossing boundaries
- **The sync-in-async trap:** Blocking cloud clients (BigQuery, GCS) called from async code without offloading
- **Graceful shutdown:** Signal handlers (`SIGTERM`/`SIGINT`) triggering `worker.shutdown()` and `gather(..., return_exceptions=True)`
- **Async HTTP clients:** Lightweight aiohttp wrappers and async request libraries with circuit breaker + retry

## How to apply

1. **For new async services:** Start with the FastAPI lifespan skeleton and AsyncSession setup from the skill examples. Initialize connections on startup, close on shutdown.
2. **For Temporal workers or multi-consumer setups:** Use the `asyncio.gather` + signal handler pattern to run workers concurrently and shut down gracefully.
3. **When bridging sync/async (e.g., kafka-python):** Follow the consumer bridge pattern: run the blocking consumer in `asyncio.to_thread`, dispatch handlers back via `run_coroutine_threadsafe`.
4. **Before calling any sync cloud client from async code:** Check if an async client exists (gcloud-aio-storage, aioboto3). If not, wrap the sync call in `asyncio.to_thread(...)`.
5. **For HTTP calls:** Use a lightweight aiohttp wrapper (`AsyncHTTPClient` pattern) or an async request library if you need circuit breaker + retry + protocol plugins.

## Provenance

### Codebase-derived

- AsyncSession setup (SQLAlchemy 2.0 + asyncpg, `async_scoped_session` with `current_task` scope)
- FastAPI lifespan pattern
- `asyncio.gather` as the universal concurrency primitive (no TaskGroup usage observed)
- Sync consumer → async handler bridge via `to_thread` + `run_coroutine_threadsafe`
- Signal-based graceful shutdown with `loop.add_signal_handler`
- BigQuery/GCS sync-in-async trap anti-pattern
- gcloud-aio-storage as async GCS client
- AsyncHTTPClient wrapper and async request library patterns

### Internet-confirmed

- SQLAlchemy 2.0 async patterns and `create_async_engine` usage documented at https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html
- `asyncio.to_thread` and `run_coroutine_threadsafe` threading bridge patterns documented at https://docs.python.org/3/library/asyncio-task.html
- aiohttp client session lifecycle best practices at https://docs.aiohttp.org/en/stable/client_quickstart.html
