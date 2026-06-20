# Tenant-Scoped Caching Patterns

How to isolate cache data across tenants and organizations.

## Key Namespacing Pattern

**Source**: Production FastAPI service

All cache keys follow a hierarchical namespacing pattern to ensure strong tenant isolation:

```
cache:{tenant_scope}:{namespace}:{key}
```

Where:
- `tenant_scope` = `{tenant_id}:{org_id}` (composite identifier)
- `namespace` = logical grouping (e.g., `users`, `orders`, `inventory`)
- `key` = specific entity identifier

## Implementation

### Cache Key Builder

Example pattern:
```python
def _k(tenant_scope: str, ns: str, key: str) -> str:
    """Build a tenant-scoped cache key.
    
    Args:
        tenant_scope: Composite "{tenant_id}:{org_id}"
        ns: Namespace for logical grouping
        key: Specific entity key
    
    Returns:
        Fully-qualified cache key
    """
    return f"cache:{tenant_scope}:{ns}:{key}"
```

### Basic Operations

```python
async def cache_get(tenant_scope: str, ns: str, key: str) -> Optional[str]:
    """Get a value from the tenant-scoped cache."""
    return await _redis.get(_k(tenant_scope, ns, key))

async def cache_set(
    tenant_scope: str,
    ns: str,
    key: str,
    value: str,
    ttl: Optional[int] = None
) -> None:
    """Set a value in the tenant-scoped cache."""
    if ttl:
        await _redis.setex(_k(tenant_scope, ns, key), ttl, value)
    else:
        await _redis.set(_k(tenant_scope, ns, key), value)

async def cache_delete(tenant_scope: str, ns: str, key: str) -> None:
    """Delete a value from the tenant-scoped cache."""
    await _redis.delete(_k(tenant_scope, ns, key))
```

### Namespace Invalidation

Clear all keys for a tenant and namespace at once:

```python
async def invalidate_namespace(tenant_scope: str, ns: str) -> None:
    """Delete all cache entries for a tenant's namespace.
    
    Uses SCAN to iterate through keys matching the pattern
    cache:{tenant_scope}:{ns}:* and deletes them in batches.
    """
    pattern = f"cache:{tenant_scope}:{ns}:*"
    cursor = 0
    deleted_count = 0
    
    while True:
        cursor, keys = await _redis.scan(cursor, match=pattern, count=100)
        if keys:
            await _redis.delete(*keys)
            deleted_count += len(keys)
        if cursor == 0:
            break
    
    logger.info(
        "Invalidated namespace cache",
        tenant_scope=tenant_scope,
        namespace=ns,
        deleted_keys=deleted_count,
    )
```

### Tenant-Wide Invalidation

Clear all cache data for a tenant across all namespaces:

```python
async def invalidate_tenant(tenant_scope: str) -> None:
    """Delete all cache entries for a tenant."""
    pattern = f"cache:{tenant_scope}:*"
    cursor = 0
    deleted_count = 0
    
    while True:
        cursor, keys = await _redis.scan(cursor, match=pattern, count=100)
        if keys:
            await _redis.delete(*keys)
            deleted_count += len(keys)
        if cursor == 0:
            break
    
    logger.info(
        "Invalidated tenant cache",
        tenant_scope=tenant_scope,
        deleted_keys=deleted_count,
    )
```

## Usage Examples

### Caching User Profile

```python
# Set cache
tenant_scope = f"{tenant_id}:{org_id}"
await cache_set(
    tenant_scope=tenant_scope,
    ns="users",
    key=str(user_id),
    value=json.dumps(user_profile),
    ttl=3600,  # 1 hour
)

# Get cache
cached = await cache_get(
    tenant_scope=tenant_scope,
    ns="users",
    key=str(user_id),
)
if cached:
    user_profile = json.loads(cached)
```

### Caching Query Results

```python
# Build a cache key from query params
query_hash = hashlib.sha256(
    json.dumps(query_params, sort_keys=True).encode()
).hexdigest()[:16]

await cache_set(
    tenant_scope=f"{tenant_id}:{org_id}",
    ns="reports",
    key=query_hash,
    value=json.dumps(results),
    ttl=1800,  # 30 minutes
)
```

### Invalidating After Mutation

```python
# After updating user profile
await cache_delete(
    tenant_scope=f"{tenant_id}:{org_id}",
    ns="users",
    key=str(user_id),
)

# Or invalidate all users for a tenant
await invalidate_namespace(
    tenant_scope=f"{tenant_id}:{org_id}",
    ns="users",
)
```

## Security Considerations

1. **Always include tenant_scope**: Never omit tenant/org IDs from cache keys. A missing scope can leak data across tenants.

2. **Validate tenant_scope format**: Ensure `tenant_scope` contains both `tenant_id` and `org_id` separated by `:`. Reject malformed scopes.

3. **Use SCAN, not KEYS**: The `KEYS` command blocks Redis. Always use `SCAN` for pattern matching in production.

4. **Log invalidations**: Track cache invalidations for audit and debugging.

5. **Set reasonable TTLs**: Don't cache tenant data indefinitely. Use expiration to limit blast radius of stale data.

## Alternative Pattern: Separate Redis Databases

Some systems use separate Redis database numbers per tenant:

```python
# Connect to tenant-specific Redis DB
redis_client = redis.Redis(db=tenant_db_number)
```

**Trade-offs**:
- **Pros**: Simpler key structure; `FLUSHDB` to clear all tenant data
- **Cons**: Limited to 16 databases (or configured max); database number mapping requires lookup; harder to share control plane cache

**When to use**: Very small number of tenants (< 10); need simple tenant-wide flush.

## Anti-patterns

- **No tenant scope in keys** — Leads to cross-tenant data leaks.
- **Using KEYS instead of SCAN** — Blocks Redis in production.
- **Hardcoding tenant IDs** — Use dependency injection to get tenant context.
- **Caching without TTL** — Stale data accumulates indefinitely.
- **Not invalidating on mutation** — Users see outdated data after updates.

## References

- Production cache implementation pattern
- [Redis SCAN documentation](https://redis.io/commands/scan) — Pattern matching without blocking
