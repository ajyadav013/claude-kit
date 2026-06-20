# GitHub Actions Test Orchestration

Comprehensive patterns for orchestrating backend, frontend, contract, and E2E tests in GitHub Actions CI.

## Path-based triggers

Run workflows only when relevant files change. Reduces CI cost and noise.

```yaml
on:
  push:
    branches: [main, develop]
    paths:
      - 'backend/**'
      - '.github/workflows/backend-tests.yml'
  pull_request:
    branches: [main, develop]
    paths:
      - 'backend/**'
      - '.github/workflows/backend-tests.yml'
```

**Frontend variant**:
```yaml
on:
  push:
    paths: ['frontend/**']
  pull_request:
    paths: ['frontend/**']
```

**Contract tests** (schema changes only):
```yaml
on:
  push:
    paths:
      - 'backend/src/schemas/**'
      - 'backend/contracts/**'
      - 'backend/scripts/generate_contract_fixtures.py'
      - 'frontend/src/__tests__/contracts/**'
```

## Service containers with health checks

Define Postgres and Redis as services with health probes. GitHub Actions waits until healthy before running steps.

```yaml
jobs:
  test:
    services:
      postgres:
        image: postgres:15
        env:
          POSTGRES_USER: postgres
          POSTGRES_PASSWORD: postgres
          POSTGRES_DB: app_db
        ports:
          - 5432:5432
        options: >-
          --health-cmd pg_isready
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5

      redis:
        image: redis:7
        ports:
          - 6379:6379
        options: >-
          --health-cmd "redis-cli ping"
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
```

**Health check parameters**:
- `--health-cmd`: Command to run (`pg_isready`, `redis-cli ping`)
- `--health-interval`: How often to check (10s)
- `--health-timeout`: Max time per check (5s)
- `--health-retries`: Retries before marking unhealthy (5)

**Test database setup**:
```yaml
- name: Create test database
  run: |
    PGPASSWORD=${{ env.POSTGRES_PASSWORD }} psql -h localhost -U ${{ env.POSTGRES_USER }} -d ${{ env.POSTGRES_DB }} -c "CREATE DATABASE ${POSTGRES_DB}_test;"
```

## Job dependencies (needs:)

Chain jobs to fail fast. Lint/typecheck runs first; all test jobs wait for lint to pass.

```yaml
jobs:
  lint:
    name: Lint & Type Check
    runs-on: ubuntu-latest
    steps:
      - run: ruff check src tests
      - run: ruff format --check src tests
      - run: mypy src --ignore-missing-imports

  test:
    name: Run Tests
    needs: [lint]
    # ...

  api-tests:
    name: API Tests
    needs: [lint]
    # ...

  integration-tests:
    name: Integration Tests
    needs: [lint]
    # ...
```

**Benefit**: All test jobs run in parallel after lint passes. If lint fails, no test jobs start.

## Coverage enforcement (--cov-fail-under)

Enforce minimum coverage threshold. CI fails if coverage drops below target.

```yaml
- name: Run tests with coverage
  working-directory: backend
  env:
    DATABASE_URL: postgresql+asyncpg://postgres:postgres@localhost:5432/app_test_db
  run: |
    pytest --junitxml=test-results.xml --cov=src --cov-report=xml --cov-report=term-missing --cov-fail-under=68
```

**Coverage flags**:
- `--cov=src`: Measure coverage for src/ directory
- `--cov-report=xml`: Generate coverage.xml for Codecov
- `--cov-report=term-missing`: Print missing lines to console
- `--cov-fail-under=68`: Fail if coverage < 68%

**Start conservatively** (e.g., 40-50%) on low-coverage repos, then ratchet up as coverage improves. Prevents regressions.

## Artifact upload

Persist test results, coverage reports, and E2E traces for debugging.

```yaml
- name: Upload test results
  uses: actions/upload-artifact@v4
  if: always()
  with:
    name: test-results
    path: backend/test-results.xml

- name: Upload coverage report
  uses: actions/upload-artifact@v4
  if: always()
  with:
    name: coverage-report
    path: backend/coverage.xml
```

**E2E traces** (on failure only):
```yaml
- name: Upload traces on failure
  uses: actions/upload-artifact@v4
  if: failure()
  with:
    name: playwright-traces
    path: test-results/
    retention-days: 7
```

**Key**: `if: always()` uploads even if tests fail; `if: failure()` uploads only on failure.

## Codecov integration

Upload coverage XML to Codecov with backend/frontend flags.

```yaml
- name: Upload coverage to Codecov
  uses: codecov/codecov-action@v4
  if: always()
  with:
    file: backend/coverage.xml
    flags: backend
    name: backend-coverage
    fail_ci_if_error: false
```

**Frontend variant**:
```yaml
- uses: codecov/codecov-action@v4
  with:
    file: frontend/coverage/coverage-final.json
    flags: frontend
    fail_ci_if_error: false
```

**Set `fail_ci_if_error: false`** to prevent Codecov API issues from blocking CI.

## Contract testing pipeline

Generate JSON fixtures from backend Pydantic schemas, then validate against frontend TypeScript types.

**Backend fixture generation**:
```yaml
- name: Generate contract fixtures
  working-directory: backend
  run: |
    python scripts/generate_contract_fixtures.py

- name: Verify fixture generation
  run: |
    test -f contracts/fixtures/manifest.json
    test -f contracts/fixtures/coverage.json
    python3 -c "
    import json
    with open('contracts/fixtures/coverage.json') as f:
        c = json.load(f)
    assert c['error_count'] == 0, f'Fixture generation had {c[\"error_count\"]} errors'
    print(f'Generated {c[\"total_models_generated\"]} model fixtures')
    "
```

**Frontend contract tests**:
```yaml
- name: Run contract tests
  working-directory: frontend
  run: npx vitest run src/__tests__/contracts/ --reporter=verbose
```

**Pattern**: Backend generates fixtures/coverage.json with error_count, total_models_generated, total_fields. CI fails if error_count > 0. Frontend Vitest imports fixtures and asserts type compatibility.

## E2E with background services (Playwright)

Start backend + frontend in background, wait for health, then run E2E tests.

```yaml
jobs:
  playwright:
    name: Playwright E2E
    services:
      postgres: {...}
      redis: {...}
    steps:
      - name: Install backend dependencies
        run: pip install -r backend/requirements.txt
      - name: Install frontend dependencies
        run: npm ci
        working-directory: frontend
      - name: Install Playwright
        run: npm install && npx playwright install chromium --with-deps

      - name: Run migrations and seed
        env:
          DATABASE_URL: postgresql+asyncpg://postgres:postgres@localhost:5432/app_test
          USE_MOCK_LLM: 'true'
        run: |
          cd backend && alembic upgrade head && python -m src.scripts.cli seed

      - name: Start backend
        env:
          DATABASE_URL: postgresql+asyncpg://postgres:postgres@localhost:5432/app_test
          REDIS_URL: redis://localhost:6379/0
        run: cd backend && uvicorn src.main:app --port 8000 &

      - name: Start frontend
        run: cd frontend && npm run dev &

      - name: Wait for services
        run: |
          timeout 30 bash -c 'until curl -s http://localhost:8000/_healthz; do sleep 1; done'
          timeout 30 bash -c 'until curl -s http://localhost:5173; do sleep 1; done'

      - name: Run Playwright tests
        run: npx playwright test
        env:
          E2E_BASE_URL: http://localhost:5173

      - name: Upload traces on failure
        uses: actions/upload-artifact@v4
        if: failure()
        with:
          name: playwright-traces
          path: test-results/
          retention-days: 7
```

**Key patterns**:
- `&` runs processes in background (backend + frontend keep running)
- `timeout 30 bash -c 'until curl ...'` polls health endpoint with 30s timeout
- `USE_MOCK_LLM: 'true'` disables external API calls during E2E
- Playwright traces uploaded only on failure

## Pytest markers for test categories

Run different test suites with targeted service dependencies.

**API tests** (Postgres only, no Redis):
```yaml
jobs:
  api-tests:
    needs: [lint]
    services:
      postgres:
        image: postgres:15
        # ...
    steps:
      - run: pytest -m api -v
```

**Integration tests** (Postgres + Redis):
```yaml
jobs:
  integration-tests:
    needs: [lint]
    services:
      postgres: {...}
      redis: {...}
    steps:
      - run: pytest -m integration -v
```

**Test file markers**:
```python
@pytest.mark.api
async def test_list_users_endpoint(client):
    # ...

@pytest.mark.integration
async def test_redis_cache_invalidation(client, redis_client):
    # ...
```

**Configure in pytest.ini**:
```ini
[pytest]
markers =
    api: API endpoint tests (needs Postgres)
    integration: Integration tests (needs Postgres + Redis)
```

## Full workflow example (backend)

```yaml
name: Backend Tests

on:
  push:
    branches: [main, develop]
    paths:
      - 'backend/**'
      - '.github/workflows/backend-tests.yml'
  pull_request:
    branches: [main, develop]
    paths:
      - 'backend/**'

env:
  PYTHON_VERSION: '3.11'
  POSTGRES_USER: postgres
  POSTGRES_PASSWORD: postgres
  POSTGRES_DB: app_db
  POSTGRES_HOST: localhost
  POSTGRES_PORT: 5432
  REDIS_URL: redis://localhost:6379/0
  LOG_LEVEL: WARNING

jobs:
  lint:
    name: Lint & Type Check
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ env.PYTHON_VERSION }}
      - run: pip install ruff mypy
      - run: pip install -r backend/requirements.txt
      - run: ruff check src tests
        working-directory: backend
      - run: ruff format --check src tests
        working-directory: backend
      - run: mypy src --ignore-missing-imports
        working-directory: backend

  test:
    name: Run Tests
    runs-on: ubuntu-latest
    needs: [lint]
    services:
      postgres:
        image: postgres:15
        env:
          POSTGRES_USER: ${{ env.POSTGRES_USER }}
          POSTGRES_PASSWORD: ${{ env.POSTGRES_PASSWORD }}
          POSTGRES_DB: ${{ env.POSTGRES_DB }}
        ports: ['5432:5432']
        options: >-
          --health-cmd pg_isready
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
      redis:
        image: redis:7
        ports: ['6379:6379']
        options: >-
          --health-cmd "redis-cli ping"
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5

    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ env.PYTHON_VERSION }}
      - uses: actions/cache@v4
        with:
          path: ~/.cache/pip
          key: ${{ runner.os }}-pip-${{ hashFiles('backend/requirements.txt') }}
      - run: pip install -r backend/requirements.txt
        working-directory: backend

      - name: Create test database
        run: |
          PGPASSWORD=${{ env.POSTGRES_PASSWORD }} psql -h localhost -U ${{ env.POSTGRES_USER }} -d ${{ env.POSTGRES_DB }} -c "CREATE DATABASE ${POSTGRES_DB}_test;"

      - name: Run migrations
        working-directory: backend
        env:
          DATABASE_URL: postgresql+asyncpg://${{ env.POSTGRES_USER }}:${{ env.POSTGRES_PASSWORD }}@${{ env.POSTGRES_HOST }}:${{ env.POSTGRES_PORT }}/${{ env.POSTGRES_DB }}_test
        run: alembic upgrade head

      - name: Run tests with coverage
        working-directory: backend
        env:
          DATABASE_URL: postgresql+asyncpg://${{ env.POSTGRES_USER }}:${{ env.POSTGRES_PASSWORD }}@${{ env.POSTGRES_HOST }}:${{ env.POSTGRES_PORT }}/${{ env.POSTGRES_DB }}_test
        run: |
          pytest --junitxml=test-results.xml --cov=src --cov-report=xml --cov-report=term-missing --cov-fail-under=68

      - uses: actions/upload-artifact@v4
        if: always()
        with:
          name: test-results
          path: backend/test-results.xml

      - uses: actions/upload-artifact@v4
        if: always()
        with:
          name: coverage-report
          path: backend/coverage.xml

      - uses: codecov/codecov-action@v4
        if: always()
        with:
          file: backend/coverage.xml
          flags: backend
          name: backend-coverage
          fail_ci_if_error: false

  api-tests:
    name: API Tests
    runs-on: ubuntu-latest
    needs: [lint]
    services:
      postgres:
        image: postgres:15
        env:
          POSTGRES_USER: ${{ env.POSTGRES_USER }}
          POSTGRES_PASSWORD: ${{ env.POSTGRES_PASSWORD }}
          POSTGRES_DB: ${{ env.POSTGRES_DB }}
        ports: ['5432:5432']
        options: >-
          --health-cmd pg_isready
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5

    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ env.PYTHON_VERSION }}
      - run: pip install -r backend/requirements.txt
        working-directory: backend
      - name: Create test database
        run: |
          PGPASSWORD=${{ env.POSTGRES_PASSWORD }} psql -h localhost -U ${{ env.POSTGRES_USER }} -d ${{ env.POSTGRES_DB }} -c "CREATE DATABASE ${POSTGRES_DB}_test;"
      - name: Run API tests
        working-directory: backend
        env:
          DATABASE_URL: postgresql+asyncpg://${{ env.POSTGRES_USER }}:${{ env.POSTGRES_PASSWORD }}@${{ env.POSTGRES_HOST }}:${{ env.POSTGRES_PORT }}/${{ env.POSTGRES_DB }}_test
        run: pytest -m api -v

  integration-tests:
    name: Integration Tests
    runs-on: ubuntu-latest
    needs: [lint]
    services:
      postgres: {...}  # Same as above
      redis: {...}     # Same as above

    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ env.PYTHON_VERSION }}
      - run: pip install -r backend/requirements.txt
        working-directory: backend
      - name: Create test database
        run: |
          PGPASSWORD=${{ env.POSTGRES_PASSWORD }} psql -h localhost -U ${{ env.POSTGRES_USER }} -d ${{ env.POSTGRES_DB }} -c "CREATE DATABASE ${POSTGRES_DB}_test;"
      - name: Run integration tests
        working-directory: backend
        env:
          DATABASE_URL: postgresql+asyncpg://${{ env.POSTGRES_USER }}:${{ env.POSTGRES_PASSWORD }}@${{ env.POSTGRES_HOST }}:${{ env.POSTGRES_PORT }}/${{ env.POSTGRES_DB }}_test
          REDIS_URL: ${{ env.REDIS_URL }}
        run: pytest -m integration -v
```

## Anti-patterns

- **Running all tests on every file change** — use `paths:` filters to scope workflows.
- **No health checks on service containers** — tests may start before DB is ready, causing flakes.
- **Not chaining with `needs:`** — lint/typecheck runs in parallel with tests, wasting CI time on known failures.
- **No coverage threshold** — coverage can regress silently; use `--cov-fail-under` to enforce baseline.
- **Uploading artifacts unconditionally** — use `if: always()` for test results, `if: failure()` for debug traces.
- **Blocking CI on Codecov failures** — set `fail_ci_if_error: false` to avoid flakes from Codecov API.
- **Polling health endpoints without timeout** — add `timeout 30` to prevent infinite hangs.
- **Running E2E against real LLM/payment APIs** — mock external services with `USE_MOCK_LLM: 'true'` env vars.
- **Not uploading E2E traces** — Playwright traces are essential for debugging headless failures.
