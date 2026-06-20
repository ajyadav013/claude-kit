# Production Engineering Skills Collection

These twenty-two Claude Code skills encode production-proven engineering conventions derived from real-world Python/FastAPI and React services. Each skill was extracted from analyzing patterns across multiple production backend and frontend services, capturing canonical patterns for FastAPI microservices, async Python, Kafka/Temporal integration, multi-tenancy, database access, React frontends, observability, authentication, containerization (with granular Dockerfile/compose deep-dives), testing, data pipelines, and modernization strategies. Use them to align new projects with established patterns, audit existing services, or onboard engineers to modern Python and React development practices.

> **Where these live in this repo:** the skill folders are under [`skills/`](../../skills/) (auto-discovered by the claude-kit plugin). The links below point there.

## Skills Catalog

| Skill | Purpose | Reference |
|-------|---------|-----------|
| **backend-repo-architecture** | Canonical backend repository structure — multi-mode entrypoint (server/consumer/worker), FastAPI factory, ConnectionManager singleton, BaseDao, flat vs versioned domain layouts | [SKILL.md](../../skills/backend-repo-architecture/SKILL.md) |
| **fastapi-service-patterns** | FastAPI conventions — app factory, lifespan hooks, CustomRequestRoute logging, structured exception handling, ResponseData envelope, dependency injection, middleware stack | [SKILL.md](../../skills/fastapi-service-patterns/SKILL.md) |
| **python-dao-and-database** | Data access layer patterns — BaseDao abstraction, async SQLAlchemy 1.4 vs 2.0 session lifecycle, pagination, bulk operations, transactions, MongoDB static-class DAO | [SKILL.md](../../skills/python-dao-and-database/SKILL.md) |
| **pydantic-schema-patterns** | Pydantic v1 and v2 idioms — BaseSettings singleton, request/response schemas, field validation, ORM mode configuration, field aliasing, migration guide | [SKILL.md](../../skills/pydantic-schema-patterns/SKILL.md) |
| **async-python-patterns** | Async Python best practices — asyncio coordination (gather/wait_for/TaskGroup), cancellation handling, resource lifecycle, connection pool management, structured concurrency | [SKILL.md](../../skills/async-python-patterns/SKILL.md) |
| **kafka-config-driven** | Config-driven Kafka producer/consumer infrastructure — JSON DSL topic/consumer config, message handling abstraction, aiokafka vs confluent_kafka, GSSAPI/SASL_SSL auth | [SKILL.md](../../skills/kafka-config-driven/SKILL.md) |
| **temporal-config-driven** | Config-driven Temporal workflow/activity orchestration — JSON DSL workflow registry, worker launcher, schedule/cron management, RetryPolicy patterns | [SKILL.md](../../skills/temporal-config-driven/SKILL.md) |
| **frontend-repo-architecture** | React + Vite + TypeScript frontend structure — three organizational models (module-scoped, feature-sliced, GraphQL-based), API layer strategies, hand-written types, state management | [SKILL.md](../../skills/frontend-repo-architecture/SKILL.md) |
| **design-patterns-and-conventions** | Design conventions across repos — naming (classes/files/routes), error handling (ResponseData envelope), config hierarchy, logging structured-log patterns, code organization | [SKILL.md](../../skills/design-patterns-and-conventions/SKILL.md) |
| **multi-tenancy-patterns** | Multi-tenant isolation strategies — tenant resolution (header/JWT/session), Postgres RLS, multi-pool databases, lazy connectors, data-layer org_id tenancy | [SKILL.md](../../skills/multi-tenancy-patterns/SKILL.md) |
| **observability-and-logging** | Structured logging, OpenTelemetry tracing, Sentry error tracking, Prometheus metrics, NewRelic, request/correlation IDs, /health and /readiness endpoints | [SKILL.md](../../skills/observability-and-logging/SKILL.md) |
| **auth-and-rbac** | Authentication dependency chain (get_current_client / x-user-data header), JWT verification, RBAC role/permission enforcement, password hashing (argon2), OTP (pyotp), tenant-scoped authorization | [SKILL.md](../../skills/auth-and-rbac/SKILL.md) |
| **containerization-and-deployment** | Multi-stage Dockerfiles, docker-compose for local infra, one-image-many-roles pattern (entrypoint.py MODE dispatch), cert/keytab writing from env + kinit bootstrap, k8s health/readiness probes, CI pipelines, secrets/env hygiene | [SKILL.md](../../skills/containerization-and-deployment/SKILL.md) |
| **dockerfile-backend** | Granular multi-stage Python/FastAPI Dockerfile deep-dive — builder/runtime split, slim vs alpine trade-offs, system deps (libpq/librdkafka/krb5), layer-cache ordering, venv copy, non-root user, gunicorn+uvicorn, HEALTHCHECK | [SKILL.md](../../skills/dockerfile-backend/SKILL.md) |
| **dockerfile-frontend** | Granular React/Vite multi-stage Dockerfile deep-dive — node(alpine) build → nginx runtime, lockfile-first caching, `VITE_*`/`REACT_APP_*` build args, runtime `envsubst`, nginx SPA history fallback, security headers | [SKILL.md](../../skills/dockerfile-frontend/SKILL.md) |
| **docker-shared** | Shared Docker building blocks — base images from a private registry (tag vs `@sha256` digest pinning), `.dockerignore` conventions, shared compose fragments (YAML anchors, `x-` fields, external networks/volumes), build-arg-secret anti-pattern + BuildKit `--mount=type=secret` | [SKILL.md](../../skills/docker-shared/SKILL.md) |
| **docker-compose** | docker-compose for local dev + orchestration — postgres/redis/kafka/temporal healthchecks wired to `depends_on: condition: service_healthy`, one-image-many-roles (MODE), env-specific compose files (`.dev`/`.prod-test`/`.override`), profiles, migrator pattern | [SKILL.md](../../skills/docker-compose/SKILL.md) |
| **testing-conventions** | pytest + pytest-asyncio + conftest fixtures, async test DB setup, mocking external services (Kafka/Temporal/HTTP), Playwright/allure E2E, honest account of coverage gaps with recommended baseline | [SKILL.md](../../skills/testing-conventions/SKILL.md) |
| **alembic-migrations** | Alembic migration setup for async SQLAlchemy — alembic.ini, env.py (async engine + target_metadata), versions/ naming, autogenerate workflow, multi-tenant/multi-schema migrations | [SKILL.md](../../skills/alembic-migrations/SKILL.md) |
| **data-engineering-bigquery-gcs** | BigQuery / GCS / pandas batch data pipelines, medallion (bronze/silver/gold) layering, ETL executed inside Temporal activities (not workflows), Vertex usage, schema/partitioning conventions | [SKILL.md](../../skills/data-engineering-bigquery-gcs/SKILL.md) |
| **graphql-patterns** | Strawberry GraphQL resolvers on the backend and Apollo Client setup on the frontend — used in only a few apps, explicit about limited footprint | [SKILL.md](../../skills/graphql-patterns/SKILL.md) |
| **modernization-and-migration** | Adapting the audit recommendations — migrate Pydantic v1 to v2 and SQLAlchemy 1.4 to 2.0 (Mapped style), extract copy-pasted BaseDao/ConnectionManager/CustomRequestRoute/connection.py into shared internal library, treat reference service as golden standard, retire divergences | [SKILL.md](../../skills/modernization-and-migration/SKILL.md) |

## How to Use

1. **In a project with Claude Code:** Copy the skill folder(s) you need into your project's `.claude/skills/` directory. Claude will auto-discover them and use them when the skill's description triggers match your task.

2. **Point Claude at the skills:** If you don't want to copy files, pass the absolute path to the skill folder in your prompt: `@/path/to/skills/backend-repo-architecture` and Claude will read the SKILL.md.

3. **Trigger phrases (examples):**
   - "scaffold a new FastAPI backend" → **backend-repo-architecture**, **fastapi-service-patterns**
   - "set up SQLAlchemy DAO" → **python-dao-and-database**
   - "implement Kafka consumer" → **kafka-config-driven**
   - "add Temporal workflow" → **temporal-config-driven**
   - "build multi-tenant data isolation" → **multi-tenancy-patterns**
   - "set up React frontend" → **frontend-repo-architecture**
   - "migrate Pydantic v1 to v2" → **pydantic-schema-patterns**
   - "add observability / structured logging / tracing" → **observability-and-logging**
   - "implement authentication / RBAC / JWT verification" → **auth-and-rbac**
   - "create Dockerfile / docker-compose / k8s probes" → **containerization-and-deployment**
   - "write a Python/FastAPI backend Dockerfile / optimize image size / multi-stage build" → **dockerfile-backend**
   - "write a React/Vite frontend Dockerfile / node build + nginx serve / VITE_* build args" → **dockerfile-frontend**
   - "set up a shared base image / .dockerignore / private registry auth / compose YAML anchors" → **docker-shared**
   - "write docker-compose for local dev / healthchecks / postgres+redis+kafka+temporal" → **docker-compose**
   - "set up pytest fixtures / test DB / E2E tests" → **testing-conventions**
   - "configure Alembic / autogenerate migrations" → **alembic-migrations**
   - "build BigQuery ETL / GCS pipeline / medallion architecture" → **data-engineering-bigquery-gcs**
   - "add GraphQL resolvers / Apollo Client" → **graphql-patterns**
   - "migrate to SQLAlchemy 2.0 / extract shared library" → **modernization-and-migration**

4. **References:** Each skill includes a `references/` subdirectory with detailed evidence files showing the exact file paths, snippets, and patterns from source repositories.

## Scope and Limitations

- **Source:** These skills are derived from real-world production Python/FastAPI and React services as of June 2026. They reflect real-world conventions, including some anti-patterns that are documented for awareness.
- **Stack coverage:** Python FastAPI + SQLAlchemy (1.4 and 2.0) + Kafka + Temporal + Redis; React + Vite + TypeScript; limited MongoDB (sync pymongo); BigQuery/GCS data pipelines; Strawberry GraphQL (backend) + Apollo Client (frontend); Docker + docker-compose + k8s; pytest + pytest-asyncio + Playwright; OpenTelemetry + Sentry + Prometheus + NewRelic; argon2 + JWT + pyotp; Alembic migrations.
- **What's NOT covered:** SQLModel, Tortoise ORM, beanie/motor (async MongoDB), Django, Flask, non-Python backends. These were absent in the analyzed codebases and were deliberately not created.
