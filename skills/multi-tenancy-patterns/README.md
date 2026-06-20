# Multi-Tenancy Patterns

Multi-tenant isolation and tenant resolution patterns derived from real-world production Python/FastAPI services and data platform architectures.

## What this skill covers

- **Tenant resolution**: Header → JWT → session priority; middleware dependency injection; lifecycle validation; schema vs RLS context
- **RLS isolation**: Postgres session variables + row-level security policies for shared SaaS
- **Multi-pool isolation**: Separate pools for config DB + per-tenant databases
- **Lazy connector isolation**: Per-tenant asyncpg pools with SSH tunnel support for dev
- **Schema-based isolation**: Per-tenant schemas with `SET search_path`; schema name validation; per-tenant migrations
- **Data-layer org_id tenancy**: Mandatory org_id on Silver/Gold tables; hierarchical org rollup; medallion architecture
- **Tenant-scoped caching**: `cache:{tenant_id}:{org_id}:{ns}:{key}` namespacing; namespace invalidation with SCAN

## Source evidence

Derived from real-world production Python/FastAPI services implementing:
- RLS isolation with tenant context middleware
- Multi-pool DatabaseManager for config + tenant DBs
- Lazy connector factory with tenant-scoped caching
- Tenant resolution with header/JWT/session priority
- Multi-org data architecture with org_id table design and BigQuery RLS

## How to apply

1. **For new multi-tenant services**: Choose an isolation strategy (RLS for shared DB, multi-pool for separate DBs, schema-based for < 1000 tenants, lazy connectors for hybrid prod/dev).
2. **For tenant resolution**: Implement the header → JWT → session priority in middleware; validate lifecycle state after lookup; decide schema vs RLS context per tenant.
3. **For data platforms**: Add `org_id STRING NOT NULL` to every Silver/Gold table; partition by time, cluster by `org_id, ...`.
4. **For caching**: Prefix Redis keys with `cache:{tenant_id}:{org_id}:{ns}:{key}`; use SCAN (not KEYS) for invalidation.

## Provenance

- **Codebase-derived**: Tenant resolution order (production middleware), RLS pattern (production migrations), multi-pool (production DatabaseManager), lazy connector (production factory), schema-based isolation (production schema migrations), org_id table design (production data platform), cache namespacing and SCAN-based invalidation (production caching).
- **Internet-confirmed**: Postgres RLS `USING` clause syntax (standard Postgres documentation), asyncpg pool API (asyncpg docs), SSH tunnel for dev (common pattern for bastion/jump hosts), BigQuery RLS on org_id (GCP documentation on row-level security), Redis SCAN vs KEYS (Redis best practices).
