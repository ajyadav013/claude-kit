# Example Patterns

Representative code examples demonstrating multi-tenancy patterns from production services.

## Example 1: RLS Isolation

**Source**: Production FastAPI service with shared-database multi-tenancy

### Tenant Context Resolution

Example from `app/common/tenant_context.py`:
```python
async def _resolve_tenant_id(
    request: Request,
    session: dict[str, object],
) -> tuple[UUID, str] | None:
    # Priority 1: explicit header
    header_val = request.headers.get("X-Tenant-ID")
    if header_val:
        return UUID(header_val), "header"

    # Priority 2: JWT claim
    if hasattr(request.state, "token_payload"):
        jwt_tid = request.state.token_payload.get("tenant_id")
        if jwt_tid:
            return UUID(str(jwt_tid)), "jwt"

    # Priority 3: session active_tenant_id
    user_data = session.get("user", {})
    active_tid = user_data.get("active_tenant_id")
    if active_tid:
        return UUID(str(active_tid)), "session"

    return None
```

**What to copy**: Resolution priority (header → JWT → session); return tuple `(tenant_id, resolved_via)`.

### RLS Session Variable

`app/connection.py`:
```python
async def set_tenant_context(self, tenant_id: UUID) -> None:
    """Set PostgreSQL session variable for RLS filtering."""
    await self.session.execute(
        text("SET LOCAL app.tenant_id = :tid"),
        {"tid": str(tenant_id)},
    )

async def set_rls_bypass(self, *, enabled: bool = True) -> None:
    """Enable or disable RLS bypass for platform admin operations."""
    value = "true" if enabled else "false"
    await self.session.execute(
        text("SET LOCAL app.bypass_rls = :val"),
        {"val": value},
    )
```

**What to copy**: `SET LOCAL app.tenant_id` for per-request tenant scoping; `app.bypass_rls` for admin bypass.

### RLS Migration

`alembic/versions/0010_add_rls_policies.py`:
```python
for table in TENANT_SCOPED_TABLES:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")

    op.execute(f"""
        CREATE POLICY tenant_isolation_{table}
        ON {table}
        FOR ALL
        USING (
            tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::uuid
            OR current_setting('app.bypass_rls', TRUE) = 'true'
        )
    """)
```

**What to copy**: RLS policy pattern with `NULLIF(current_setting(...), '')::uuid` and bypass clause.

### Bypass Context Manager

Example from `app/common/rls.py`:
```python
@asynccontextmanager
async def bypass_rls(connection_handler: ConnectionHandler) -> AsyncIterator[None]:
    try:
        await connection_handler.set_rls_bypass(enabled=True)
        yield
    finally:
        await connection_handler.set_rls_bypass(enabled=False)
```

**What to copy**: Async context manager for temporary RLS bypass.

### Schema-Based Isolation

`app/connection.py`:
```python
async def set_schema_context(self, schema_name: str) -> None:
    """Switch search_path to a tenant's dedicated schema.
    
    Sets LOCAL to ensure the setting is transaction-scoped and
    resets after commit/rollback.
    
    Args:
        schema_name: Full schema name (e.g. ``acme_payments``).
    
    Raises:
        ValueError: If schema_name contains invalid characters.
    """
    clean = schema_name.lower()
    if not re.match(r'^[a-z0-9_]+$', clean):
        raise ValueError(f"Invalid schema name: {schema_name}")
    await self.session.execute(text(f"SET LOCAL search_path TO {clean}, public"))

async def reset_schema_context(self) -> None:
    """Reset search_path to public schema only."""
    await self.session.execute(text("SET LOCAL search_path TO public"))
```

**What to copy**: Schema validation with regex before `SET search_path`; `SET LOCAL` for transaction scoping.

`alembic/versions/0018_schema_per_tenant.py`:
```python
# Migration: create per-tenant schemas
# Example: during tenant provisioning
def upgrade():
    op.execute("CREATE SCHEMA IF NOT EXISTS acme_payments")
    op.execute("GRANT USAGE ON SCHEMA acme_payments TO app_user")
    # Replicate tables in tenant schema...
```

**What to copy**: Schema creation during tenant provisioning; grant usage to app user.

---

## Example 2: Multi-Pool Isolation

**Source**: Production FastAPI service with config + per-tenant databases

### DatabaseManager

Example from `app/core/database.py`:
```python
class DatabaseManager:
    """Manages asyncpg connection pools, including tenant-scoped pools."""

    def __init__(self, settings: DatabaseSettings) -> None:
        self._settings = settings
        self._pools: dict[str, asyncpg.Pool] = {}
        self._config_pool: asyncpg.Pool | None = None

    async def initialize(self) -> None:
        """Create the config database pool at startup."""
        self._config_pool = await self._create_pool(self._settings.config_url)

    async def get_pool(self, tenant_id: str, dsn: str | None = None) -> asyncpg.Pool:
        """Get or create a connection pool for a tenant."""
        if tenant_id in self._pools:
            return self._pools[tenant_id]

        pool_dsn = dsn or self._settings.url
        pool = await self._create_pool(pool_dsn)
        self._pools[tenant_id] = pool
        logger.info("Created connection pool for tenant %s", tenant_id)
        return pool
```

**What to copy**: Separate `_config_pool` for control plane; `_pools` dict for lazy per-tenant pool creation.

---

## Example 3: Lazy Connector + SSH Tunnel

**Source**: Production FastAPI service with hybrid prod/dev multi-tenancy

### Connector Factory

Example from `app/connectors/factory.py`:
```python
@staticmethod
def from_datasource_config(datasource_config: Dict[str, Any]) -> PostgreSQLConnector:
    database_url = config.get('database_url')
    
    if database_url:
        # URL mode (production - from vault)
        connector = PostgreSQLConnector(
            database_url=database_url,
            schema=config.get('schema', 'public'),
            pool_size=config.get('pool_size', 10),
            ...
        )
    else:
        # Params mode (local dev with optional SSH)
        connector = PostgreSQLConnector(
            host=config['host'],
            port=int(config['port']),
            database=config['database'],
            user=config['user'],
            password=config['password'],
            ssh_host=config.get('ssh_host'),
            ssh_user=config.get('ssh_user'),
            ...
        )
    
    return connector
```

**What to copy**: Two connection modes (URL-based for prod, params + SSH for dev).

### PostgreSQLConnector with SSH

Example from `app/connectors/postgresql.py`:
```python
async def connect(self):
    if self._use_url:
        self._pool = await asyncpg.create_pool(
            dsn=self._database_url,
            min_size=self.min_pool_size,
            max_size=self.pool_size,
            command_timeout=self.command_timeout,
            init=self._init_connection,
        )
    else:
        if self._use_ssh:
            await self._setup_ssh_tunnel()
            connect_host = '127.0.0.1'
            connect_port = self._tunnel.local_bind_port
        else:
            connect_host = self.host
            connect_port = self.port
        
        self._pool = await asyncpg.create_pool(
            host=connect_host,
            port=connect_port,
            database=self.database,
            user=self.user,
            password=self.password,
            ...
        )

async def _init_connection(self, connection: asyncpg.Connection):
    """Initialize connection with default settings."""
    await connection.execute(f"SET search_path TO {self.default_schema}")
```

**What to copy**: SSH tunnel for dev; schema switching via `SET search_path` on init.

### Tenant-Scoped Caching

`app/core/cache.py`:
```python
def _k(tenant_scope: str, ns: str, key: str) -> str:
    # Strong tenant/org isolation: cache:{tenant:org}:{ns}:{key}
    return f"cache:{tenant_scope}:{ns}:{key}"

async def cache_get(tenant_scope: str, ns: str, key: str) -> Optional[str]:
    return await _redis.get(_k(tenant_scope, ns, key))

async def invalidate_namespace(tenant_scope: str, ns: str) -> None:
    pattern = f"cache:{tenant_scope}:{ns}:*"
    cursor = 0
    while True:
        cursor, keys = await _redis.scan(cursor, match=pattern, count=100)
        if keys:
            await _redis.delete(*keys)
        if cursor == 0:
            break
```

**What to copy**: `cache:{tenant_scope}:{ns}:{key}` namespacing; `SCAN` for namespace invalidation.

---

## Example 4: Data-Layer Tenancy

**Source**: Production data platform with multi-org architecture

### org_id Table Design

Example pattern:
```sql
CREATE TABLE analytics_silver.metrics_summary (
  -- Org isolation
  org_id              STRING NOT NULL,

  -- Time dimension
  metric_date         DATE NOT NULL,

  -- Entity keys
  region              STRING NOT NULL,
  product_id          STRING NOT NULL,
  -- ... other dimensions and measures

  _ingested_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP()
)
PARTITION BY metric_date
CLUSTER BY org_id, region, category;
```

**What to copy**: Mandatory `org_id STRING NOT NULL` on every data warehouse table; partition by time, cluster by `org_id, ...`.

### Org Hierarchy

Example pattern:
```sql
CREATE TABLE analytics_silver.dim_org (
  org_id          STRING NOT NULL,       -- PK: 'ACME_ANALYTICS', 'ACME_REPORTING', etc.
  org_name        STRING NOT NULL,
  region_codes    ARRAY<STRING>,
  parent_org_id   STRING,                -- NULL for top-level
  is_active       BOOL DEFAULT TRUE,
  ...
);
```

**What to copy**: `parent_org_id` for hierarchical rollup (company → business unit → team → project).

### BigQuery RLS

Example pattern:
```sql
CREATE ROW ACCESS POLICY org_filter
  ON analytics_silver.metrics_summary
  GRANT TO ('serviceAccount:<REDACTED>')
  FILTER USING (org_id = 'ACME_ANALYTICS');
```

**What to copy**: Row-level security on `org_id` column for BigQuery.

---

## Summary

| Pattern | Isolation Strategy | Key Mechanism | When to Use |
|---------|-------------------|---------------|-------------|
| Example 1 | RLS (shared DB) | `SET LOCAL app.tenant_id`; RLS policies on tenant_id | Shared SaaS; moderate data volume per tenant |
| Example 1 | Schema-based (shared DB) | `SET LOCAL search_path TO {schema}`; per-tenant schemas | < 1000 tenants; stronger isolation than RLS |
| Example 2 | Multi-pool | `_config_pool` + `_pools[tenant_id]` | Separate config DB + per-tenant DBs |
| Example 3 | Lazy connectors | Per-tenant asyncpg pools; SSH tunnel for dev | Hybrid prod (URL) + dev (params + SSH) |
| Example 3 | Tenant-scoped caching | `cache:{tenant:org}:{ns}:{key}` namespacing; SCAN invalidation | Multi-tenant Redis caching |
| Example 4 | Data-layer org_id | Mandatory org_id on Silver/Gold; partition/cluster | Multi-org analytics; hierarchical rollup |
