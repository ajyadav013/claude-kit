# Namespacing and Invalidation Patterns

## Multi-tenant key namespacing

Production Redis caches use strict key prefixing to prevent cross-tenant data leakage.

### Standard format

```
{tenant_id}:{namespace}:{key}
```

Examples:
- `a1b2c3d4:{permission}:user_123:org_456`
- `e5f6g7h8:{dashboard}:filters:store_789`
- `{analytics}:report:monthly` (platform-level, no tenant_id)

### TenantRedis wrapper

```python
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
```

**Key behaviors:**
- Constructor takes `tenant_id: UUID | None` — `None` for platform-level keys
- `_key()` helper builds the full key with tenant prefix
- All methods delegate to the underlying `redis` client with formatted keys

**Alternative:** CacheManager `_key(tenant_id, namespace, key)` method. Same pattern, different wrapper style.

## SCAN-based namespace invalidation

### Why SCAN, not KEYS

`KEYS *` blocks Redis for milliseconds-to-seconds on large keyspaces. Production code uses `SCAN` with pagination.

### invalidate_namespace pattern

```python
async def invalidate_namespace(self, tenant_id: str, namespace: str) -> int:
    """Delete all keys in a tenant namespace. Returns count of deleted keys."""
    prefix = f"{tenant_id}:{namespace}:"
    pattern = f"{prefix}*"
    keys = []
    async for key in self.client.scan_iter(match=pattern, count=200):
        keys.append(key)
    if keys:
        return await self.client.delete(*keys)
    return 0
```

**Key details:**
- `scan_iter(match=pattern, count=200)` — async iterator, fetches 200 keys per SCAN call
- Collect keys in a list, then batch-delete via `delete(*keys)`
- Returns total count deleted for observability
- Safe for production — non-blocking, O(N) but chunked

### Manual SCAN loop (lower-level)

```python
async def invalidate_namespace_manual(redis: Redis, pattern: str) -> int:
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
    return deleted
```

**When to use:** When you need explicit pipeline control or custom logging per batch.

## Pipelined bulk delete

### Small set (<1000 keys)

```python
async def invalidate_users_cache_small(
    redis: Redis, user_ids: list[UUID], org_id: UUID
) -> None:
    keys = [f"perm:{uid}:{org_id}" for uid in user_ids]
    if keys:
        pipe = redis.pipeline()
        for key in keys:
            pipe.delete(key)
        await pipe.execute()
        logger.info("cache.bulk_invalidated", count=len(keys))
```

**Pattern:** Build full key list upfront, pipeline all deletes, single `execute()`.

### Large set (≥1000 keys)

```python
async def invalidate_users_cache_large(
    redis: Redis, user_ids: list[UUID], org_id: UUID
) -> None:
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
```

**Why:** Avoids building a 10k+ list in memory. Deletes in 500-key chunks via SCAN.

**Threshold:** Real service uses `if len(user_ids) < 1000:` small-set path, else large-set path.

## Invalidate entire tenant

```python
async def invalidate_tenant_cache(self, tenant_id: UUID) -> int:
    """Delete every key belonging to tenant_id."""
    return await self.delete_pattern(f"{tenant_id}:*")

async def delete_pattern(self, pattern: str) -> int:
    """Delete all keys matching pattern. Returns count."""
    keys: list[str] = []
    async for k in self._redis.scan_iter(match=pattern, count=200):
        keys.append(k)
    if keys:
        return await self._redis.delete(*keys)
    return 0
```

**Use case:** Tenant offboarding, data purge, emergency invalidation.

## Background invalidation

Non-critical invalidation (e.g., permission cache after role change) can run async without blocking the HTTP response.

```python
import asyncio

def schedule_cache_invalidation(
    redis: Redis,
    user_ids: list[UUID],
    org_id: UUID,
) -> None:
    """Schedule async cache invalidation without blocking response."""
    asyncio.create_task(invalidate_users_cache(redis, user_ids, org_id))
```

**Pattern:** Fire-and-forget `create_task()`. Task logs errors internally; caller doesn't await.

**When to use:** Permission updates, configuration changes. Not for critical writes (e.g., invalidating stale order data before read).

## Real-world grounding

### Permission cache invalidation

- **Single user:** `DELETE perm:{user_id}:{org_id}`
- **Role change affecting 50 users:** Pipeline DELETE with 50 keys
- **Organization deleted:** SCAN `perm:*:{org_id}`, delete in batches
- **Global permission deactivated:** SCAN `perm:*`, delete all

### Dashboard filter cache

- **User updates filters:** `DELETE {tenant_id}:filters:store_{id}`
- **Tenant data refresh:** SCAN `{tenant_id}:filters:*`, delete all

All use SCAN, not KEYS. All wrap in try/except. All log counts for monitoring.
