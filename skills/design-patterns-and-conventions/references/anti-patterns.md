# Anti-Patterns Catalogue

Comprehensive list of anti-patterns observed across production Python/FastAPI services, with the issue and the recommended fix for each.

---

## 1. Hardcoded Secrets in Dockerfiles

**Issue:** Embedding sensitive credentials (API tokens, Azure DevOps tokens, passwords) directly in Dockerfiles or application config defaults.

**Risk:** Secrets leak into version control, container registries, and CI/CD logs; accessible to anyone with repo or image access.

**Examples:**
- Azure DevOps personal access token embedded in Dockerfile ARG/ENV
- Hardcoded API tokens in `config/docker_config.py` defaults (default values instead of required environment variables)

**Fix:**
- NEVER hardcode secrets in Dockerfiles or config defaults.
- Use environment variables or secret management systems (Kubernetes Secrets, AWS Secrets Manager, HashiCorp Vault).
- Mark sensitive fields as required (no defaults) in Pydantic Settings:
  ```python
  class Settings(BaseSettings):
      API_TOKEN: str  # No default; must come from env
      AZURE_DEVOPS_TOKEN: str  # No default
  ```
- Use Docker build secrets or BuildKit `--secret` for build-time secrets (never ARG/ENV).

**Example (secure):**
```dockerfile
# Dockerfile
# DO NOT: ARG AZURE_DEVOPS_TOKEN=<token>
# DO: Pass via --secret and mount at build time
RUN --mount=type=secret,id=azure_token cat /run/secrets/azure_token
```

---

## 2. CORS allow_origins=["*"] in Production

**Issue:** Allowing requests from any origin (`allow_origins=["*"]`) disables CORS protection and exposes APIs to cross-site attacks.

**Risk:** Any malicious website can make authenticated requests to your API from a user's browser.

**Examples:**
- Several repos (exact files not captured; observed in middleware setup across repos)

**Fix:**
- Restrict `allow_origins` to known, trusted domains:
  ```python
  from fastapi.middleware.cors import CORSMiddleware

  app.add_middleware(
      CORSMiddleware,
      allow_origins=["https://example.com", "https://app.example.com"],  # Specific origins
      allow_credentials=True,
      allow_methods=["*"],
      allow_headers=["*"],
  )
  ```
- Load allowed origins from configuration (env var `ALLOWED_ORIGINS="https://example.com,https://app.example.com"`).
- NEVER use `["*"]` in production; only acceptable in local dev.

---

## 3. Sync Cloud Clients in Async Handlers

**Issue:** Calling synchronous blocking I/O (BigQuery, GCS, sync HTTP clients) inside async FastAPI route handlers or async functions.

**Risk:** Blocks the event loop, starving other concurrent requests; degrades performance and can cause timeouts.

**Examples:**
- BigQuery client (sync `google-cloud-bigquery`) called in async routes
- GCS client (sync `google-cloud-storage`) called in async routes
- Sync `requests` library used instead of `httpx` or `aiohttp`

**Fix:**
- Use async clients:
  - BigQuery: `google-cloud-bigquery` has async support via `aio` module or use `aiogoogle`
  - GCS: `google-cloud-storage` async or `aiofiles` + `httpx` for direct REST
  - HTTP: `httpx.AsyncClient` or `aiohttp.ClientSession`
- If async client not available, use `asyncio.to_thread()` or `run_in_executor()`:
  ```python
  import asyncio
  from google.cloud import bigquery

  client = bigquery.Client()

  async def query_bigquery(query: str):
      loop = asyncio.get_event_loop()
      result = await loop.run_in_executor(None, client.query, query)
      return result
  ```
- Prefer async-first libraries in new code.

---

## 4. Copy-Pasted DAO/Connection Code Across Services

**Issue:** `BaseDao` and `connection.py` duplicated across multiple services instead of being a shared library.

**Risk:** Bug fixes and improvements must be manually copied; inconsistencies emerge; maintenance burden grows.

**Examples:**
- `app/connection.py` duplicated nearly identically across multiple services
- BaseDao pattern repeated in multiple codebases

**Fix:**
- Extract common DAO, connection manager, and utilities into a shared Python package (internal PyPI or git submodule).
- Publish the shared package and import it in all services:
  ```python
  # pyproject.toml
  [dependencies]
  mycompany-common = {git = "https://github.com/your-org/common-lib.git"}

  # app/connection.py
  from mycompany_common.connection import ConnectionManager, get_connection_handler_for_app
  ```
- Apply DRY: shared code belongs in a shared lib.

---

## 5. No Transaction Rollback / No Unit-of-Work Pattern

**Issue:** Manual `await session.commit()` scattered throughout code; no automatic rollback on exception.

**Risk:** Partial commits on error; data corruption; inconsistent state.

**Examples:**
- DAO methods with explicit `await self.session.commit()` and no rollback handling
- No try/except wrapping transaction boundaries

**Fix:**
- Use a unit-of-work pattern or context manager that commits on success and rolls back on exception:
  ```python
  async def get_connection_handler_for_app():
      connection_handler = ConnectionHandler()
      try:
          yield connection_handler
          await connection_handler.session.commit()  # Commit on success
      except Exception:
          await connection_handler.session.rollback()  # Rollback on error
          raise
      finally:
          await connection_handler.close()
  ```
- Or use SQLAlchemy's `async with session.begin():` context manager (auto-commit/rollback).
- Never leave commits/rollbacks implicit; always handle exceptions.

---

## 6. Thin or Empty Service Layer

**Issue:** Business logic scattered in routers or DAOs; service layer is a thin pass-through or absent.

**Risk:** Violates separation of concerns; harder to test business logic; duplicate logic across routes.

**Examples:**
- Routers directly calling DAO methods with business logic embedded in the router
- Service methods that just call DAO methods without any transformation or validation

**Fix:**
- Move business logic into the service layer:
  ```python
  # service.py
  async def create_supplier(data: SupplierCreate, session: AsyncSession):
      # Business logic: validate, transform, apply rules
      if await dao.supplier_exists_by_email(data.email, session):
          raise ValueError("Supplier with this email already exists")
      supplier = await dao.create_supplier(data, session)
      # Emit event, send notification, etc.
      return supplier

  # router.py
  @router.post("/supplier")
  async def create_supplier_endpoint(data: SupplierCreate, handler = Depends(get_connection_handler)):
      supplier = await service.create_supplier(data, handler.session)
      return ResponseData.ok(data=supplier)
  ```
- Keep routers thin (HTTP concerns only); keep DAOs thin (data access only); put logic in services.

---

## 7. Mixed Kafka Libraries Imported Together

**Issue:** Multiple Kafka client libraries (`aiokafka`, `confluent-kafka`, `kafka-python`) imported in the same repo or even the same file.

**Risk:** Confusion, bloated dependencies, incompatible configurations, unexpected behavior.

**Examples:**
- Some repos import both `aiokafka` (async) and `confluent-kafka` (sync) in different modules

**Fix:**
- Pick ONE Kafka library per repo:
  - **Recommended for async FastAPI:** `aiokafka` (async producer/consumer)
  - **For high-throughput sync:** `confluent-kafka`
  - **Avoid:** `kafka-python` (slower, less maintained)
- Remove unused Kafka libraries from `pyproject.toml` / `requirements.txt`.
- Consolidate all Kafka code under `services/kafka/` with a single client library.

---

## 8. Duplicate Router Registration

**Issue:** The same router included multiple times in the application (e.g., `webhook_callback_router` registered twice).

**Risk:** Duplicate endpoints; confusing OpenAPI schema; potential routing conflicts.

**Example:**
- `src/routers.py`:
  ```python
  api_router_v1_prefix.include_router(webhook_callback_router, prefix="/webhooks", tags=["webhooks-callback"])
  # ... other routers ...
  api_router_v1_prefix.include_router(webhook_callback_router, prefix="/webhooks", tags=["webhooks-callback"])  # DUPLICATE
  ```

**Fix:**
- Audit `include_router()` calls; remove duplicates.
- Use a linter or pre-commit hook to detect duplicate router registrations:
  ```bash
  # Example: grep for duplicate include_router calls
  grep -n "include_router(webhook_callback_router" src/routers.py
  ```
- Keep a single, canonical router aggregation file (`routers.py` or `app/router.py`) and review it carefully.

---

## 9. Empty or Dead Code (LogLevel Enum)

**Issue:** Unused code (e.g., `LogLevel` enum defined but never used; placeholder classes/functions).

**Risk:** Code bloat, confusion, maintenance overhead.

**Example:**
- `config/docker_config.py` defines `LogLevel(enum.Enum)` but it's never used (logging config uses string log levels directly)

**Fix:**
- Remove unused code.
- Use a linter (Ruff, pylint) with unused-code detection:
  ```bash
  ruff check --select F401,F841  # unused imports, unused variables
  ```
- Regularly audit and delete dead code during refactoring.

---

## 10. Unused Dependencies in Worker-Only Services

**Issue:** Libraries installed that are never used in the codebase (e.g., `fastapi` and `strawberry` in a Kafka consumer/Temporal worker service with no HTTP server).

**Risk:** Larger Docker images, longer build times, security vulnerabilities in unused libs, dependency conflicts.

**Example:**
- A Temporal worker-only service has `fastapi` and `strawberry-graphql` in dependencies but no HTTP server

**Fix:**
- Audit dependencies; remove unused ones:
  ```bash
  pip install pipreqs
  pipreqs . --force  # Generate requirements.txt from actual imports
  # Compare with current dependencies; remove extras
  ```
- Use `pip-audit` or `safety` to check for vulnerabilities in unused deps.
- Keep dependencies minimal; only install what's needed for the MODE.

---

## 11. Near-Zero Automated Test Coverage

**Issue:** Many production services have minimal or zero automated tests (unit tests, integration tests).

**Risk:** Regressions, broken features, fear of refactoring, high manual QA burden.

**Observation:** Across multiple production services, minimal test files or very sparse coverage.

**Fix:**
- Establish a testing culture:
  - Add pytest fixtures for database, Kafka, Temporal mocks.
  - Write unit tests for service layer (easiest to test; pure business logic).
  - Write integration tests for routers (FastAPI TestClient).
  - Aim for >70% coverage on critical paths.
- Example:
  ```python
  # tests/test_supplier_service.py
  import pytest
  from app.supplier.service import create_supplier
  from app.supplier.models import SupplierCreate

  @pytest.mark.asyncio
  async def test_create_supplier_success(mock_session):
      data = SupplierCreate(name="Acme Corp", email="acme@example.com")
      supplier = await create_supplier(data, mock_session)
      assert supplier.name == "Acme Corp"
  ```
- Integrate test runs into CI/CD (fail build on test failure).

---

## 12. Unscoped sessionmaker (Session Leak Risk)

**Issue:** Creating an async session factory without scoping (no `scopefunc`), leading to potential session sharing across concurrent requests in async contexts.

**Risk:** Race conditions, data corruption, session leaks (sessions not closed).

**Example:**
- `core/connection_manager.py`:
  ```python
  async_session_factory = sessionmaker(
      async_engine,
      expire_on_commit=False,
      class_=AsyncSession,
  )  # NO scopefunc; sessions may leak or be shared unsafely
  ```

**Fix:**
- Use `async_scoped_session` with `scopefunc=current_task` to ensure each async task (request) gets its own session:
  ```python
  from sqlalchemy.ext.asyncio import async_scoped_session
  from asyncio import current_task

  session_factory = async_scoped_session(
      sessionmaker(async_engine, expire_on_commit=False, class_=AsyncSession),
      scopefunc=current_task,
  )
  ```
- Always close sessions explicitly (or use a Depends generator that closes in `finally`).

---

## 13. Deprecated FastAPI Lifecycle Hooks

**Issue:** Using `@app.on_event("startup")` and `@app.on_event("shutdown")` instead of the recommended `lifespan` context manager.

**Risk:** `on_event` is deprecated in FastAPI 0.109+; will be removed in future versions; no support for async context managers or exception handling.

**Example:**
- `src/routers.py`:
  ```python
  @api_router.on_event("startup")
  def list_routes():
      # ...
  ```

**Fix:**
- Migrate to `lifespan` context manager:
  ```python
  from contextlib import asynccontextmanager
  from fastapi import FastAPI

  @asynccontextmanager
  async def lifespan(app: FastAPI):
      # Startup logic
      print("Application starting...")
      # Example: Initialize ConnectionManager
      from app.connection import ConnectionManager
      connection_manager = ConnectionManager()
      print(f"Database connection pool initialized: {connection_manager}")
      
      yield  # Application runs here
      
      # Shutdown logic
      print("Application shutting down...")
      # Example: Close database connections
      await connection_manager._db_engine.dispose()
      print("Database connections closed")

  app = FastAPI(lifespan=lifespan)
  ```
- **Real-world example:**
  ```python
  from contextlib import asynccontextmanager
  from app.connection import ConnectionManager
  from services.kafka.producer.producer import AsyncEventEmitterWrapper

  @asynccontextmanager
  async def lifespan(app: FastAPI):
      # Startup
      connection_manager = ConnectionManager()
      kafka_producer = AsyncEventEmitterWrapper()
      await kafka_producer.start()
      app.state.kafka_producer = kafka_producer
      
      yield  # Application runs
      
      # Shutdown
      await kafka_producer.stop()
      await connection_manager._db_engine.dispose()

  app = FastAPI(lifespan=lifespan)
  ```
- See FastAPI docs: https://fastapi.tiangolo.com/advanced/events/

---

## 14. No Input Validation Beyond Schema

**Issue:** Relying solely on Pydantic schema validation; no business-level validation (e.g., "supplier name must not duplicate an existing supplier").

**Risk:** Invalid data enters the system; constraint violations at DB level instead of clean API errors.

**Fix:**
- Add business validation in the service layer:
  ```python
  async def create_supplier(data: SupplierCreate, session: AsyncSession):
      if await dao.supplier_exists_by_name(data.name, session):
          raise HTTPException(status_code=400, detail="Supplier name already exists")
      # ...
  ```
- Return clear error messages via the ResponseData envelope.

---

## 15. No Logging of Sensitive Data Redaction

**Issue:** Logging request bodies and headers without redacting sensitive fields (passwords, tokens, PII).

**Risk:** Secrets leak into log aggregation systems (Elasticsearch, CloudWatch); compliance violations (GDPR, PCI-DSS).

**Fix:**
- Filter sensitive fields before logging:
  ```python
  SENSITIVE_FIELDS = {"password", "token", "authorization", "x-api-key"}

  def redact_sensitive(data: dict) -> dict:
      return {k: "<REDACTED>" if k.lower() in SENSITIVE_FIELDS else v for k, v in data.items()}

  logger.info("Request data", extra={"request_data": redact_sensitive(request_data)})
  ```
- Use structured logging libraries that support field redaction (e.g., `structlog` with processors).

---

## Summary Table

| Anti-Pattern | Issue | Fix | Observed In |
|--------------|-------|-----|-------------|
| Hardcoded secrets | Credentials in Dockerfiles/config defaults | Use env vars, secret managers, no defaults | Multiple services |
| CORS `allow_origins=["*"]` | Disables CORS protection | Restrict to known origins | Multiple services |
| Sync clients in async code | Blocks event loop | Use async clients or `run_in_executor` | Multiple services |
| Copy-pasted DAO code | No shared library | Extract to shared package | Multiple services |
| No transaction rollback | Manual commit, no rollback | Use unit-of-work or context manager | Multiple services |
| Thin/empty service layer | Logic in routers or DAOs | Move business logic to service | Multiple services |
| Mixed Kafka libraries | Multiple Kafka clients imported | Pick one (aiokafka recommended) | Some services |
| Duplicate router registration | Same router included twice | Audit and remove duplicates | Production services |
| Dead code (LogLevel enum) | Unused enum/class | Remove unused code | Production services |
| Unused dependencies | Libs installed but never used | Audit with `pipreqs`, remove extras | Worker-only services |
| Near-zero test coverage | No automated tests | Add pytest, unit/integration tests | Multiple services |
| Unscoped sessionmaker | Session leak risk | Use `async_scoped_session(scopefunc=current_task)` | Production services |
| Deprecated `on_event` | Uses deprecated lifecycle hooks | Migrate to `lifespan` context manager | Production services |
| No business validation | Schema-only validation | Add service-layer validation | Multiple services |
| Logging sensitive data | PII/secrets in logs | Redact sensitive fields before logging | Multiple services |

---

## How to Audit for Anti-Patterns

1. **Secrets:**
   ```bash
   grep -rE "(token|password|secret|key).*=.*['\"]" --include="*.py" --include="Dockerfile" .
   ```
2. **CORS wildcards:**
   ```bash
   grep -r "allow_origins.*\[\"\*\"\]" --include="*.py" .
   ```
3. **Sync clients:**
   ```bash
   grep -rE "from google.cloud import (bigquery|storage)" --include="*.py" .  # Check if used in async funcs
   ```
4. **Duplicate routers:**
   ```bash
   grep -n "include_router" app/router.py | sort | uniq -d
   ```
5. **Deprecated lifecycle hooks:**
   ```bash
   grep -r "@.*\.on_event" --include="*.py" .
   ```
6. **Unscoped sessionmaker:**
   ```bash
   grep -A5 "sessionmaker" --include="*.py" . | grep -v "scopefunc"
   ```
7. **Unused imports:**
   ```bash
   ruff check --select F401
   ```

Run these checks in CI/CD to prevent anti-patterns from merging.
