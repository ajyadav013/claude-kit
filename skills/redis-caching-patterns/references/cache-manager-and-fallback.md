# CacheManager and In-Memory Fallback

## Pattern overview

Production services implement a `CacheManager` that attempts Redis initialization on startup and falls back to an in-memory TTL cache if Redis is unavailable. This ensures zero downtime when Redis is down or misconfigured.

## CacheManager structure

```python
class CacheManager:
    """Cache with Redis primary and in-memory fallback."""

    def __init__(self, settings: RedisSettings) -> None:
        self._settings = settings
        self._client: aioredis.Redis | None = None
        self._mem = _MemoryCache()
        self._use_memory = False

    async def initialize(self) -> None:
        try:
            self._client = aioredis.from_url(
                self._settings.url,
                decode_responses=True,
            )
            await self._client.ping()
            logger.info("Redis client initialized")
        except Exception:
            logger.warning("Redis unavailable — using in-memory TTL cache")
            self._client = None
            self._use_memory = True
```

**Initialization flow:**
1. Create `CacheManager(settings)` in application factory
2. Call `await cache_manager.initialize()` in FastAPI `lifespan` startup
3. If Redis connection or ping fails, set `_use_memory = True` and log a warning
4. All subsequent operations check `if self._use_memory` and delegate to `_MemoryCache`

**Benefit:** The service starts successfully even when Redis is down. Caching continues with process-local TTL cache.

## In-memory TTL cache

Simple dict-based cache with expiration:

```python
class _MemoryCache:
    """Simple in-memory TTL cache used when Redis is unavailable."""

    def __init__(self) -> None:
        self._store: dict[str, tuple[Any, float]] = {}  # key → (value, expires_at)

    def get(self, key: str) -> Any | None:
        entry = self._store.get(key)
        if entry is None:
            return None
        value, expires_at = entry
        if time.monotonic() > expires_at:
            del self._store[key]
            return None
        return value

    def set(self, key: str, value: Any, ttl: int) -> None:
        self._store[key] = (value, time.monotonic() + ttl)

    def delete(self, key: str) -> None:
        self._store.pop(key, None)

    def clear_prefix(self, prefix: str) -> int:
        to_delete = [k for k in self._store if k.startswith(prefix)]
        for k in to_delete:
            del self._store[k]
        return len(to_delete)
```

**Key behaviors:**
- `get()` checks `expires_at` against `time.monotonic()` and deletes expired entries lazily
- `set()` stores `(value, time.monotonic() + ttl)`
- `clear_prefix()` supports namespace invalidation by filtering keys with `startswith()`

**Limitation:** Process-local only. Multi-instance deployments won't share cache. Acceptable for read-heavy, eventually-consistent data (analytics, filters).

## CacheManager methods

All methods delegate to Redis or in-memory based on `_use_memory` flag:

```python
async def get(self, tenant_id: str, namespace: str, key: str) -> Any | None:
    full_key = self._key(tenant_id, namespace, key)
    if self._use_memory:
        return self._mem.get(full_key)
    try:
        raw = await self.client.get(full_key)
        if raw is None:
            return None
        return json.loads(raw) if raw else raw
    except Exception:
        logger.error("Failed to get key %s from Redis", full_key)
        return None

async def set(
    self,
    tenant_id: str,
    namespace: str,
    key: str,
    value: Any,
    ttl: int | None = None,
) -> None:
    ttl = ttl or self._settings.default_ttl
    full_key = self._key(tenant_id, namespace, key)
    if self._use_memory:
        self._mem.set(full_key, value, ttl)
        return
    try:
        serialized = json.dumps(value) if not isinstance(value, str) else value
        await self.client.set(full_key, serialized, ex=ttl)
    except Exception:
        logger.error("Failed to set key %s in Redis", full_key)
```

**Graceful degradation:** Every Redis operation wrapped in `try/except Exception`. Errors logged but not raised — the service continues.

## Key formatting

```python
def _key(self, tenant_id: str, namespace: str, key: str) -> str:
    return f"{tenant_id}:{namespace}:{key}"
```

All keys follow `{tenant_id}:{namespace}:{key}` format. See `namespacing-and-invalidation.md`.

## Health check

```python
async def health_check(self) -> bool:
    if self._use_memory:
        return True
    if self._client is None:
        return False
    try:
        return await self.client.ping()
    except Exception:
        logger.exception("Redis health check failed")
        return False
```

Expose this in a `/health` endpoint to monitor cache layer. Returns `True` for in-memory mode (degraded but operational).

## Lifespan integration

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI

cache_manager: CacheManager | None = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global cache_manager
    cache_manager = CacheManager(redis_settings)
    await cache_manager.initialize()
    yield
    await cache_manager.close()
```

Initialize in FastAPI lifespan startup, close on shutdown. Singleton pattern for process-wide cache.

## Real-world grounding

Observed in production services handling:
- Analytics cache for dashboard filters (1-hour TTL)
- Permission cache for RBAC checks (5-minute TTL)
- BigQuery results cache (10-minute TTL)

When Redis maintenance windows occur, services continue with in-memory cache. Alerts fired but no user-facing downtime.
