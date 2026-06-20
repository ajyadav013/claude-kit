# node-express-service

Production-grounded Express.js service architecture skill covering app factory patterns, multi-mode server dispatch, hierarchical configuration, middleware composition, and error handling.

## What this covers

This skill encodes patterns from real production Node.js backend services running Express.js in multi-tenant, role-based architectures. It captures:

- **App factory with server-type dispatch**: one codebase, multiple server modes (platform API, admin panel, internal services, webhooks)
- **Hierarchical configuration with convict**: env-driven config with format validation and strict schema enforcement
- **Module-alias path mapping**: clean imports via `@controllers`, `@services`, `@utils` aliases
- **Swagger-jsdoc API documentation**: auto-generated OpenAPI 3.0 specs with server-type-specific base paths
- **Custom middleware suite**:
  - Ingress header parser (`x-user-data` → `userId`/`roleIds`/`orgId`)
  - Request logger with nanoid request IDs, response timing, and password masking
  - Redis-backed sessions with connect-redis
  - Session tracking with active session limits
  - Connect-timeout for request timeouts
  - Basic auth for internal routes
  - Passport.js strategies
- **Error handling with statusCode convention**: custom error middleware that logs, captures to Sentry, and returns structured JSON errors
- **Observability wiring**: Sentry error tracking, New Relic APM, structured logging

All patterns are derived from real production services (no names disclosed) and genericized for reusability.

## When to use

Use when building or refactoring a Node.js backend service that needs:
- Multi-mode dispatch (API + admin + internal + webhooks from one codebase)
- Role-based routing or multi-tenancy
- Redis-backed sessions with session limits
- Hierarchical, validated configuration
- Clean import paths without deep relative imports
- Swagger API docs with conditional base paths
- Request/response logging with unique request IDs
- Sentry + New Relic integration

## Structure

- `SKILL.md` — the core skill definition with triggers, conventions, skeleton code, and anti-patterns
- `references/app-factory-and-mode-dispatch.md` — app factory, server-type dispatch, health checks
- `references/config-and-module-alias.md` — convict config, module-alias setup
- `references/middleware-patterns.md` — ingress parser, request logger, session tracking, error handling
- `references/repo-evidence.md` — short, genericized snippets from real codebases

## Cross-references

- [backend-repo-architecture](../backend-repo-architecture/SKILL.md) — the Python/FastAPI analog for backend architecture patterns
- [fastapi-service-patterns](../fastapi-service-patterns/SKILL.md) — FastAPI app factory, lifespan, middleware, DI
