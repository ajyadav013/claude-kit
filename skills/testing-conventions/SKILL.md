---
name: testing-conventions
description: Testing conventions from production Python/FastAPI and React services — pytest + pytest-asyncio, conftest.py fixtures (session event loop, async session, authenticated client, dependency overrides, cleanup), AsyncMock for Kafka/Temporal/HTTP, factory.Factory + factory.Faker patterns, Vitest + jsdom for frontend, and honest coverage gaps. Use when writing or reviewing tests, setting up pytest infrastructure, implementing async test fixtures, mocking external dependencies, establishing testing baselines for services with thin coverage, configuring Vitest for React/TypeScript, or auditing test quality.
---

# Testing Conventions

Testing patterns and conventions derived from production backend and frontend services, with honest assessment of coverage gaps.

## When to use

- Setting up pytest infrastructure (conftest, fixtures, async session management)
- Implementing async test fixtures for FastAPI services
- Mocking external dependencies (Kafka, Temporal, HTTP clients, DB connections)
- Writing DAO/service/route layer tests
- Establishing test baselines for projects with thin coverage
- Reviewing test quality and identifying missing coverage
- Setting up Vitest/Playwright for frontend testing

## Core conventions

### Session-Scoped Event Loop (pytest-asyncio)

**Single event loop per session**: Define `event_loop` fixture with `scope="session"` to avoid loop creation overhead. _(reference service patterns)_

**Pattern**:
```python
@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()
```

**Alternative**: Use `asyncio.get_event_loop()` for session scope, but always close it in `finally`. _(alternative pattern)_

### Test Database Isolation

**Separate test database + Redis DB**: Override env vars **before** any app imports to ensure test isolation. Use dedicated test DB (e.g., `app_test_db`) and Redis DB 1. _(integration test pattern)_

**Migration setup**: Run Alembic migrations once per session via `autouse=True` fixture. _(integration test pattern)_

**Cleanup pattern**: Use `autouse=True` cleanup fixture that flushes Redis and truncates all tables with `RESTART IDENTITY CASCADE`. Also drop tenant schemas created during tests. _(integration test pattern)_

**Lightweight mocking alternative**: For unit tests, use dependency overrides with `UnittestConnectionManager` singleton that provides isolated async engine + session factory. No real DB setup needed for pure unit tests. _(unit test pattern)_

### Conftest Fixtures

**Authenticated client fixture**: Register sys_admin user, login, attach cookies to client, yield, then logout. _(integration test pattern)_

**HTTP client fixture**: Use `httpx.AsyncClient` with `ASGITransport(app=app)` for FastAPI testing. Always close in `finally`. _(common pattern)_

**Dependency override registration**: Override `get_connection_handler_for_app` and `get_connection_handler_for_func` at module level in conftest. _(dependency injection pattern)_

**Factory fixtures**: Use `factory.Factory` with `factory.LazyAttribute` and `factory.Faker` for generating test data schemas. _(factory pattern)_

**Per-module conftest**: Domain-specific fixtures (e.g., `tests/unit/webhook/conftest.py`) provide mocked DAOs, services, and sample data factories. _(domain-specific fixture pattern)_

### Async Test Fixtures

**Function-scoped DAO fixtures**: Wrap DAO instantiation in async context manager from `db_connection` session factory. _(DAO test pattern)_

**Pattern**:
```python
@pytest.fixture
async def dao(self, db_connection):
    async with db_connection() as session:
        yield BrandDAO(session)
```

**Parametrized fixtures**: Use `@pytest.fixture(params=[...])` for multiple test cases (e.g., template resolution, condition evaluation, HTTP methods). _(parametrized fixture pattern)_

### Mocking External Services

**AsyncMock for Kafka**: Mock `emit`, `emit_batch`, `close` as `AsyncMock()`. Mock consumer with `start`, `stop`, and `__aiter__`. _(Kafka mock pattern)_

**AsyncMock for Temporal**: Mock client methods (`start_workflow`, `get_workflow_handle`, `health_check`) as `AsyncMock()`. Mock activity/workflow info with `MagicMock()`. _(Temporal mock pattern)_

**unittest.mock.patch for HTTP/config**: Use `@patch("module.path.function")` for Slack/HTTP publish functions and config objects. _(patch pattern)_

**Mock DAO/service pattern**: Create `MagicMock()` with all methods stubbed as `AsyncMock()` for dependency injection. _(mock DAO pattern)_

### Test Markers and Async

**@pytest.mark.asyncio**: Required for all async test functions. _(standard pytest-asyncio practice)_

**Async with httpx**: All FastAPI route tests use `async def test_` and `await client.post/get(...)`. _(FastAPI test pattern)_

### Frontend Testing (Vitest)

**Vitest config**: Use `jsdom` environment, globals mode, setup file for test utilities. _(standard Vitest pattern)_

**Coverage thresholds**: Set aggressive thresholds (90% lines/functions/branches/statements) but exclude generated files, test files, and specific uncovered components. _(example: excludes hard-to-test components like complex sidebars)_

**Include pattern**: `src/test/**/*.test.{ts,tsx}` for test discovery. _(standard Vitest pattern)_

**Coverage focus**: Prioritize `src/lib/**` and `src/hooks/**`; exclude API clients and module-specific views from baseline coverage. _(focused coverage strategy)_

### Coverage Gap: The Honest Truth

**Reference service A** (high coverage): 18 test files (17 test_*.py + conftest + load_test); comprehensive coverage of auth, multi-tenancy, access control, enterprise features. **Strength**: integration tests for entire feature sets.

**Reference service B** (moderate coverage): ~40 domain modules, most have 3-file test structure (`test_dao.py`, `test_service.py`, `test_route.py`) but many are thin or absent. **Strength**: factory fixtures + mocking patterns.

**Reference service C** (minimal coverage): 3-4 test files (`test_contracts.py`, `test_sdk.py`, `test_workflow_execution.py` E2E, + conftest) covering JSON schema validation and basic E2E. **Gap**: No comprehensive DAO/service layer tests, no Temporal workflow tests beyond mocks.

**Reference service D** (zero coverage): 0 test files found. **Gap**: No test infrastructure.

**Multiple other services**: Minimal to zero test coverage (0-2 test files). **Gap**: No test baselines.

**Reference frontend**: Vitest configured with aggressive thresholds; 31 test files found (14 hook tests, 11 component tests, 6 module/lib tests). **Strength**: Good coverage of hooks (useToast, usePagination, useFilters, etc.) and task module components. Coverage includes config, utils, permissions, API clients.

## Skeleton / example

```python
# conftest.py (integration test setup)
import os
os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://user:pass@postgres:5432/app_test_db",
)
os.environ["REDIS_URL"] = "redis://redis:6379/1"

import pytest
import httpx
from httpx import ASGITransport

@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()

@pytest.fixture(scope="session", autouse=True)
async def _run_migrations():
    result = subprocess.run(["alembic", "upgrade", "head"], ...)
    if result.returncode != 0:
        raise RuntimeError(f"Migration failed: {result.stderr}")
    yield

@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

@pytest.fixture
async def authenticated_client(client: httpx.AsyncClient):
    await client.post("/v1/auth/register", json={...})
    resp = await client.post("/v1/auth/login", json={...})
    client.cookies.update(resp.cookies)
    yield client
    await client.post("/v1/auth/logout")

@pytest.fixture(autouse=True)
async def cleanup():
    yield
    # Flush Redis
    redis = Redis.from_url(settings.REDIS_URL)
    await redis.flushdb()
    await redis.aclose()
    # Truncate all tables + drop tenant schemas
    engine = create_async_engine(settings.DATABASE_URL)
    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE TABLE ... RESTART IDENTITY CASCADE"))
    await engine.dispose()

# conftest.py (unit test mocks)
from tests.utils import UnittestConnectionManager, get_test_connection_handler_for_app

@pytest.fixture(scope="session", autouse=True)
def event_loop():
    loop = asyncio.get_event_loop()
    try:
        yield loop
    finally:
        loop.close()

@pytest_asyncio.fixture
async def client():
    async with httpx.AsyncClient(app=test_app, base_url="http://testserver/v1.0") as http_client:
        try:
            yield http_client
        finally:
            await http_client.aclose()

@pytest_asyncio.fixture(autouse=False)
async def db_connection():
    cm = UnittestConnectionManager()
    try:
        engine = cm.get_db_engine()
        await db_setup(engine)  # Create all tables
        yield cm.get_session_factory()
        await db_cleanup(engine)  # Drop all tables
    finally:
        await cm.close_connections()

test_app.dependency_overrides[get_connection_handler_for_app] = get_test_connection_handler_for_app

# Domain-specific conftest (webhook/temporal)
import factory
from unittest.mock import AsyncMock, MagicMock

class WebhookDeliveryFactory(factory.Factory):
    class Meta:
        model = WebhookDeliveryCreate
    
    webhook_chain_step_id = factory.LazyAttribute(lambda n: uuid4())
    url = factory.Faker("url")
    http_method = factory.Faker("random_element", elements=["GET", "POST", "PUT"])
    status_code = 200
    delivery_status = "success"

@pytest.fixture
def mock_webhook_delivery_dao():
    dao = MagicMock()
    dao.get_by_pk = AsyncMock()
    dao.create_delivery = AsyncMock()
    return dao

@pytest.fixture
async def mock_temporal_client():
    client = AsyncMock()
    client.start_workflow = AsyncMock(return_value="test_workflow_id")
    return client

@pytest.fixture
async def mock_kafka_producer():
    producer = AsyncMock()
    producer.emit = AsyncMock()
    producer.close = AsyncMock()
    return producer

# Test example (DAO layer)
class TestBrandDao:
    @pytest.fixture
    async def dao(self, db_connection):
        async with db_connection() as session:
            yield BrandDAO(session)
    
    async def test_get_records_by_id(self, dao, db_connection):
        records = await dao.get_record_by_id(1)
        assert records is None
        async with db_connection() as session:
            brand = await populate_brand_by_size(session)
            record = await dao.get_record_by_id(brand.id)
            assert record.id == brand.id

# Test example (async route with mocking)
@patch("src.config.docker_config.loaded_config", MockConfig)
@patch("src.utils.slack.alerts.publish_slack_alert_push_event")
@pytest.mark.asyncio
async def test_raise_slack_alert_success(mock_publish_event, valid_slack_alert_schema):
    mock_publish_event.return_value = True
    response = await raise_slack_alert(valid_slack_alert_schema)
    assert response["success"]
    mock_publish_event.assert_called_once()

# Vitest config (frontend)
import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/test/**/*.test.{ts,tsx}'],
    coverage: {
      provider: 'v8',
      include: ['src/lib/**', 'src/hooks/**'],
      exclude: ['src/test/**', 'src/**/*.test.{ts,tsx}'],
      thresholds: { lines: 90, functions: 90, branches: 90 },
    },
  },
});
```

## Anti-patterns to avoid

- **Running tests against dev database** — always override env vars before any app imports to use test DB.
- **Sharing event loop across tests without session scope** — causes loop closure conflicts and test flakiness.
- **Forgetting autouse cleanup fixtures** — state leaks across tests; always flush Redis and truncate tables.
- **Using sync fixtures for async DAOs** — use `@pytest_asyncio.fixture` or `@pytest.fixture` with `async def`.
- **Mixing @pytest.fixture and @pytest_asyncio.fixture inconsistently** — pick one style per project; `@pytest.fixture` with `async def` works in most cases, `@pytest_asyncio.fixture` is explicit but requires pytest-asyncio mode configuration.
- **Not mocking external services** — never hit real Kafka/Temporal/Slack/HTTP in unit tests; use AsyncMock.
- **Hardcoding test data instead of factories** — use factory.Factory for reusable, randomized test data.
- **Trusting coverage metrics without inspecting tests** — thin coverage is worse than honest zero; measure what matters (DAO, service, route contracts).
- **Setting aggressive coverage thresholds on greenfield projects** — start with baseline coverage on critical paths, expand incrementally.
- **Not closing async clients in finally blocks** — httpx.AsyncClient and other async resources must close even on test failure.

## Recommended Baseline (for thin-coverage repos)

When coverage is near-zero, establish this pragmatic baseline **before** adding features:

1. **DAO layer**: Test `create`, `get_by_id`, `get_by_field`, `update`, `delete` for each entity.
2. **Service layer**: Test happy path + one error case (e.g., not found, validation failure).
3. **Route contracts**: Test auth required, tenant scoping, request/response schemas (not full business logic).
4. **External mocks**: Stub Kafka producer, Temporal client, HTTP clients as AsyncMock fixtures.
5. **Conftest setup**: Session event loop, test DB override, dependency injection, cleanup fixtures.

**Do not aim for 80% coverage initially** — aim for 40-60% on the **right** surface (DAO, service contracts, auth).

## References

- [pytest-and-fixtures.md](./references/pytest-and-fixtures.md) — Session event loop, conftest patterns, cleanup, authenticated client
- [async-and-mocking.md](./references/async-and-mocking.md) — AsyncMock for Kafka/Temporal/HTTP, factory fixtures, parametrized tests
- [pytest-asyncio-modes.md](./references/pytest-asyncio-modes.md) — pytest-asyncio mode (auto vs strict), @pytest.fixture vs @pytest_asyncio.fixture, event loop patterns
- [vitest-frontend-testing.md](./references/vitest-frontend-testing.md) — Vitest config, jsdom setup, hook/component/API testing patterns, coverage strategy
- [coverage-gap-and-recommendations.md](./references/coverage-gap-and-recommendations.md) — Honest coverage audit, recommended baseline
- [repo-evidence.md](./references/repo-evidence.md) — Real file paths and snippets from source repos
