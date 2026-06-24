# Isolation Strategies

Three production patterns for tenant data isolation, each with different trade-offs.

## Strategy 1: PostgreSQL RLS (Shared Database)

**Source**: Production FastAPI service

### How It Works

All tenants share a single database. Each tenant-scoped table has a `tenant_id` column and an enabled RLS policy. Before each query, the connection handler sets a PostgreSQL session variable `app.tenant_id` to the current tenant. The RLS policy filters rows to match only that tenant.

### Implementation

#### Step 1: Add tenant_id to tables

```sql
CREATE TABLE tenant_configs (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id    UUID NOT NULL REFERENCES tenants(id),
  config_key   TEXT NOT NULL,
  config_value JSONB,
  ...
);
```

#### Step 2: Enable RLS and create policy

```sql
ALTER TABLE tenant_configs ENABLE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation_tenant_configs
ON tenant_configs
FOR ALL
USING (
    tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::uuid
    OR current_setting('app.bypass_rls', TRUE) = 'true'
);
```

The `USING` clause filters rows to:
- Match the `app.tenant_id` session variable (for normal tenant-scoped queries), OR
- Allow all rows when `app.bypass_rls` is set to `'true'` (for platform admin queries).

`NULLIF(..., '')` handles the case where the session variable is unset (returns NULL, which fails the match).

#### Step 3: Set session variable per request

```python
# In ConnectionHandler
async def set_tenant_context(self, tenant_id: UUID) -> None:
    await self.session.execute(
        text("SET LOCAL app.tenant_id = :tid"),
        {"tid": str(tenant_id)},
    )
```

`SET LOCAL` ensures the variable is scoped to the current transaction and reset after commit/rollback.

#### Step 4: Bypass RLS for admin queries

```python
from contextlib import asynccontextmanager

@asynccontextmanager
async def bypass_rls(connection_handler: ConnectionHandler):
    try:
        await connection_handler.set_rls_bypass(enabled=True)
        yield
    finally:
        await connection_handler.set_rls_bypass(enabled=False)

# Usage
async with bypass_rls(connection_handler):
    # Queries here see all tenants
    all_configs = await db.execute(select(TenantConfig)).scalars().all()
```

### Trade-offs

**Pros**:
- Simplest infrastructure — one database for all tenants
- No connection pool overhead per tenant
- Easy to query across tenants for analytics/admin dashboards
- Schema migrations apply to all tenants at once

**Cons**:
- RLS has a small query overhead (filter evaluation on every row)
- All tenants affected by DB outages or performance issues
- Harder to isolate noisy neighbors (one tenant's heavy query can slow others)
- No per-tenant backup/restore granularity

**When to use**: Shared SaaS with moderate data volume per tenant; acceptable performance overhead; strong trust in RLS policy correctness.

---

## Strategy 2: Multi-Pool (Config + Per-Tenant DBs)

**Source**: Production FastAPI service

### How It Works

A `DatabaseManager` maintains:
- A `_config_pool` for the control plane database (tenant registry, metadata, routing config)
- A `_pools` dict mapping `tenant_id → asyncpg.Pool` for per-tenant databases

Each tenant gets a dedicated database (or at least a dedicated connection pool). The manager lazily creates pools on first access.

### Implementation

```python
class DatabaseManager:
    def __init__(self, settings: DatabaseSettings) -> None:
        self._settings = settings
        self._pools: dict[str, asyncpg.Pool] = {}
        self._config_pool: asyncpg.Pool | None = None

    async def initialize(self) -> None:
        """Create the config database pool at startup."""
        self._config_pool = await asyncpg.create_pool(
            self._settings.config_url,
            min_size=self._settings.min_pool_size,
            max_size=self._settings.max_pool_size,
            command_timeout=self._settings.command_timeout,
        )

    @property
    def config_pool(self) -> asyncpg.Pool:
        if self._config_pool is None:
            raise RuntimeError("Config database pool not initialized")
        return self._config_pool

    async def get_pool(self, tenant_id: str, dsn: str | None = None) -> asyncpg.Pool:
        """Get or create a connection pool for a tenant."""
        if tenant_id in self._pools:
            return self._pools[tenant_id]

        pool_dsn = dsn or self._settings.url
        pool = await asyncpg.create_pool(
            pool_dsn,
            min_size=self._settings.min_pool_size,
            max_size=self._settings.max_pool_size,
            command_timeout=self._settings.command_timeout,
        )
        self._pools[tenant_id] = pool
        logger.info("Created connection pool for tenant %s", tenant_id)
        return pool

    async def close(self) -> None:
        """Close all connection pools."""
        for tenant_id, pool in self._pools.items():
            await pool.close()
        self._pools.clear()

        if self._config_pool:
            await self._config_pool.close()
            self._config_pool = None
```

### Usage in Handlers

```python
# Get config pool (for tenant lookup, routing)
async with db_manager.config_pool.acquire() as conn:
    tenant_config = await conn.fetchrow(
        "SELECT dsn FROM tenant_registry WHERE tenant_id = $1", tenant_id
    )

# Get tenant pool (for tenant-scoped queries)
tenant_pool = await db_manager.get_pool(tenant_id, dsn=tenant_config['dsn'])
async with tenant_pool.acquire() as conn:
    results = await conn.fetch("SELECT * FROM orders WHERE ...")
```

### Trade-offs

**Pros**:
- Strong isolation — each tenant has a separate database (or at least separate pool)
- Independent scaling — add resources to high-traffic tenants
- Per-tenant backup/restore, disaster recovery
- No RLS overhead

**Cons**:
- Connection pool overhead — each tenant pool consumes memory
- More complex infrastructure — multiple databases to manage
- Cross-tenant queries require federated queries or separate ETL
- Schema migrations must run per tenant

**When to use**: Dedicated tenant databases; high-traffic tenants needing independent scaling; compliance requirements for data isolation.

---

## Strategy 3: Lazy Connectors (Hybrid Prod + Dev)

**Source**: Production FastAPI service

### How It Works

A `ConnectorFactory` creates `PostgreSQLConnector` instances from tenant config. Each connector wraps an asyncpg pool and supports:
- **URL mode** (production): `database_url` from vault (e.g., Cloud SQL, RDS)
- **Params mode** (local dev): `host`, `port`, `database`, `user`, `password` + optional SSH tunnel to bastion

The factory lazily creates connectors per tenant. Each connector tracks pool stats (`get_size()`, `get_idle_size()`).

### Implementation

#### Connector Factory

```python
class ConnectorFactory:
    @staticmethod
    def from_datasource_config(datasource_config: Dict[str, Any]) -> PostgreSQLConnector:
        database_url = datasource_config.get('database_url')
        
        # Validate database_url format
        if database_url and not database_url.startswith(('postgresql://', 'postgres://')):
            database_url = None  # Fall back to params mode
        
        if database_url:
            # Production: URL from vault
            return PostgreSQLConnector(
                database_url=database_url,
                schema=config.get('schema', 'public'),
                pool_size=config.get('pool_size', 10),
                min_pool_size=config.get('min_pool_size', 2),
                command_timeout=config.get('command_timeout', 60),
            )
        else:
            # Local dev: params + optional SSH
            return PostgreSQLConnector(
                host=config['host'],
                port=int(config['port']),
                database=config['database'],
                user=config['user'],
                password=config['password'],
                schema=config.get('schema', 'public'),
                # SSH tunnel for bastion/jump host
                ssh_host=config.get('ssh_host'),
                ssh_port=int(config.get('ssh_port', 22)),
                ssh_user=config.get('ssh_user'),
                ssh_key_path=config.get('ssh_key_path'),
                pool_size=config.get('pool_size', 10),
                ...
            )
```

#### PostgreSQLConnector

```python
class PostgreSQLConnector:
    def __init__(
        self,
        database_url: str | None = None,
        host: str | None = None,
        port: int = 5432,
        database: str | None = None,
        user: str | None = None,
        password: str | None = None,
        schema: str = "public",
        pool_size: int = 10,
        min_pool_size: int = 2,
        command_timeout: int = 60,
        # SSH tunnel (only used with params mode)
        ssh_host: str | None = None,
        ssh_port: int = 22,
        ssh_user: str | None = None,
        ssh_key_path: str | None = None,
        ssh_password: str | None = None,
    ):
        self._use_url = bool(database_url)
        self._use_ssh = bool(ssh_host and ssh_user) and not self._use_url
        self._database_url = database_url
        self.host = host
        self.port = port
        self.database = database
        self.user = user
        self.password = password
        self.default_schema = schema
        self._pool: asyncpg.Pool | None = None
        self._tunnel: SSHTunnelForwarder | None = None
        ...

    async def connect(self):
        if self._pool is not None:
            return  # Already connected

        if self._use_url:
            # URL mode (production)
            self._pool = await asyncpg.create_pool(
                dsn=self._database_url,
                min_size=self.min_pool_size,
                max_size=self.pool_size,
                command_timeout=self.command_timeout,
                init=self._init_connection,
            )
        else:
            # Params mode (with optional SSH tunnel)
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
                min_size=self.min_pool_size,
                max_size=self.pool_size,
                command_timeout=self.command_timeout,
                init=self._init_connection,
            )

    async def _init_connection(self, connection: asyncpg.Connection):
        """Initialize connection with default schema."""
        await connection.execute(f"SET search_path TO {self.default_schema}")

    async def _reset_connection(self, connection: asyncpg.Connection):
        """Reset connection state before returning to pool."""
        await connection.execute(f"SET search_path TO {self.default_schema}")
```

#### SSH Tunnel Setup

```python
async def _setup_ssh_tunnel(self):
    def create_tunnel():
        tunnel = SSHTunnelForwarder(
            (self.ssh_host, self.ssh_port),
            ssh_username=self.ssh_user,
            ssh_pkey=self.ssh_key_path if self.ssh_key_path else None,
            ssh_password=self.ssh_password if self.ssh_password else None,
            remote_bind_address=(self.host, self.port),
            local_bind_address=('127.0.0.1', 0),  # Auto-assign local port
        )
        tunnel.start()
        return tunnel
    
    self._tunnel = await asyncio.get_event_loop().run_in_executor(None, create_tunnel)
```

### Query Execution with Schema Switching

```python
async def fetch_all(
    self,
    query: str,
    params: list | None = None,
    schema: str | None = None
) -> list[dict]:
    if self._pool is None:
        await self.connect()
    
    connection = await self._pool.acquire()
    
    try:
        # Switch schema if specified (per-request override)
        if schema:
            await connection.execute(f"SET search_path TO {schema}")
        
        if params:
            rows = await connection.fetch(query, *params)
        else:
            rows = await connection.fetch(query)
        
        return [dict(row) for row in rows]
    finally:
        await self._reset_connection(connection)  # Reset to default schema
        await self._pool.release(connection)
```

### Pool Stats

```python
def get_stats(self) -> dict[str, Any]:
    if not self._pool:
        return {"status": "not_connected"}
    
    return {
        "status": "connected",
        "connection_mode": "url" if self._use_url else "params",
        "size": self._pool.get_size(),
        "free_size": self._pool.get_idle_size(),
        "ssh_tunnel": self._use_ssh,
        "default_schema": self.default_schema,
    }
```

### Trade-offs

**Pros**:
- Flexible for hybrid environments (prod URL + dev SSH)
- Per-tenant schema switching without multiple pools
- Tracks pool stats per tenant
- SSH tunnel auto-starts and auto-closes

**Cons**:
- More complex connection logic (URL vs params, SSH tunnel management)
- SSH tunnel overhead for local dev
- Schema switching requires careful reset logic to avoid leaks

**When to use**: Hybrid prod (direct URLs) + dev (SSH bastion); per-tenant schemas in a shared database; need to track per-tenant pool stats.

---

## Strategy 4: Schema-Based Isolation (Per-Tenant Schemas)

**Source**: Production FastAPI service (migration from RLS to schemas)

### How It Works

Each tenant gets a dedicated PostgreSQL schema within a shared database. The connection handler sets `search_path` to the tenant's schema before queries. Tables exist in each schema with identical structure but isolated data.

### Implementation

#### Step 1: Create tenant-specific schemas

```sql
-- During tenant provisioning
CREATE SCHEMA acme_payments;
GRANT USAGE ON SCHEMA acme_payments TO app_user;
GRANT ALL ON ALL TABLES IN SCHEMA acme_payments TO app_user;

-- Replicate table structure in tenant schema
CREATE TABLE acme_payments.orders (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  order_number TEXT NOT NULL,
  created_at   TIMESTAMP DEFAULT NOW(),
  ...
);
```

#### Step 2: Set search_path per request

```python
# In ConnectionHandler
async def set_schema_context(self, schema_name: str) -> None:
    """Switch search_path to a tenant's dedicated schema.
    
    Sets LOCAL to ensure the setting is transaction-scoped and
    resets after commit/rollback.
    
    Args:
        schema_name: Full schema name (e.g. ``acme_payments``).
    
    Raises:
        ValueError: If schema_name contains invalid characters.
    """
    # Validate schema name (alphanumeric + underscore only)
    clean = schema_name.lower()
    if not re.match(r'^[a-z0-9_]+$', clean):
        raise ValueError(f"Invalid schema name: {schema_name}")
    await self.session.execute(text(f"SET LOCAL search_path TO {clean}, public"))

async def reset_schema_context(self) -> None:
    """Reset search_path to public schema only."""
    await self.session.execute(text("SET LOCAL search_path TO public"))
```

#### Step 3: Tenant routing in middleware

```python
async def get_tenant_context(
    request: Request,
    session: dict = Depends(require_auth),
    connection_handler: ConnectionHandler = Depends(get_connection_handler),
) -> TenantContext:
    # Resolve tenant_id...
    tenant = await db.fetch_tenant(tenant_id)
    
    # Set schema context (instead of RLS)
    if tenant.schema_name:
        await connection_handler.set_schema_context(tenant.schema_name)
    else:
        # Fallback to RLS if schema not yet provisioned
        await connection_handler.set_tenant_context(tenant_id)
    
    return TenantContext(...)
```

#### Step 4: Schema migrations per tenant

```python
async def migrate_tenant_schema(tenant_id: UUID, schema_name: str):
    """Apply alembic migrations to a tenant's schema."""
    # Set search_path for the migration connection
    await connection.execute(f"SET search_path TO {schema_name}, public")
    
    # Run migrations
    alembic_cfg = Config("alembic.ini")
    alembic_cfg.set_main_option("script_location", "alembic_tenant")
    command.upgrade(alembic_cfg, "head")
    
    logger.info("Migrated tenant schema", tenant_id=tenant_id, schema=schema_name)
```

### Trade-offs

**Pros**:
- Stronger isolation than RLS (schema-level permissions)
- No RLS overhead on queries
- Easier to export/import tenant data (pg_dump per schema)
- Per-tenant schema migrations possible (gradual rollout)
- Cross-tenant queries still possible with schema-qualified names

**Cons**:
- Schema proliferation (one schema per tenant)
- Migrations must run per tenant (slower at scale)
- More complex backup/restore orchestration
- Connection pool shared across tenants (noisy neighbor risk remains)
- Schema limit of ~1000 schemas per database (practical, not hard limit)

**When to use**: Moderate number of tenants (< 1000); need stronger isolation than RLS but not separate databases; want per-tenant migration flexibility.

---

## Data-Layer Tenancy (org_id on Every Table)

**Source**: Production data platform architecture

### How It Works

In a multi-org data platform, every Silver and Gold table includes `org_id STRING NOT NULL`. This enables:
- Efficient query scoping (`WHERE org_id = ...`)
- Row-level security (RLS policies on `org_id`)
- Hierarchical rollup (company → business unit → pod → store)

### Table Design

```sql
CREATE TABLE analytics_silver.metrics_summary (
  -- Org isolation
  org_id              STRING NOT NULL,

  -- Time dimension
  metric_date         DATE NOT NULL,

  -- Entity keys
  site                STRING NOT NULL,
  article             STRING NOT NULL,
  segment             STRING,

  -- Measures
  billing_qty         FLOAT64,
  gross_sales         FLOAT64,
  net_sales           FLOAT64,
  cost                FLOAT64,
  gross_margin        FLOAT64,

  -- Metadata
  _ingested_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP()
)
PARTITION BY metric_date
CLUSTER BY org_id, site, segment;
```

### Org Hierarchy

```sql
CREATE TABLE analytics_silver.dim_org (
  org_id          STRING NOT NULL,       -- PK: 'ACME_RETAIL', 'ACME_WHOLESALE', etc.
  org_name        STRING NOT NULL,
  format_codes    ARRAY<STRING>,         -- Format codes this org owns
  parent_org_id   STRING,                -- NULL for top-level
  is_active       BOOL DEFAULT TRUE,
  created_at      TIMESTAMP,
  updated_at      TIMESTAMP
);
```

Example hierarchy:
```
ACME (parent_org_id = NULL)
├── ACME_RETAIL (parent_org_id = 'ACME')
│   ├── ACME_RETAIL_ANALYTICS
│   └── ACME_RETAIL_APPAREL
└── ACME_WHOLESALE (parent_org_id = 'ACME')
```

### Medallion Architecture

```
Bronze (raw)
  └─> Silver (org_id injected)
      └─> Gold (aggregated with org_id)
```

In external multi-tenant mode:
```
analytics_{tenant_id}_bronze
analytics_{tenant_id}_silver
analytics_{tenant_id}_gold
analytics_control  (shared: KPI definitions, thresholds, agent config)
```

### BigQuery RLS

```sql
CREATE ROW ACCESS POLICY org_filter_metrics_summary
ON analytics_silver.metrics_summary
GRANT TO ('serviceAccount:app@example.iam.gserviceaccount.com')
FILTER USING (org_id = 'ACME_RETAIL');
```

Each org gets a dedicated service account with RLS policies scoping them to their `org_id`.

### Trade-offs

**Pros**:
- Efficient query scoping (partition + cluster)
- Works with BigQuery RLS
- Hierarchical rollup for reporting
- Single pipeline for all orgs (Bronze → Silver → Gold)

**Cons**:
- `org_id` must be correct on every row (data quality risk)
- Cross-org analytics require `WHERE org_id IN (...)` or bypass RLS
- Partitioning/clustering must account for `org_id` cardinality

**When to use**: Multi-org data platforms; hierarchical reporting; shared analytics infrastructure.

---

## Comparison Table

| Strategy | Isolation Level | Infra Complexity | Query Overhead | Cross-Tenant Queries | When to Use |
|----------|----------------|------------------|----------------|---------------------|-------------|
| RLS | Logical (shared DB) | Low | Low (RLS filter) | Easy (bypass RLS) | Shared SaaS; moderate data per tenant |
| Multi-pool | Physical (separate DBs) | High | None | Hard (federated) | Dedicated DBs; independent scaling |
| Lazy connectors | Schema-level | Medium | Low (schema switch) | Medium (per schema) | Hybrid prod/dev; per-tenant schemas |
| Schema-based | Schema-level (shared DB) | Medium | None | Medium (schema-qualified) | < 1000 tenants; per-tenant migration flexibility |
| org_id | Logical (column filter) | Low | Low (cluster by org_id) | Easy (WHERE org_id IN) | Multi-org analytics; hierarchical rollup |
