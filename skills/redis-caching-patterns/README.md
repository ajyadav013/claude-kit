# redis-caching-patterns

Production Redis caching conventions for multi-tenant services, extracted from real backend microservices.

## What this covers

- **Multi-tenant namespacing**: `{tenant_id}:{namespace}:{key}` format for strict tenant isolation
- **CacheManager with fallback**: Redis-primary + in-memory TTL cache when Redis is unavailable
- **BaseRedis abstraction**: prefix-scoped, tenant-aware cache handle for DRY feature caches
- **Configurable TTL strategies**: global defaults + per-namespace overrides via settings
- **Graceful degradation**: wrap all Redis ops in `try/except`, return `None` on failures
- **SCAN-based invalidation**: safe namespace/tenant invalidation without blocking Redis
- **Pipelined bulk delete**: batch delete for small sets, SCAN+pipeline for large sets
- **Background invalidation**: `asyncio.create_task()` for non-blocking cache clears
- **Health checks**: Redis ping with fallback detection

## Origin

Derived from production Python/FastAPI microservices handling multi-tenant authorization, analytics caching, and feature filters. Genericized for public reuse — no internal service names, repos, or cloud identifiers included.

## Structure

- `SKILL.md` — the full skill with conventions, skeleton code, anti-patterns, and cross-links
- `references/cache-manager-and-fallback.md` — CacheManager, in-memory fallback, initialization
- `references/namespacing-and-invalidation.md` — TenantRedis, key formatting, SCAN patterns
- `references/repo-evidence.md` — genericized code snippets grounding the patterns

## Usage

Read this skill when implementing caching in a multi-tenant service, designing cache invalidation, or handling Redis failures gracefully. Cross-link with `multi-tenancy-patterns` for tenant context and `async-python-patterns` for asyncio task scheduling.
