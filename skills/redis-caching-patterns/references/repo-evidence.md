# Repo Evidence (Genericized)

Short, genericized snippets grounding the patterns in real production code.

## TenantRedis: multi-tenant key prefixing

**Source:** `backend/common/redis_client.py`

```python
class TenantRedis:
    """Redis wrapper that namespaces keys by tenant.

    Args:
        redis: Underlying async Redis connection.
        tenant_id: Tenant UUID for key prefixing. None for platform-level keys.
    """

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

    async def invalidate_namespace(self, tenant_id: UUID, namespace: str) -> int:
        """Delete all keys in namespace for tenant_id."""
        return await self.delete_pattern(f"{tenant_id}:{namespace}:*")

    async def delete_pattern(self, pattern: str) -> int:
        """Delete all keys matching pattern. Returns count deleted."""
        keys: list[str] = []
        async for k in self._redis.scan_iter(match=pattern, count=200):
            keys.append(k)
        if keys:
            return await self._redis.delete(*keys)
        return 0
```

**Pattern:** Tenant-scoped wrapper with `_key()` helper. SCAN-based invalidation.

---

## CacheManager: Redis-primary + in-memory fallback

**Source:** `apps/api/src/app/core/cache.py`

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
```

**Pattern:** Graceful fallback on init failure. Every Redis op wrapped in try/except.

---

## BaseRedis: prefix-scoped abstraction

**Source:** `apps/api/src/app/core/redis.py`

```python
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

    async def clear_all(self) -> int:
        """Delete all keys matching {tenant_id}:{prefix}:*."""
        if self._cache is None:
            return 0
        try:
            return await self._cache.invalidate_namespace(
                self._tenant_id, self.prefix,
            )
        except Exception:
            logger.error("Failed to clear keys with prefix %s:%s", self._tenant_id, self.prefix)
            return 0
```

**Pattern:** Feature modules subclass and define domain methods. All ops wrap cache calls with error handling.

---

## Permission cache: graceful degradation + background invalidation

**Source:** `backend/access/v1/evaluation/cache.py`

```python
async def get_cached_permissions(
    redis: Redis, user_id: uuid.UUID, org_id: uuid.UUID
) -> set[str] | None:
    """Retrieve cached permission set. Returns None on miss or error."""
    try:
        key = f"perm:{user_id}:{org_id}"
        data = await redis.get(key)
        if data is None:
            logger.debug("cache.miss", user_id=str(user_id))
            return None
        logger.debug("cache.hit", user_id=str(user_id))
        return set(json.loads(data))
    except Exception:
        logger.warning("cache.read_error", user_id=str(user_id))
        return None


async def invalidate_users_cache(
    redis: Redis, user_ids: list[uuid.UUID], org_id: uuid.UUID
) -> None:
    """Invalidate cache for multiple users via pipeline or SCAN."""
    try:
        if len(user_ids) < 1000:
            # Small set: pipeline DELETE
            keys = [f"perm:{uid}:{org_id}" for uid in user_ids]
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

**Pattern:** `try/except` on all ops. Pipelined bulk delete. SCAN for large sets. Background task scheduling.

---

## Tenant-scoped cache key with strong isolation

**Source:** `backend/app/core/cache.py`

```python
def _k(tenant_scope: str, ns: str, key: str) -> str:
    # Strong tenant/org isolation: cache:{tenant:org}:{ns}:{key}
    return f"cache:{tenant_scope}:{ns}:{key}"

async def cache_get(tenant_scope: str, ns: str, key: str) -> Optional[str]:
    assert _redis is not None, "cache not initialized"
    return await _redis.get(_k(tenant_scope, ns, key))

async def invalidate_namespace(tenant_scope: str, ns: str) -> None:
    """Invalidate all cache keys in a namespace for a tenant."""
    assert _redis is not None, "cache not initialized"
    
    pattern = f"cache:{tenant_scope}:{ns}:*"
    cursor = 0
    deleted_count = 0
    
    while True:
        cursor, keys = await _redis.scan(cursor, match=pattern, count=100)
        if keys:
            deleted = await _redis.delete(*keys)
            deleted_count += deleted
        if cursor == 0:
            break
    
    return deleted_count
```

**Pattern:** Three-level key structure `cache:{tenant_scope}:{ns}:{key}`. SCAN loop with batch delete.

---

## Configurable TTL per namespace

**Source:** `apps/api/src/app/domain_feature/config.py`

```python
# Feature-specific config
class ServiceConfig(BaseSettings):
    filters_cache_ttl: int = 3600  # 1 hour
    analytics_cache_ttl: int = 600   # 10 minutes
    default_cache_ttl: int = 300  # 5 minutes

# Usage in service
await self._cache.set(tenant_id, namespace, key, value, ttl=self._config.filters_cache_ttl)
```

**Pattern:** Global default in RedisSettings, per-feature override in domain config.

---

All snippets genericized — no internal service names, repos, cloud projects, or filesystem paths.
