# Coverage Gap and Recommendations

Honest assessment of test coverage across repos, with pragmatic baseline recommendations.

## Coverage Audit

### High Coverage: Reference Service A

**Example**: A production FastAPI service with comprehensive test coverage

**Test files**: 18 test files (17 test_*.py + conftest.py + load_test.py)

**Coverage**:
- Auth API (`test_auth_api.py`)
- Multi-tenancy (`test_multi_tenancy.py`)
- Access control (`test_access_control.py`)
- Control plane (`test_control_plane.py`)
- Enterprise features (`test_enterprise_features.py`)
- Flexible tenant roles (`test_flexible_tenant_roles.py`)
- MFA/SSO/OAuth/JWT (`test_mfa_sso_oauth_jwt.py`)
- Provisioning policy (`test_provisioning_policy.py`)
- Security pentest (`test_security_pentest.py`)
- Data integrity (`test_data_integrity.py`)
- Rate limiter (`test_rate_limiter.py`)
- Session manager (`test_session_manager.py`)
- Load test (`load_test.py`)

**Strength**: Comprehensive integration tests covering entire feature sets (auth, RBAC, provisioning, enterprise features). Includes pentest and load test scenarios.

**Conftest quality**: Production-grade test DB isolation, Alembic migrations, authenticated client fixture, autouse cleanup with Redis flush + table truncation.

### Moderate Coverage: Reference Service B

**Example**: A production FastAPI service with good structure but inconsistent coverage

**Test structure**: Most domain modules have 3-file test structure:
- `tests/<domain>/test_dao.py`
- `tests/<domain>/test_service.py`
- `tests/<domain>/test_route.py`

Example domains with tests:
- `tests/tenant/` (dao, service, route, helpers, templates)
- `tests/cluster/` (dao, service, route)
- `tests/unit/webhook/` (conftest, factory fixtures)
- `tests/unit/temporal/` (conftest, factory fixtures, parametrized fixtures)
- `tests/test_slack_alert.py`
- `tests/test_metrics.py`
- `tests/test_gcs_client.py`

**Strength**: Well-organized test structure; excellent factory fixture patterns (factory.Factory + factory.Faker); domain-specific conftest files; AsyncMock patterns for external services.

**Gap**: Many domain modules (out of ~40 total) have thin or absent tests; test files exist but coverage varies widely.

### Minimal Coverage: Reference Service C

**Example**: A production FastAPI service with minimal test coverage

**Test files**: 3-4 test files (unit + E2E + conftest)
- `tests/unit/test_contracts.py` — JSON schema validation for envelope, payload, workflow DSL
- `tests/unit/test_sdk.py` — SDK interface tests
- `tests/e2e/test_workflow_execution.py` — Basic E2E workflow execution tests
- `tests/conftest.py` — Fixture setup (event loop, mocks for Kafka/Temporal)

**Gap**: No comprehensive DAO layer tests, no service layer tests, no Temporal workflow tests beyond basic E2E. Contract validation and SDK tests are the primary coverage.

**Strength**: Clean AsyncMock patterns for Kafka/Temporal; good fixture isolation; logging config fixture.

### Zero Coverage: Reference Service D

**Example**: A production FastAPI service with no test coverage

**Test files**: 0

**Gap**: No test infrastructure found. No conftest, no test files.

### Zero/Minimal Coverage: Other Services

**Examples**: Multiple production FastAPI services with thin or no test coverage

**Pattern**: 0-10 test files per service

**Gap**: No systematic test baselines for these services.

### Frontend Coverage: Reference React Application

**Example**: A production React application with good test coverage

**Test files**: 31 test files
- **Hook tests** (14 files): `useListState`, `useToast`, `useApiData`, `useSearch`, `useSelection`, `usePagination`, `useSidebarStore`, `useFilters`, `useNavigationStore`, `useSort`, `usePersonaStore`, `usePersonaConfig`, `useResetOnPersonaChange`, `useTimePeriodStore`
- **Component tests** (11 files): UI components (`ToggleGroup`, `Badge`, `Avatar`), Task module components (`PriorityPicker`, `TaskStatusPill`, `TaskRowCard`, `TaskListTableView`, `TaskListCardView`, `PriorityChip`, `ViewSwitcher`, `ActionsList`)
- **Module/lib tests** (6 files): `config.test.ts`, `lib/utils.test.ts`, `tasks/types/task.types.test.ts`, `tasks/lib/permissions.test.ts`, `tasks/api/tasksApi.test.ts`, `tasks/api/queryKeys.test.ts`

**Vitest config**: `vitest.config.ts`
- Coverage provider: v8
- Environment: jsdom
- Setup file: `./src/test/setup.ts`
- Include: `src/test/**/*.test.{ts,tsx}`
- Coverage thresholds: 90% lines/functions/branches/statements
- Coverage include: `src/lib/**`, `src/hooks/**`
- Coverage exclude: test files, `src/lib/api.ts`, `src/modules/analytics/components/AnalyticsPanel.tsx`

**Strength**: Good coverage of hooks (state management, filters, pagination, search, etc.) and task module components/logic. Comprehensive test suite. Aggressive thresholds met with targeted exclusions for hard-to-test components.

## Recommended Baseline (for thin-coverage repos)

When test coverage is near-zero or minimal, establish this pragmatic baseline **before** adding features:

### 1. DAO Layer Tests

**What to test**: Core CRUD operations for each entity.

**Priority operations**:
- `create(schema)` — create a new record, verify it's returned with ID
- `get_by_id(id)` — fetch existing record, verify fields match
- `get_by_field(field, value)` — lookup by unique field (e.g., name, email, slug)
- `update(id, schema)` — update existing record, verify changes persisted
- `delete(id)` — soft or hard delete, verify record gone or marked deleted

**Pattern** (example):

```python
class TestTenantDao:
    @pytest.fixture
    async def dao(self, db_connection):
        async with db_connection() as session:
            yield TenantDAO(session)

    async def test_get_records_by_id(self, dao, db_connection):
        records = await dao.get_record_by_id(1)
        assert records is None  # Empty DB case
        async with db_connection() as session:
            tenant = await populate_tenant_by_size(session)
            record = await dao.get_record_by_id(tenant.id)
            assert record.id == tenant.id

    async def test_get_tenant_by_field(self, dao, db_connection):
        record = await dao.get_tenant_by_field("name", "test")
        assert record is None
        async with db_connection() as session:
            tenant = await populate_tenant_by_size(session)
            record = await dao.get_tenant_by_field("name", tenant.name)
            assert record.id == tenant.id
```

**Do not**: Test every single DAO method; focus on the 5-6 core operations. Skip pagination helpers initially.

### 2. Service Layer Tests

**What to test**: Happy path + one error case per service method.

**Priority tests**:
- Happy path: Service method returns expected DTO when DAO succeeds
- Not found: Service raises or returns `None` when DAO returns `None`
- Validation failure: Service raises when input schema is invalid

**Pattern**:

```python
@pytest.mark.asyncio
async def test_create_tenant_success(mock_tenant_dao, sample_tenant_create):
    mock_tenant_dao.create.return_value = Tenant(id=1, **sample_tenant_create.dict())
    service = TenantService(mock_tenant_dao)
    result = await service.create_tenant(sample_tenant_create)
    assert result.id == 1

@pytest.mark.asyncio
async def test_get_tenant_not_found(mock_tenant_dao):
    mock_tenant_dao.get_by_id.return_value = None
    service = TenantService(mock_tenant_dao)
    result = await service.get_tenant(999)
    assert result is None
```

**Do not**: Aim for exhaustive business logic coverage; start with happy path + not found.

### 3. Route Contract Tests

**What to test**: Auth required, tenant scoping, request/response schemas.

**Priority tests**:
- Unauthenticated: Route returns 401 when no auth header/cookie
- Tenant scoped: Route returns tenant-filtered data when `X-Tenant-ID` header present
- Valid request: Route returns 200/201 with expected schema
- Invalid request: Route returns 400/422 when request schema is invalid

**Pattern**:

```python
@pytest.mark.asyncio
async def test_create_tenant_unauthenticated(client):
    resp = await client.post("/v1/tenants", json={...})
    assert resp.status_code == 401

@pytest.mark.asyncio
async def test_create_tenant_success(authenticated_client):
    resp = await authenticated_client.post("/v1/tenants", json={
        "name": "Test Tenant",
        "slug": "test-tenant",
        ...
    })
    assert resp.status_code == 201
    assert resp.json()["name"] == "Test Tenant"
```

**Do not**: Test full business logic in route tests; that's what service tests are for. Focus on HTTP contracts (status codes, schemas, auth).

### 4. External Service Mocks

**What to mock**: Kafka, Temporal, HTTP clients, Redis, external APIs.

**Priority mocks**:
- Kafka producer: `emit`, `emit_batch`, `close`
- Kafka consumer: `start`, `stop`, `__aiter__`
- Temporal client: `start_workflow`, `get_workflow_handle`, `health_check`
- HTTP client: `fetch`, `get`, `post`, `close`

**Pattern** (example):

```python
@pytest.fixture
async def mock_kafka_producer():
    producer = AsyncMock()
    producer.emit = AsyncMock()
    producer.emit_batch = AsyncMock()
    producer.close = AsyncMock()
    return producer

@pytest.fixture
async def mock_temporal_client():
    client = AsyncMock()
    client.start_workflow = AsyncMock(return_value="test_workflow_id")
    client.get_workflow_handle = AsyncMock()
    return client
```

**Do not**: Hit real Kafka/Temporal in unit tests. Always mock.

### 5. Conftest Setup

**What to include**:
- Session event loop fixture
- Test DB env override (before imports)
- Alembic migration runner (session scope, autouse)
- HTTP client fixture (httpx.AsyncClient with ASGITransport)
- Authenticated client fixture (register + login)
- Cleanup fixture (flush Redis, truncate tables)
- Dependency overrides (replace prod DB with test DB)

**Pattern** (example):

```python
import os
os.environ["DATABASE_URL"] = "postgresql+asyncpg://user:pass@postgres:5432/test_db"
os.environ["REDIS_URL"] = "redis://redis:6379/1"

@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()

@pytest.fixture(scope="session", autouse=True)
async def _run_migrations():
    subprocess.run(["alembic", "upgrade", "head"], ...)
    yield

@pytest.fixture
async def client(app):
    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac

@pytest.fixture(autouse=True)
async def cleanup():
    yield
    # Flush Redis + truncate tables
```

**Do not**: Skip cleanup fixtures; state leaks will cause flaky tests.

## Initial Coverage Target

**Do not aim for 80% coverage** on a greenfield or thin-coverage project. Aim for **40-60% coverage on the right surface**:

- DAO layer: 60-80% (core CRUD operations)
- Service layer: 40-60% (happy path + not found)
- Route layer: 40-60% (auth, tenant scoping, schema validation)
- External mocks: 100% (all external services stubbed)

**Measure what matters**: DAO correctness, service contracts, route auth/tenant scoping. Skip edge cases initially.

## Anti-Patterns

- **Trusting coverage metrics without inspecting tests** — thin coverage (e.g., only testing `get_by_id` success) is worse than honest zero.
- **Setting aggressive coverage thresholds on greenfield projects** — 90% thresholds force junk tests to hit the number.
- **Testing implementation details** — don't test private methods, internal state, or ORM internals; test public DAO/service interfaces.
- **Omitting external service mocks** — hitting real Kafka/Temporal in tests is slow, flaky, and breaks CI.
- **Skipping cleanup fixtures** — state leaks cause test interdependencies and flakiness.

## When to Raise Coverage

**After** establishing the baseline (DAO, service happy path, route contracts), raise coverage incrementally:

1. **Add service error cases** — validation failures, not found, unauthorized
2. **Add route error cases** — 400/404/422/403 scenarios
3. **Add DAO edge cases** — pagination, filtering, sorting, bulk operations
4. **Add integration tests** — full request/response cycles with real DB
5. **Add E2E tests** — Playwright/Selenium for critical user flows

**Do not** jump straight to E2E or integration tests without unit test baseline.
