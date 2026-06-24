---
name: multi-tenancy-patterns
description: Multi-tenant isolation patterns from production Python/FastAPI services — tenant resolution (header/JWT/session), four isolation strategies (Postgres RLS, multi-pool, lazy connectors, schema-based), data-layer org_id tenancy, and tenant-scoped caching. Use when building multi-tenant SaaS architectures, designing tenant data isolation, implementing tenant context resolution, migrating from single-tenant to multi-tenant, partitioning shared databases for multi-org deployments, scoping cache keys by tenant, implementing row-level security, or designing per-tenant database pools.
---

# Multi-Tenancy Patterns

Stack-agnostic multi-tenant isolation and tenant resolution patterns derived from production services.

## When to use

- Implementing tenant resolution middleware or dependency injection
- Designing row-level security (RLS) for shared Postgres databases
- Building per-tenant database connection pooling (multi-pool or lazy connectors)
- Implementing per-tenant schema isolation with `SET search_path`
- Implementing multi-org data platform with hierarchical rollup
- Scoping Redis cache keys by tenant/org
- Migrating from single-tenant to multi-tenant architecture
- Choosing between RLS, schema-based, or separate database isolation strategies
- Implementing SSH tunnel support for local dev against bastion hosts
- Invalidating tenant-scoped cache namespaces efficiently

## Core conventions

### Tenant Resolution

**Resolution order (header → JWT → session)**: Try `X-Tenant-ID` header first, then JWT claim `tenant_id`, finally session `active_tenant_id`. Return `(tenant_id, resolved_via)` tuple. _(Production pattern)_

**Middleware dependency injection**: Use a `get_tenant_context` FastAPI dependency that returns an immutable frozen dataclass with `tenant_id`, `organization_id`, `user_id`, tenant roles, and `resolved_via`. _(Production pattern)_

**Validate lifecycle state**: After resolving tenant ID, fetch tenant from DB and verify lifecycle state is `active` or `provisioning` (reject `suspended` / `deleted`). _(Production pattern)_

**Hierarchical access checks**: `sys_admin` sees all tenants; `org_admin` validates via org path prefix; `tenant_admin` / `member` require explicit user-tenant mapping. _(Production pattern)_

### Isolation Strategy 1: PostgreSQL RLS (Shared Database)

**Session variable approach**: Call `connection_handler.set_tenant_context(tenant_id)` which executes `SET LOCAL app.tenant_id = :tid` before queries. _(Production pattern)_

**RLS policy pattern**: Enable RLS on tenant-scoped tables; create policy `USING (tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::uuid OR current_setting('app.bypass_rls', TRUE) = 'true')`. _(Production pattern)_

**Admin bypass context manager**: Use `async with bypass_rls(connection_handler)` to temporarily set `app.bypass_rls = true` for cross-tenant platform admin queries. _(Production pattern)_

**When to use**: Shared SaaS with logical isolation; one database serving all tenants; simplest infrastructure footprint; acceptable when data volume per tenant is moderate and RLS overhead is tolerable.

### Isolation Strategy 2: Multi-Pool (Config DB + Tenant DBs)

**Separate pools per database**: Maintain a `_config_pool` for control plane metadata and per-tenant pools in `_pools: dict[str, asyncpg.Pool]`. _(Production pattern)_

**Lazy pool creation**: `get_pool(tenant_id, dsn)` checks the dict; if missing, creates a new pool with `min_size` / `max_size` / `command_timeout` and caches it. _(Production pattern)_

**SSH tunnel support for dev**: If `ssh_host` and `ssh_user` are present in config, establish an `SSHTunnelForwarder` and connect the pool to `127.0.0.1:{tunnel.local_bind_port}`. _(Production pattern)_

**When to use**: Control plane database + per-tenant isolated databases; dev/staging requires SSH bastion; tenant databases are separate physical or logical databases.

### Isolation Strategy 3: Lazy Per-Tenant Connectors

**Connector registry**: A factory creates connectors from tenant datasource config; each connector wraps an `asyncpg.Pool` and tracks stats (`get_size()`, `get_idle_size()`). _(Production pattern)_

**Schema switching**: Each connector stores a `default_schema` and runs `SET search_path TO {schema}` on connection init and reset before returning connections to the pool. _(Production pattern)_

**Two connection modes**: URL-based (production from vault: `database_url`) or params-based (local dev: `host`, `port`, `database`, `user`, `password` + optional SSH). _(Production pattern)_

**When to use**: Multi-tenant with per-tenant schemas or separate databases; need to support both prod (URL) and local dev (params + SSH); want to track per-tenant pool stats.

### Isolation Strategy 4: Schema-Based (Per-Tenant Schemas)

**Schema per tenant**: Each tenant gets a dedicated PostgreSQL schema within a shared database; the connection handler sets `search_path TO {schema_name}, public` before queries. _(Production pattern)_

**Schema name validation**: Always validate schema name with regex `^[a-z0-9_]+$` before setting `search_path` to prevent SQL injection. _(Production pattern)_

**Per-tenant migrations**: Alembic migrations run per tenant schema; set `search_path` in the migration connection before running `alembic upgrade head`. _(Production pattern)_

**Schema vs RLS context**: If `tenant.schema_name` is present, call `set_schema_context(schema_name)`; otherwise fall back to `set_tenant_context(tenant_id)` for RLS. _(Production pattern)_

**When to use**: Moderate number of tenants (< 1000); stronger isolation than RLS without separate databases; per-tenant migration flexibility.

### Data-Layer Tenancy (Analytics Platform)

**org_id on every table**: Every Silver and Gold table includes `org_id STRING NOT NULL` as a mandatory column; partition by `metric_date`, cluster by `org_id, site, ...`. _(Production data platform pattern)_

**Org hierarchy**: `company → business unit → pod → store`; the `dim_org` table tracks `org_id`, `parent_org_id`, `format_codes` for hierarchical rollup. _(Production data platform pattern)_

**Medallion isolation**: Bronze → Silver (inject org_id) → Gold; in external multi-tenant mode, use separate datasets `{tenant_id}_{bronze|silver|gold}` with shared control dataset for KPI definitions. _(Production data platform pattern)_

**Row-level security for BigQuery**: Create RLS policies on `org_id` column; grant per-org service accounts access filtered by their `org_id`. _(Production data platform pattern)_

### Tenant-Scoped Caching

**Cache key namespacing**: Prefix all Redis keys with `cache:{tenant_scope}:{ns}:{key}` where `tenant_scope` is `{tenant_id}:{org_id}`. _(Production pattern)_

**Namespace invalidation**: Use `SCAN` (not `KEYS`) with pattern `cache:{tenant_scope}:{ns}:*` to clear all keys for a tenant/namespace without blocking Redis. _(Production pattern)_

**Always include tenant_scope**: Never omit tenant/org IDs from cache keys; validate `tenant_scope` format contains both IDs separated by `:`. _(Production pattern)_

**Set TTLs**: Don't cache tenant data indefinitely; use `setex` with reasonable expiration (e.g., 1-60 minutes) to limit stale data blast radius. _(Production pattern)_

## Skeleton / example

```python
# Tenant resolution
@dataclass(frozen=True)
class TenantContext:
    tenant_id: UUID
    organization_id: UUID
    user_id: UUID
    platform_role: str
    tenant_roles: list[str]
    resolved_via: str  # "header" | "jwt" | "session"

async def get_tenant_context(
    request: Request,
    session: dict = Depends(require_auth),
    connection_handler: ConnectionHandler = Depends(get_connection_handler),
) -> TenantContext:
    # Priority: X-Tenant-ID header > JWT claim > session
    tenant_id, resolved_via = await _resolve_tenant_id(request, session)
    # Fetch tenant, validate lifecycle, check access...
    await connection_handler.set_tenant_context(tenant_id)
    return TenantContext(...)

# RLS isolation
async def set_tenant_context(self, tenant_id: UUID) -> None:
    await self.session.execute(
        text("SET LOCAL app.tenant_id = :tid"),
        {"tid": str(tenant_id)},
    )

# Migration: enable RLS
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

# Multi-pool isolation
class DatabaseManager:
    def __init__(self, settings: DatabaseSettings):
        self._pools: dict[str, asyncpg.Pool] = {}
        self._config_pool: asyncpg.Pool | None = None

    async def get_pool(self, tenant_id: str, dsn: str | None = None) -> asyncpg.Pool:
        if tenant_id in self._pools:
            return self._pools[tenant_id]
        pool = await self._create_pool(dsn or self._settings.url)
        self._pools[tenant_id] = pool
        return pool

# Schema-based isolation
async def set_schema_context(self, schema_name: str) -> None:
    """Switch search_path to a tenant's dedicated schema."""
    # Validate schema name (prevent SQL injection)
    clean = schema_name.lower()
    if not re.match(r'^[a-z0-9_]+$', clean):
        raise ValueError(f"Invalid schema name: {schema_name}")
    await self.session.execute(text(f"SET LOCAL search_path TO {clean}, public"))

# Lazy connector with SSH tunnel
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
        ssh_host: str | None = None,
        ssh_user: str | None = None,
        ...
    ):
        self._use_url = bool(database_url)
        self._use_ssh = bool(ssh_host and ssh_user) and not self._use_url
        ...

    async def connect(self):
        if self._use_url:
            self._pool = await asyncpg.create_pool(dsn=self._database_url, ...)
        else:
            if self._use_ssh:
                await self._setup_ssh_tunnel()
                connect_host = '127.0.0.1'
                connect_port = self._tunnel.local_bind_port
            else:
                connect_host = self.host
                connect_port = self.port
            self._pool = await asyncpg.create_pool(
                host=connect_host, port=connect_port, ...
            )

# Data-layer org_id tenancy
CREATE TABLE analytics_silver.metrics_summary (
  org_id              STRING NOT NULL,
  metric_date         DATE NOT NULL,
  site                STRING NOT NULL,
  -- ... measures and dimensions
  _ingested_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP()
)
PARTITION BY metric_date
CLUSTER BY org_id, site, segment;

# Tenant-scoped cache
def _k(tenant_scope: str, ns: str, key: str) -> str:
    return f"cache:{tenant_scope}:{ns}:{key}"

async def cache_get(tenant_scope: str, ns: str, key: str) -> str | None:
    return await _redis.get(_k(tenant_scope, ns, key))
```

## Anti-patterns to avoid

- **Trusting tenant ID from URL path without validation** — always fetch tenant from DB and validate lifecycle state.
- **Mixing RLS and per-tenant schemas** — pick one isolation strategy per service (some services allow both but choose per-tenant dynamically).
- **Hard-coding tenant IDs** — use dependency injection or middleware to resolve tenant context per request.
- **Forgetting to reset schema/tenant context** — always reset `search_path` or session variables before returning connections to the pool.
- **Not validating schema names** — SQL injection risk; always validate with `^[a-z0-9_]+$` regex before `SET search_path`.
- **Using SSH tunnels in production** — SSH is for local dev only; prod should use direct URLs or IAM-based auth.
- **Allowing org_admin to bypass RLS without path checks** — validate org hierarchy (path prefix) for delegated admin roles.
- **Omitting org_id from Silver/Gold tables** — multi-org analytics requires org_id on every table for efficient scoping and RLS.
- **Omitting tenant scope from cache keys** — leads to cross-tenant data leaks; always include `{tenant_id}:{org_id}` in Redis keys.

## References

- [repo-evidence.md](./references/repo-evidence.md) — Real file paths and snippets from source repos
- [tenant-resolution.md](./references/tenant-resolution.md) — Resolution order, middleware, context shape, schema vs RLS context
- [isolation-strategies.md](./references/isolation-strategies.md) — RLS / multi-pool / lazy connectors / schema-based; when to use which
- [caching-patterns.md](./references/caching-patterns.md) — Tenant-scoped cache keys, namespace invalidation, Redis patterns
