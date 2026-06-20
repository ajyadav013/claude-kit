# Technology Coverage Matrix

This document maps the technology stack coverage provided by the skills collection. The skills are derived from real-world production Python/FastAPI and React services, covering modern async patterns, data engineering, observability, and full-stack development.

## Technology Stack Coverage

The skills collection covers the following technology areas:

### Backend (Python/FastAPI)
- **FastAPI:** 0.104 - 0.121, modern async patterns, dependency injection, middleware
- **SQLAlchemy:** 1.4 and 2.0, async engines, connection pooling, DAO/Repository patterns
- **Alembic:** Async migrations, autogenerate workflows, multi-schema support
- **Pydantic:** v1 and v2, field validators, settings management, serialization
- **Async I/O:** asyncio, aiohttp, asyncpg, aiokafka patterns
- **Database:** PostgreSQL (asyncpg), MongoDB (pymongo), multi-tenancy (RLS, multi-pool, lazy connectors)

### Message Queues & Workflow
- **Kafka:** aiokafka, confluent_kafka, GSSAPI/SASL_SSL configurations
- **Temporal:** temporalio workflows, activities, config-driven task orchestration

### Data Engineering
- **BigQuery/GCS:** Medallion ETL (bronze/silver/gold), batch processing
- **Vertex AI:** ML pipeline integration

### Observability & Operations
- **Logging:** OpenTelemetry, structured logging, correlation IDs
- **Monitoring:** Sentry, Prometheus, NewRelic integration
- **Health Checks:** /health and /readiness endpoints

### Authentication & Security
- **Auth:** JWT, argon2 password hashing, pyotp (TOTP/2FA)
- **RBAC:** Role-based access control, permission enforcement
- **Multi-tenancy:** Row-level security (RLS), tenant isolation patterns

### Frontend (React/TypeScript)
- **React:** 18-19, Vite builds, TypeScript
- **State Management:** zustand, Context API, persistence
- **API Layer:** react-query, Apollo GraphQL, axios, fetch wrappers with token refresh
- **UI Libraries:** Radix UI, Headless UI, Tailwind CSS
- **Routing:** react-router-dom
- **Forms:** React Hook Form, zod validation
- **Mobile:** Capacitor (hybrid apps)
- **GraphQL:** Apollo Client, schema-driven development, SSR
- **Testing:** Mock Service Worker (msw), E2E testing

### Testing & Quality
- **Unit/Integration:** pytest, pytest-asyncio, conftest fixtures, async test DB
- **E2E:** Playwright with Allure reporting
- **Mocking:** unittest.mock, pytest fixtures, msw

### DevOps & Containerization
- **Docker:** Multi-stage Dockerfiles, docker-compose
- **Kubernetes:** Health/readiness probes, configuration
- **Deployment:** Multi-environment patterns, feature flags

### GraphQL
- **Backend:** Strawberry resolvers
- **Frontend:** Apollo Client, code generation

### Additional Libraries
- **Redis:** Caching, session storage
- **HTTP/File Transfer:** Async HTTP, FTP, SFTP with retry/circuit-breaker patterns

## Pattern Categories Covered

### Backend Service Patterns
- **Repository Structure:**
  - Flat domain layout (30-40+ parallel domain modules)
  - Versioned layout (v1/v2 side-by-side domains)
  - Monorepo (apps/packages/services split)
  
- **Multi-Deployment:** Single codebase with environment-based feature gating (SERVER_TYPE dispatch)

- **Data Access Patterns:**
  - BaseDao with advanced filtering (QueryFilter DSL, ComparisonOperator enums)
  - Repository pattern with lazy initialization
  - Static-class MongoDB DAO with bulk operations
  - Raw asyncpg without ORM for minimal overhead

- **Connection Management:**
  - async_scoped_session with current_task scopefunc
  - Multi-pool DatabaseManager with tenant resolution
  - Lazy per-tenant connectors with connection pooling

- **Multi-Tenancy Approaches:**
  - Postgres Row-Level Security (RLS) with set_tenant_context
  - Multi-pool with DatabaseManager + TenantResolver + SSH tunnel support
  - Lazy per-tenant connectors

- **Message Queue Patterns:**
  - Config-driven Kafka topic/consumer setup (JSON DSL)
  - GSSAPI/SASL_SSL enterprise configurations
  - aiokafka, confluent_kafka, kafka-python usage patterns

- **Workflow Orchestration:**
  - Config-driven Temporal workflow registry
  - Worker launcher patterns
  - Activity-based ETL pipelines

### Frontend Patterns
- **Module-Scoped Layout:** Monolithic with parallel feature modules
- **Feature-Sliced Architecture:** Cross-cutting features, lazy-loaded pages
- **Schema-Driven (GraphQL):** Apollo Client, SSR, type generation

### Testing Patterns
- pytest with pytest-asyncio for async services
- conftest fixtures for test setup
- Async test database patterns
- Playwright E2E with Allure Framework reporting
- Mock Service Worker for API mocking

### Data Engineering Patterns
- Medallion architecture (bronze/silver/gold layers)
- ETL in Temporal activities
- BigQuery batch processing
- Vertex AI integration

## Skill-to-Technology Mapping

The following table maps each major technology area to the skills that provide coverage:

| Technology Area | Key Skills Covering This Area |
|----------------|-------------------------------|
| **FastAPI Service Architecture** | `fastapi-service-patterns`, `backend-repo-structure`, `multi-deployment-patterns` |
| **SQLAlchemy (1.4 & 2.0)** | `sqlalchemy-dao-patterns`, `connection-management`, `async-db-patterns` |
| **Alembic Migrations** | `alembic-migration-patterns`, `async-migration-workflows` |
| **Pydantic (v1 & v2)** | `pydantic-validation-patterns`, `pydantic-v1-to-v2-migration` |
| **Async Python** | `async-patterns`, `asyncio-best-practices`, `async-db-patterns` |
| **Kafka** | `kafka-patterns`, `kafka-enterprise-config`, `message-queue-patterns` |
| **Temporal** | `temporal-workflow-patterns`, `temporal-activity-patterns`, `config-driven-orchestration` |
| **Multi-Tenancy** | `multi-tenancy-rls`, `multi-pool-patterns`, `tenant-isolation` |
| **BigQuery/GCS** | `bigquery-etl-patterns`, `medallion-architecture`, `data-pipeline-patterns` |
| **Authentication** | `jwt-auth-patterns`, `rbac-patterns`, `password-hashing-patterns`, `totp-2fa` |
| **Observability** | `opentelemetry-integration`, `structured-logging`, `health-check-patterns` |
| **React/TypeScript** | `react-service-patterns`, `frontend-architecture-patterns`, `state-management-patterns` |
| **GraphQL** | `graphql-backend-patterns`, `apollo-client-patterns`, `schema-driven-development` |
| **Testing** | `pytest-patterns`, `playwright-e2e-patterns`, `test-fixture-patterns` |
| **Containerization** | `docker-patterns`, `kubernetes-patterns`, `multi-stage-builds` |
| **MongoDB** | `mongodb-dao-patterns`, `pymongo-patterns` |

## Version Support

The skills support both legacy and modern versions to accommodate migration scenarios:

- **SQLAlchemy:** 1.4 (legacy) and 2.0 (modern async patterns)
- **Pydantic:** v1 (validator decorators) and v2 (field_validator, ConfigDict)
- **React:** 18-19 with modern hooks and concurrent features
- **FastAPI:** 0.104 - 0.121+ covering modern dependency injection and async patterns

## Architecture Patterns Emphasized

1. **Clean Architecture:** Domain-driven design with clear separation of concerns
2. **Async-First:** Modern Python async patterns with proper connection management
3. **Config-Driven:** JSON DSL for Kafka topics, Temporal workflows, feature flags
4. **Type Safety:** Full Pydantic validation, TypeScript strict mode, GraphQL schemas
5. **Observability:** Structured logging, distributed tracing, health checks built-in
6. **Security:** JWT/OAuth, RBAC, password hashing (argon2), multi-tenancy isolation
7. **Testability:** pytest with async support, fixture patterns, E2E automation
