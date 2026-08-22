---
name: redis-caching-patterns
description: Production Redis caching — multi-tenant namespacing, configurable TTL, in-memory fallback degradation, safe SCAN-based invalidation. Use when caching in multi-tenant services or handling Redis failures.
---

Standardize Redis caching implementation with multi-tenant key isolation, TTL strategies, graceful degradation, and safe bulk invalidation patterns.

## When to use

- Building a cache layer for a multi-tenant service with tenant/org isolation requirements
- Implementing graceful degradation when Redis is unavailable (in-memory TTL fallback)
- Designing namespace-based cache invalidation (user permissions, tenant data, feature caches)
- Adding configurable TTL strategies per namespace or feature domain
- Creating a BaseRedis abstraction for prefix-scoped cache operations
- Migrating from unsafe `KEYS *` patterns to `SCAN`-based iteration
- Handling background cache invalidation without blocking request responses
- Distinguishing cached `None` values from cache misses (None-sentinel pattern)
- Implementing pipelined bulk delete for small/large key sets
- Adding Redis health checks and automatic fallback switching

## Core conventions

1. **Multi-tenant key namespacing**: every key follows `{tenant_id}:{namespace}:{key}` format. Build keys via a `_key()` or `_k()` helper function that takes `(tenant_id, namespace, key)` and returns the formatted string. For platform-level (non-tenant) keys, support `{namespace}:{key}` when `tenant_id=None`. This guarantees tenant data isolation and enables namespace-scoped invalidation.

2. **CacheManager with Redis-primary + in-memory fallback**: implement `CacheManager` that tries to initialize Redis on startup via `initialize()` → `redis.from_url()` → `await client.ping()`. If Redis is unavailable, set `_use_memory = True` and fall back to an in-memory TTL cache (`_MemoryCache` — simple `dict[str, tuple[value, expires_at]]` with monotonic clock). Every `get/set/delete` operation checks `if self._use_memory` and delegates to the fallback; otherwise uses Redis. This ensures zero downtime when Redis is down. See [cache-manager-and-fallback.md](references/cache-manager-and-fallback.md).

3. **BaseRedis abstraction**: create a `BaseRedis` base class that subclasses bind to a `(tenant_id, prefix, ttl)` tuple. The base class provides `set_key(key, value, ttl)`, `get_key(key)`, `delete_key(key)`, and `clear_all()` methods that delegate to `CacheManager`. Feature modules subclass and define domain-specific methods (e.g., `DashboardCache.set_tab()`). This keeps cache logic DRY and prefix-scoped. Every operation wraps CacheManager calls in `try/except` and logs errors without propagating — degradation is silent.

4. **Configurable TTL strategies**: define a default TTL in `RedisSettings` (e.g., `default_ttl: int = 300`). Allow per-namespace or per-feature TTL overrides via config (e.g., `filters_cache_ttl: int = 3600` for filters, `insights_cache_ttl: int = 600` for analytics). Pass `ttl` as an optional parameter to `set()` methods — fall back to the instance or global default if omitted. For time-sensitive data that should expire at midnight, calculate `ttl = seconds_until_midnight()` dynamically (not shown in repo evidence but a common pattern).

5. **Graceful degradation**: wrap every Redis operation in `try/except Exception` and return `None` on `get` failures, silent no-op on `set/delete` failures. Log the error (e.g., `logger.error("Failed to get key from Redis")`) but do not raise. The system must never crash due to Redis unavailability. When Redis is down, the in-memory cache serves as a process-local fallback with TTL enforcement.

6. **Namespace invalidation via SCAN**: implement `invalidate_namespace(tenant_id, namespace)` that deletes all keys matching `{tenant_id}:{namespace}:*`. Use `SCAN` with `match=pattern, count=100-500` in a loop (`while cursor != 0`), collect keys, then batch-delete via `await redis.delete(*keys)` or pipeline. Never use `KEYS *` in production — it blocks Redis. Return the count of deleted keys for observability. For in-memory fallback, clear via `self._mem.clear_prefix(prefix)` by filtering the dict. See [namespacing-and-invalidation.md](references/namespacing-and-invalidation.md).

7. **Pipelined bulk delete**: for small sets (<1000 keys), build a list of full keys and execute `pipe = redis.pipeline(); for key in keys: pipe.delete(key); await pipe.execute()`. For large sets (≥1000 or unbounded), use `SCAN` + pipeline: iterate with `await redis.scan(cursor, match=pattern)`, batch the keys, and delete in chunks. This avoids memory spikes and blocking. Example: invalidating permissions for 10,000 users → SCAN pattern `perm:*:{org_id}`, delete in 500-key chunks.

8. **Background invalidation via `asyncio.create_task`**: for non-critical invalidation (e.g., user permission cache after role change), schedule it in the background with `asyncio.create_task(invalidate_users_cache(redis, user_ids, org_id))` so the HTTP response isn't blocked. The task runs fire-and-forget; log errors inside the task if it fails. Do NOT await the task in the request handler.

9. **None-sentinel caching** (optional): to distinguish cached `None` (e.g., "user not found" query result) from cache miss, serialize `None` as a sentinel string (`"__NONE__"`) or JSON `null`. On `get`, check if the raw value is the sentinel and return `None`; if the key doesn't exist, return a different marker (e.g., `CacheMiss` object) so the caller knows to query the database. This is not shown in repo evidence but is a known pattern for negative caching.

10. **TenantRedis wrapper** (alternative pattern): instead of CacheManager, create a lightweight `TenantRedis` class that wraps `redis.asyncio.Redis` and auto-prefixes keys. Constructor takes `(redis: Redis, tenant_id: UUID | None)`. Methods like `get(namespace, key)`, `set(namespace, key, value, ex)`, `delete_pattern(pattern)`, `invalidate_namespace(tenant_id, namespace)` build the full key via `_key()` and delegate to the wrapped client. This is simpler than CacheManager but lacks fallback. See [namespacing-and-invalidation.md](references/namespacing-and-invalidation.md).

11. **RedisSettings configuration**: define a Pydantic `RedisSettings` class with `url: str`, `default_ttl: int`, `decode_responses: bool = True`. Load from env (`REDIS_URL`, `REDIS_DEFAULT_TTL`). Pass to `CacheManager.__init__()`. Use `redis.from_url(settings.url, decode_responses=True)` to auto-decode bytes to strings.

12. **Health check endpoint**: implement `async def health_check() -> bool` that returns `True` for in-memory mode or tries `await redis.ping()` with exception handling. Expose via a `/health` endpoint to monitor cache availability. Log health check failures for alerting.

13. **Cross-link multi-tenancy-patterns and async-python-patterns**: see `multi-tenancy-patterns` for RLS/schema isolation and tenant context propagation; see `async-python-patterns` for asyncio task scheduling, connection pooling, and async context managers.

14. **Cache-stampede protection for hot keys** (single-flight + early recompute): when a popular key expires, many concurrent requests miss *at the same instant* and all recompute it simultaneously — a *thundering herd* that can overload the very origin the cache exists to protect (and the network can't tell them to wait for each other). Two composable defenses; reserve them for genuinely hot keys, since the coordination cost isn't worth it for cold ones:
    - **Request coalescing / single-flight** — the first miss takes a short per-key lock (`SET {key}:lock <token> NX EX <few s>`), recomputes, and populates the cache; concurrent callers that fail to get the lock briefly wait-and-retry the read (or serve the last good value) instead of stampeding the origin. Only one caller hits the backend per key per expiry. Release the lock by token (compare-and-delete) so a slow holder can't delete a successor's lock.
    - **Probabilistic early expiration (XFetch)** — store the value's recompute cost and its expiry alongside it, and let each reader *probabilistically* recompute slightly *before* the TTL elapses (the probability rises as expiry nears). One request refreshes the key while it is still warm; everyone else keeps hitting the cache, so the key never actually expires under load. This avoids the synchronized miss entirely, without a lock.

    > Per the AWS Builders Library ("Caching challenges and strategies", aws.amazon.com/builders-library) and the XFetch scheme (Vattani et al., "Optimal Probabilistic Cache Stampede Prevention"). Stack-agnostic; the lock/early-recompute discipline maps to any cache, not just Redis.

## Skeleton / example

```python
# app/core/config.py (Pydantic settings)
from pydantic_settings import BaseSettings

class RedisSettings(BaseSettings):
    url: str = "redis://localhost:6379/0"
    default_ttl: int = 300  # 5 minutes
    decode_responses: bool = True

    class Config:
        env_prefix = "REDIS_"

settings = Settings()
redis_settings = RedisSettings()
```

```python
# app/core/cache.py (CacheManager with in-memory fallback)
import json
import logging
import time
from typing import Any

import redis.asyncio as aioredis

from app.core.config import RedisSettings

logger = logging.getLogger("app.core.cache")


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

    @property
    def client(self) -> aioredis.Redis:
        if self._client is None:
            raise RuntimeError("Redis client not initialized. Call initialize() first.")
        return self._client

    def _key(self, tenant_id: str, namespace: str, key: str) -> str:
        return f"{tenant_id}:{namespace}:{key}"

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

    async def delete(self, tenant_id: str, namespace: str, key: str) -> None:
        full_key = self._key(tenant_id, namespace, key)
        if self._use_memory:
            self._mem.delete(full_key)
            return
        try:
            await self.client.delete(full_key)
        except Exception:
            logger.error("Failed to delete key %s from Redis", full_key)

    async def invalidate_namespace(self, tenant_id: str, namespace: str) -> int:
        """Delete all keys in a tenant namespace. Returns count of deleted keys."""
        prefix = f"{tenant_id}:{namespace}:"
        if self._use_memory:
            return self._mem.clear_prefix(prefix)
        try:
            pattern = f"{prefix}*"
            keys = []
            async for key in self.client.scan_iter(match=pattern):
                keys.append(key)
            if keys:
                return await self.client.delete(*keys)
            return 0
        except Exception:
            logger.error("Failed to invalidate namespace %s:%s", tenant_id, namespace)
            return 0

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

    async def close(self) -> None:
        if self._client:
            await self._client.close()
            self._client = None
            logger.info("Redis client closed")
```

```python
# app/core/redis.py (BaseRedis abstraction)
import logging
from typing import Any

from app.core.cache import CacheManager

logger = logging.getLogger("app.core.redis")


class BaseRedis:
    """Prefix-scoped, tenant-aware Redis cache backed by CacheManager.

    Each instance is bound to a (tenant_id, prefix, ttl) tuple.
    Keys are stored as {tenant_id}:{prefix}:{key} via CacheManager.
    """

    def __init__(
        self,
        cache_manager: CacheManager | None,
        tenant_id: str,
        prefix: str,
        ttl: int,
    ) -> None:
        self._cache = cache_manager
        self._tenant_id = tenant_id
        self.prefix = prefix
        self.ttl = ttl

    async def set_key(self, key: str, value: Any, ttl: int | None = None) -> None:
        """Store a value under {tenant_id}:{prefix}:{key}."""
        if self._cache is None:
            return
        try:
            await self._cache.set(
                self._tenant_id,
                self.prefix,
                key,
                value,
                ttl=ttl or self.ttl,
            )
        except Exception:
            logger.error("Failed to set key %s:%s in Redis", self.prefix, key)

    async def get_key(self, key: str) -> Any | None:
        """Retrieve a value. Returns None on miss or error."""
        if self._cache is None:
            return None
        try:
            return await self._cache.get(self._tenant_id, self.prefix, key)
        except Exception:
            logger.error("Failed to get key %s:%s from Redis", self.prefix, key)
            return None

    async def delete_key(self, key: str) -> None:
        """Delete a single key."""
        if self._cache is None:
            return
        try:
            await self._cache.delete(self._tenant_id, self.prefix, key)
        except Exception:
            logger.error("Failed to delete key %s:%s from Redis", self.prefix, key)

    async def clear_all(self) -> int:
        """Delete all keys matching {tenant_id}:{prefix}:*.

        Returns the number of keys deleted.
        """
        if self._cache is None:
            return 0
        try:
            return await self._cache.invalidate_namespace(
                self._tenant_id, self.prefix,
            )
        except Exception:
            logger.error(
                "Failed to clear keys with prefix %s:%s",
                self._tenant_id, self.prefix,
            )
            return 0


# Feature-specific cache (example)
class DashboardCache(BaseRedis):
    def __init__(self, cache_manager: CacheManager, tenant_id: str):
        super().__init__(cache_manager, tenant_id, prefix="dashboard", ttl=1800)

    async def get_filters(self, user_id: str) -> dict | None:
        return await self.get_key(f"filters:{user_id}")

    async def set_filters(self, user_id: str, filters: dict) -> None:
        await self.set_key(f"filters:{user_id}", filters)
```

```python
# app/lifespan.py (FastAPI lifespan with cache init/close)
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.cache import CacheManager
from app.core.config import redis_settings

cache_manager: CacheManager | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global cache_manager
    cache_manager = CacheManager(redis_settings)
    await cache_manager.initialize()
    yield
    await cache_manager.close()


def get_cache_manager() -> CacheManager:
    if cache_manager is None:
        raise RuntimeError("Cache manager not initialized")
    return cache_manager
```

```python
# domain/v1/cache.py (permission cache with background invalidation)
import asyncio
import uuid
import json
import logging

from redis.asyncio import Redis

logger = logging.getLogger(__name__)


def _cache_key(user_id: uuid.UUID, org_id: uuid.UUID) -> str:
    return f"perm:{user_id}:{org_id}"


async def get_cached_permissions(
    redis: Redis, user_id: uuid.UUID, org_id: uuid.UUID
) -> set[str] | None:
    """Retrieve cached permission set. Returns None on miss or error."""
    try:
        key = _cache_key(user_id, org_id)
        data = await redis.get(key)
        if data is None:
            logger.debug("cache.miss", user_id=str(user_id), org_id=str(org_id))
            return None
        logger.debug("cache.hit", user_id=str(user_id), org_id=str(org_id))
        return set(json.loads(data))
    except Exception:
        logger.warning("cache.read_error", user_id=str(user_id), org_id=str(org_id))
        return None


async def set_cached_permissions(
    redis: Redis,
    user_id: uuid.UUID,
    org_id: uuid.UUID,
    permissions: set[str],
    ttl: int = 300,
) -> None:
    """Store permission set with TTL. Silent failure on error."""
    try:
        key = _cache_key(user_id, org_id)
        data = json.dumps(sorted(permissions))
        await redis.setex(key, ttl, data)
        logger.debug(
            "cache.set",
            user_id=str(user_id),
            org_id=str(org_id),
            count=len(permissions),
        )
    except Exception:
        logger.warning("cache.write_error", user_id=str(user_id), org_id=str(org_id))


async def invalidate_users_cache(
    redis: Redis, user_ids: list[uuid.UUID], org_id: uuid.UUID
) -> None:
    """Invalidate cache for multiple users via pipeline or SCAN."""
    try:
        if len(user_ids) < 1000:
            # Small set: pipeline DELETE
            keys = [_cache_key(uid, org_id) for uid in user_ids]
            if keys:
                pipe = redis.pipeline()
                for key in keys:
                    pipe.delete(key)
                await pipe.execute()
                logger.info("cache.bulk_invalidated", count=len(keys))
        else:
            # Large set: SCAN + pipeline
            pattern = f"perm:*:{org_id}"
            deleted = 0
            cursor = 0
            while True:
                cursor, keys = await redis.scan(cursor=cursor, match=pattern, count=500)
                if keys:
                    pipe = redis.pipeline()
                    for key in keys:
                        pipe.delete(key)
                    await pipe.execute()
                    deleted += len(keys)
                if cursor == 0:
                    break
            logger.info("cache.scan_invalidated", count=deleted)
    except Exception:
        logger.warning("cache.bulk_invalidate_error", count=len(user_ids))


def schedule_cache_invalidation(
    redis: Redis,
    user_ids: list[uuid.UUID],
    org_id: uuid.UUID,
) -> None:
    """Schedule async cache invalidation without blocking response."""
    asyncio.create_task(invalidate_users_cache(redis, user_ids, org_id))
```

```python
# Alternative: TenantRedis wrapper (simpler, no fallback)
from uuid import UUID
from redis.asyncio import Redis


class TenantRedis:
    """Redis wrapper that namespaces keys by tenant."""

    def __init__(self, redis: Redis, tenant_id: UUID | None = None) -> None:
        self._redis = redis
        self._tenant_id = tenant_id

    def _key(self, namespace: str, key: str) -> str:
        """Build {tenant_id}:{namespace}:{key} or {namespace}:{key}."""
        if self._tenant_id:
            return f"{self._tenant_id}:{namespace}:{key}"
        return f"{namespace}:{key}"

    async def get(self, namespace: str, key: str) -> str | None:
        return await self._redis.get(self._key(namespace, key))

    async def set(
        self, namespace: str, key: str, value: str, *, ex: int | None = None
    ) -> None:
        await self._redis.set(self._key(namespace, key), value, ex=ex)

    async def delete(self, namespace: str, key: str) -> int:
        return await self._redis.delete(self._key(namespace, key))

    async def delete_pattern(self, pattern: str) -> int:
        """Delete all keys matching pattern via SCAN. Returns count."""
        keys: list[str] = []
        async for k in self._redis.scan_iter(match=pattern, count=200):
            keys.append(k)
        if keys:
            return await self._redis.delete(*keys)
        return 0

    async def invalidate_namespace(self, tenant_id: UUID, namespace: str) -> int:
        """Delete all {tenant_id}:{namespace}:* keys."""
        return await self.delete_pattern(f"{tenant_id}:{namespace}:*")

    @property
    def raw(self) -> Redis:
        """Access underlying Redis for unsupported operations."""
        return self._redis
```

## Beyond-cache Redis: structures, atomicity, eviction, persistence

Everything above treats Redis as a cache — string values under a TTL, safe to lose and recompute.
Redis is equally an operational store (rate limiters, queues, rankings, membership checks), and
that role forces four decisions a pure cache never surfaces. Frame each as a choice with a
default, the same way the conventions above do:

1. **Purpose-fit structure selection** — don't serialize everything into JSON-blob strings; pick
   the native structure that makes the hot operation O(1)/O(log N) instead of
   deserialize-modify-reserialize:
    - **Hash** for object-like records accessed field-by-field (`HSET user:{id} email …`,
      `HGET user:{id} email`) — read or update one field without round-tripping the whole object
      through the serializer.
    - **Sorted set** for anything ordered by score: leaderboards (`ZADD` + `ZREVRANGE` give top-N
      and rank for free) and sliding rate-limit windows (score = request timestamp;
      `ZREMRANGEBYSCORE` prunes entries older than the window, `ZCARD` counts the remainder).
    - **Set** for membership and uniqueness (tags, seen-IDs, permission flags) with native
      union/intersection/difference — no read-everything-then-scan in application code.
    - **List** for queues: producers `LPUSH`, consumers `BRPOP` (blocking pop, no poll loop). For
      crash-safety, atomically move each job into a per-consumer processing list and delete it
      only after completion so a dead consumer leaves the job recoverable.
    - **String + `INCR`** for counters — a single-command atomic increment, no read-modify-write.

    Default: if a value is always read and written whole, a JSON string under the conventions
    above is right; the moment you operate on *parts* of a value or need ordering/membership
    semantics, switch structures rather than growing application-side logic.

2. **Atomicity — match the tool to the operation.** Every single command is already atomic (Redis
   executes commands one at a time on one thread), so `INCR` or `SET … NX` need nothing extra.
   For compound operations:
    - **MULTI/EXEC** queues commands and runs them as one uninterruptible batch — with **no
      rollback**: if a queued command errors, the rest still run. Use it for grouped writes that
      are individually safe, never for all-or-nothing semantics.
    - **WATCH** turns MULTI/EXEC into optimistic check-and-set: watch the key, read, queue the
      update; EXEC aborts if the key changed underneath, and the client retries. Right for
      low-contention read-modify-write cycles.
    - **Server-side Lua (`EVAL`)** runs a whole script as one atomic unit — the only way to make
      read-decide-write logic atomic. Canonical case: an atomic rate-limit counter that
      increments, checks the cap, and sets the window expiry in one step. Cache scripts and
      invoke by SHA (`EVALSHA`) so the body isn't resent on every call.
    - **Pipelining is not atomicity** — it batches round trips for throughput (other clients'
      commands may interleave). Use it to amortize network latency (convention 7), not for
      consistency.

    Default: plain commands where one suffices; Lua when the logic must read *and* write
    atomically; MULTI/EXEC only for independent grouped updates; WATCH when contention is low
    and a retry loop is acceptable.

3. **Eviction policy per workload** (`maxmemory-policy`) — when the memory cap is hit, the policy
   decides what disappears, and the wrong pick either silently drops data or refuses writes at
   peak:
    - **Cache workloads**: `allkeys-lru` is the standard choice; prefer `allkeys-lfu` when the
      hot set is popularity-skewed (a few keys dominate reads) so access *frequency*, not
      recency, decides survival.
    - **Store workloads** (queues, locks, counters): `noeviction` — silently evicting a lock or a
      queued job is data loss; better that writes fail loudly and alert someone.
    - **Mixed instances**: `volatile-lru`/`volatile-lfu`/`volatile-ttl` evict only TTL-bearing
      keys, so cache entries (which carry TTLs per convention 4) are reclaimable while durable
      keys without TTLs survive.

    Default: `allkeys-lfu` for a dedicated cache instance; `noeviction` the moment anything
    non-recomputable shares the instance — and prefer splitting cache and store into separate
    instances so the choice stays unambiguous.

4. **Persistence per role, decided explicitly** — never inherit whatever the deployment template
   shipped:
    - **RDB snapshots**: a background fork writes a compact point-in-time dump — small files,
      fast restarts, cheap backups — but everything since the last snapshot is lost on a crash.
      Fits data with an acceptable, bounded loss window.
    - **AOF**: every write is appended and replayed at startup; `appendfsync everysec` is the
      standard setting — bounds loss to about one second without paying a per-write fsync.
      Costs: larger files, slower restarts, periodic rewrites to compact the log.
    - **Hybrid RDB+AOF** (Redis ≥ 4.0): the AOF rewrite embeds an RDB snapshot at the head and
      appends subsequent commands — snapshot-fast restart plus AOF-grade durability. The
      production default when Redis holds anything you can't recompute.
    - **Persistence off** is legitimate for a pure cache: every value is recomputable from the
      origin, a cold restart is just a warm-up period, and the in-memory fallback (convention 2)
      already covers the outage case. Maximum throughput, zero disk.

    Default: persistence off (or RDB-only if you want faster warm restarts) on cache instances;
    hybrid RDB+AOF on anything operational.

> Distilled from [htn-a-complete-guide-to-redis.md](references/htn-a-complete-guide-to-redis.md),
> an own-words digest whose operational sections (structures, transactions, eviction,
> persistence) back this section.

## Anti-patterns to avoid

1. **Using `KEYS *` for pattern matching**: blocks Redis for large keyspaces. Use `SCAN` with `match` and `count`.
2. **Raising exceptions on cache failures**: wrap all Redis ops in `try/except` and return `None` or no-op. Caching is an optimization, not a requirement.
3. **Hardcoding TTL values in code**: define TTL in settings (global default + per-namespace overrides) so it's tunable without code changes.
4. **Not namespacing keys by tenant**: a single key like `user:123` allows cross-tenant data leakage. Always prefix with `{tenant_id}:`.
5. **Blocking responses for cache invalidation**: use `asyncio.create_task()` for non-critical invalidation so the HTTP response isn't delayed.
6. **Deleting 10k+ keys in one command**: batch via pipeline or SCAN loop to avoid memory spikes and blocking.
7. **Assuming Redis is always available**: add in-memory fallback or handle `None` returns gracefully in application logic.
8. **Not logging cache errors**: silent failures are invisible. Log at `warning` or `error` level for monitoring/alerting.
9. **Mixing sync and async Redis clients**: use `redis.asyncio` consistently in async services (FastAPI, aiohttp). Sync `redis-py` blocks the event loop.
10. **Storing sensitive data without encryption**: cache should not hold PII/secrets unless encrypted at application layer. Use short TTLs for sensitive data.
11. **No stampede protection on hot keys**: letting a popular key expire with no coalescing or early recompute means every concurrent miss recomputes at once and can knock over the origin — the failure often looks like a mysterious periodic latency/error spike synced to the TTL. Add single-flight and/or probabilistic early expiration for hot keys (convention 14).

## References

- [repo-evidence.md](references/repo-evidence.md) — genericized source snippets
- [cache-manager-and-fallback.md](references/cache-manager-and-fallback.md) — CacheManager, in-memory fallback, initialization patterns
- [namespacing-and-invalidation.md](references/namespacing-and-invalidation.md) — TenantRedis, key formatting, SCAN-based invalidation, pipelined bulk delete
- [htn-a-complete-guide-to-redis.md](references/htn-a-complete-guide-to-redis.md) — operational-Redis digest: data structures, transactions/Lua, eviction, persistence, replication, security
- `multi-tenancy-patterns` — tenant isolation, RLS, schema context
- `async-python-patterns` — asyncio.create_task, connection pooling, lifespan hooks
