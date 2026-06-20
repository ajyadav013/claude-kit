# Gap Analysis (Phase 3 + Phase 4)

This document maps the original 15 requested topics plus 8 new topics to the 18 generated skills and identifies coverage strength, internet research used, and deliberately omitted patterns.

## Coverage Matrix

| Requested Topic | Coverage | Skill(s) | Notes |
|-----------------|----------|----------|-------|
| **FastAPI patterns** | STRONG | fastapi-service-patterns, backend-repo-architecture | App factory, lifespan hooks, CustomRequestRoute, ResponseData envelope, middleware stack, dependency injection, CORS, RBAC; extracted from 16+ production services |
| **SQLAlchemy (1.4 and 2.0)** | STRONG | python-dao-and-database | BaseDao abstraction, async session lifecycle (scoped vs plain), 1.4→2.0 migration (Base, Mapped columns, relationships), pagination, transactions, bulk ops; side-by-side comparison from multiple production services |
| **Pydantic (v1 and v2)** | STRONG | pydantic-schema-patterns | BaseSettings singleton, field validators, ORM mode config, field aliasing, v1→v2 migration table (decorators, ConfigDict, pydantic_settings); extracted from multiple production services |
| **Async Python** | STRONG | async-python-patterns | asyncio coordination (gather, wait_for, TaskGroup), cancellation, resource lifecycle, connection pooling, structured concurrency; derived from real service code |
| **Kafka integration** | STRONG | kafka-config-driven | Config-driven producer/consumer (JSON DSL), aiokafka vs confluent_kafka, message handling abstraction, GSSAPI/SASL_SSL auth; extracted from multiple production services |
| **Temporal workflows** | STRONG | temporal-config-driven | Config-driven workflow/activity orchestration (JSON DSL), worker launcher, schedule/cron, RetryPolicy patterns; extracted from multiple production services |
| **Repository structure** | STRONG | backend-repo-architecture, frontend-repo-architecture | Backend: flat vs versioned domain layouts, multi-mode entrypoint (MODE dispatcher), monorepo variant; Frontend: module-scoped, feature-sliced, GraphQL-based; extracted from 19 production services |
| **Alembic migrations** | STRONG | alembic-migrations | Alembic setup for async SQLAlchemy, alembic.ini, env.py (async engine + target_metadata), versions/ naming, autogenerate workflow, multi-tenant/multi-schema migrations; extracted from multiple production services |
| **Redis patterns** | MODERATE | fastapi-service-patterns (ConnectionHandler), backend-repo-architecture (lifetime hook) | Redis client in ConnectionManager; used for caching/sessions; no dedicated skill for cache patterns, TTL strategies, pub/sub; flagged for future enhancement |
| **Multi-tenancy** | STRONG | multi-tenancy-patterns | Tenant resolution (header/JWT/session), three isolation strategies (Postgres RLS, multi-pool, lazy connectors), data-layer org_id tenancy; extracted from multiple production services |
| **Authentication patterns** | STRONG | auth-and-rbac | Authentication dependency chain (get_current_client / x-user-data header), JWT verification, RBAC role/permission enforcement, password hashing (argon2), OTP (pyotp), tenant-scoped authorization; extracted from multiple production services |
| **Testing patterns** | STRONG | testing-conventions | pytest + pytest-asyncio + conftest fixtures, async test DB setup, mocking external services (Kafka/Temporal/HTTP), Playwright E2E with Allure reporting framework, honest account of coverage gaps with recommended baseline; extracted from multiple production services |
| **Logging and observability** | STRONG | observability-and-logging | Structured logging, OpenTelemetry tracing, Sentry error tracking, Prometheus metrics, NewRelic, request/correlation IDs, /health + /readiness endpoints across FastAPI backends; extracted from multiple production services |
| **Error handling** | STRONG | fastapi-service-patterns (CustomRequestRoute exception wrapping), design-patterns-and-conventions (ResponseData envelope) | Structured exception handling, ResponseData.error(), validation error formatting, HTTP status mapping; pervasive across all FastAPI services |
| **Config management** | MODERATE | backend-repo-architecture (Settings pattern), pydantic-schema-patterns (BaseSettings singleton) | pydantic-settings, configargparse, docker_config/loaded_config singleton; no skill for multi-env config (dev/staging/prod), secret management, or config validation beyond BaseSettings |
| **Containerization and deployment** | STRONG | containerization-and-deployment | Multi-stage Dockerfiles, docker-compose for local infra, one-image-many-roles pattern (entrypoint.py MODE dispatch), cert/keytab writing from env + kinit bootstrap, k8s health/readiness probes, CI pipelines, secrets/env hygiene; extracted from multiple production services |
| **Data engineering (BigQuery/GCS)** | STRONG | data-engineering-bigquery-gcs | BigQuery / GCS / pandas batch data pipelines, medallion (bronze/silver/gold) layering, ETL executed inside Temporal activities (not workflows), Vertex usage, schema/partitioning conventions; extracted from multiple production services |
| **GraphQL** | MODERATE | graphql-patterns | Strawberry GraphQL resolvers on the backend and Apollo Client setup on the frontend; used in only a few applications — explicit about limited footprint |
| **Modernization and migration** | STRONG | modernization-and-migration | Adapting the audit recommendations — migrate Pydantic v1 to v2 and SQLAlchemy 1.4 to 2.0 (Mapped style), extract copy-pasted BaseDao/ConnectionManager/CustomRequestRoute/connection.py into shared internal library, treat reference service as golden example, retire divergences |

## Coverage Legend

- **STRONG:** Dedicated skill or major section in a skill; patterns extracted from 3+ repos with canonical examples.
- **MODERATE:** Covered in a skill but not the primary focus; patterns present in source but not deeply extracted.
- **ABSENT:** Not covered in any skill; either insufficient unique patterns in source repos or out of scope (now ZERO topics remain ABSENT after Phase 4).

## Topic → Skill Mapping

### Strongly Covered (20 topics)
1. **FastAPI patterns** → **fastapi-service-patterns** + **backend-repo-architecture**
2. **SQLAlchemy** → **python-dao-and-database**
3. **Pydantic** → **pydantic-schema-patterns**
4. **Async Python** → **async-python-patterns**
5. **Kafka** → **kafka-config-driven**
6. **Temporal** → **temporal-config-driven**
7. **Repository structure** → **backend-repo-architecture** + **frontend-repo-architecture**
8. **Multi-tenancy** → **multi-tenancy-patterns**
9. **Error handling** → **fastapi-service-patterns** + **design-patterns-and-conventions**
10. **React frontend architecture** → **frontend-repo-architecture**
11. **Alembic migrations** → **alembic-migrations**
12. **Authentication and RBAC** → **auth-and-rbac**
13. **Testing patterns** → **testing-conventions**
14. **Logging and observability** → **observability-and-logging**
15. **Containerization and deployment** → **containerization-and-deployment**
16. **Data engineering (BigQuery/GCS)** → **data-engineering-bigquery-gcs**
17. **Modernization and migration** → **modernization-and-migration**

### Moderately Covered (3 topics)
1. **Redis patterns** → ConnectionHandler in **fastapi-service-patterns**, lifetime hook in **backend-repo-architecture**
2. **Config management** → Settings in **backend-repo-architecture**, BaseSettings in **pydantic-schema-patterns**
3. **GraphQL** → **graphql-patterns** (limited footprint: used in only a few production services)

### Absent (0 topics)
All originally requested topics and Phase 4 topics are now covered.

## Internet Research Used

Internet sources were consulted **only** to confirm external API facts not present in the codebase. The codebase remained the primary source for all patterns. Specific confirmations:

1. **Temporal RetryPolicy fields** — Confirmed `initial_interval`, `backoff_coefficient`, `maximum_interval`, `maximum_attempts`, `non_retryable_error_types` from Temporal Python SDK docs to validate the JSON DSL patterns in production services. (temporal-config-driven skill)

2. **SQLAlchemy 2.0 Mapped typing** — Confirmed `Mapped[T]` (non-nullable), `Mapped[Optional[T]]` (nullable), `mapped_column()` syntax from SQLAlchemy 2.0 docs to document the 1.4→2.0 migration table. (python-dao-and-database skill)

3. **Pydantic v2 model_config and ConfigDict** — Confirmed `model_config = ConfigDict(from_attributes=True)` as the v2 replacement for `class Config: orm_mode = True` from Pydantic v2 docs. (pydantic-schema-patterns skill)

4. **aiokafka GSSAPI authentication** — Confirmed `sasl_mechanism="GSSAPI"`, `sasl_kerberos_service_name`, `security_protocol="SASL_SSL"` config structure from aiokafka docs to validate production Kafka setups. (kafka-config-driven skill)

5. **asyncio TaskGroup** — Confirmed Python 3.11+ `async with asyncio.TaskGroup()` structured concurrency API from Python docs to document the preferred pattern over manual gather/create_task. (async-python-patterns skill)

All patterns, conventions, naming, and code structures are derived from real-world production Python/FastAPI and React services. Internet research served only as a reference check for external library APIs.

## Deliberately NOT Created

The following technologies were **absent** in the analyzed production codebases and were deliberately **not** included in the skills:

1. **SQLModel** — Not used in any service; all services use SQLAlchemy ORM + Pydantic schemas separately.
2. **Tortoise ORM** — Not used in any service; SQLAlchemy is the standard ORM.
3. **beanie / motor (async MongoDB)** — Only one service uses MongoDB, which uses **sync pymongo** with a static-class DAO. No async MongoDB drivers detected.
4. **Django** — Not used; FastAPI is the standard framework.
5. **Flask** — Not used; FastAPI is the standard framework.
6. **Celery** — Not used; async work is delegated to **Temporal** or **Kafka**, not Celery queues.
7. **RabbitMQ / AWS SQS** — Not used; Kafka is the standard message broker.
8. **gRPC** — Not used; all services use HTTP/REST or Kafka for inter-service communication.
9. **Serverless (AWS Lambda, Cloud Functions)** — Not detected; services are container-based (FastAPI + Uvicorn).

Note: **GraphQL** was initially flagged as "insufficient coverage" but Phase 4 created **graphql-patterns** skill with explicit limited-footprint documentation (Strawberry backend, Apollo Client frontend).

## Recommendations for Future Enhancement

1. **Redis patterns skill** — Document cache TTL strategies, pub/sub, distributed locks, session storage, key naming conventions (currently partial coverage in fastapi-service-patterns).
2. **Config management skill** — Document multi-env config (dev/staging/prod), secret injection (env vs vault), config validation, feature flags (currently partial coverage in backend-repo-architecture).
3. **CI/CD patterns skill** — Extend containerization-and-deployment to cover GitHub Actions / GitLab CI / Jenkins pipelines, automated testing in CI, deployment strategies (blue-green, canary), rollback procedures.
4. **API versioning skill** — Extract patterns for versioning REST APIs (URL path versioning, header versioning, deprecation notices, backward compatibility strategies).

## Completed Enhancements (Phase 4)

The following recommendations from Phase 3 have been implemented:
1. **Alembic migrations skill** ✓ — Now covered in **alembic-migrations**
2. **Auth patterns skill** ✓ — Now covered in **auth-and-rbac**
3. **Testing skill** ✓ — Now covered in **testing-conventions**
4. **Observability skill** ✓ — Now covered in **observability-and-logging**
5. **Data engineering skill** ✓ — Now covered in **data-engineering-bigquery-gcs**
6. **GraphQL skill** ✓ — Now covered in **graphql-patterns**
7. **Modernization skill** ✓ — Now covered in **modernization-and-migration** (adapting audit recommendations, with reference service as the golden example)

## Validation

All 18 skills were validated against:
- **Canonical repo references** (listed in REPO-INVENTORY.md)
- **File path evidence** (all references/ subdirectories include repo-evidence.md with exact file paths)
- **Anti-pattern detection** (each skill includes an "Anti-patterns to avoid" section documenting real divergences found)
- **Version split handling** (SQLAlchemy 1.4 vs 2.0, Pydantic v1 vs v2 documented side-by-side)

No hallucinated patterns were introduced. All code snippets are representative of real production code from the analyzed repositories.

## Phase 4 Summary

Phase 4 added 8 new skills to address the moderate-coverage and absent topics from Phase 3:
- **observability-and-logging** — OpenTelemetry, Sentry, Prometheus, NewRelic, structured logging, /health + /readiness endpoints
- **auth-and-rbac** — JWT verification, RBAC, argon2, pyotp, get_current_client dependency
- **containerization-and-deployment** — Dockerfiles, docker-compose, entrypoint.py MODE dispatch, k8s probes
- **testing-conventions** — pytest-asyncio, conftest, mocking, Playwright/allure, honest coverage gap assessment
- **alembic-migrations** — Async SQLAlchemy migrations, autogenerate, multi-schema
- **data-engineering-bigquery-gcs** — Medallion ETL, BigQuery/GCS pipelines, Temporal activity-based ETL
- **graphql-patterns** — Strawberry backend, Apollo Client frontend, limited footprint
- **modernization-and-migration** — Pydantic v1→v2, SQLAlchemy 1.4→2.0, extract shared library, reference service as golden example

The modernization-and-migration skill adapts the audit's "recommended next improvements" section and treats the reference service as the canonical archetype for clean FastAPI backend patterns.
