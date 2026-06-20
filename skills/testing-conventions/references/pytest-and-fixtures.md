# Pytest and Fixtures

Core pytest patterns for async testing with FastAPI services.

## Session-Scoped Event Loop

**Pattern A** (recommended for integration tests):

```python
# app/tests/conftest.py
@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()
```

Creates a new event loop once per test session. Avoids loop closure conflicts when running multiple async tests.

**Pattern B** (alternative):

```python
# app/tests/conftest.py
@pytest.fixture(scope="session", autouse=True)
def event_loop():
    loop = asyncio.get_event_loop()
    try:
        yield loop
    finally:
        loop.close()
```

Uses the default event loop; always closes in `finally`.

**Pattern C**:

```python
# app/tests/conftest.py
@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()
```

Uses the event loop policy to create a new loop; same effect as Pattern A.

## Test Database Isolation

**Env var override before imports** (example pattern):

```python
# app/tests/conftest.py
import os

# Override env vars BEFORE any app code imports settings
os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://user:<REDACTED>@postgres:5432/app_test_db",
)
os.environ["REDIS_URL"] = os.environ.get(
    "TEST_REDIS_URL",
    "redis://redis:6379/1",  # DB 1 for tests, DB 0 for dev
)

# NOW safe to import app code
from config.settings import settings
from app.connection import ConnectionManager
```

**Migration setup** (example pattern):

```python
# app/tests/conftest.py
@pytest.fixture(scope="session", autouse=True)
async def _run_migrations():
    """Run Alembic migrations on the test database once per session."""
    import subprocess

    result = subprocess.run(
        ["alembic", "upgrade", "head"],
        cwd="/app",
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Alembic migration failed:\n{result.stderr}")
    yield
```

Runs once before any tests; ensures test DB schema is up to date.

## Cleanup Fixtures

**Autouse cleanup** (example pattern):

```python
# app/tests/conftest.py
@pytest.fixture(autouse=True)
async def cleanup():
    yield  # Test runs here
    # Cleanup after each test
    try:
        redis = Redis.from_url(settings.REDIS_URL, decode_responses=True)
        await redis.flushdb()
        await redis.aclose()
    except Exception:
        pass
    try:
        engine = create_async_engine(settings.DATABASE_URL)
        async with engine.begin() as conn:
            # Drop any tenant schemas created during the test
            tenant_schemas = await conn.execute(
                text("SELECT schema_name FROM tenants WHERE schema_name IS NOT NULL")
            )
            for row in tenant_schemas.fetchall():
                await conn.execute(text(f"DROP SCHEMA IF EXISTS {row[0]} CASCADE"))
            
            # Truncate all tables
            await conn.execute(
                text(
                    "TRUNCATE TABLE "
                    "usage_records, organization_subscriptions, subscription_plans, "
                    "password_history, tenant_entitlements, ... "
                    "user_tenant_mappings, tenants, users, organizations "
                    "RESTART IDENTITY CASCADE"
                )
            )
        await engine.dispose()
    except Exception:
        pass
    ConnectionManager._instance = None
```

Runs after every test; flushes Redis, truncates tables, drops tenant schemas.

**Alternative cleanup** (drop + create tables):

```python
# app/tests/conftest.py
async def db_setup(engine):
    async with engine.begin() as conn:
        # Drop all tables first to ensure a clean state
        await conn.run_sync(Base.metadata.drop_all)
        # Drop enum types
        await conn.execute(text("DROP TYPE IF EXISTS eventtypestatus;"))
        # Create all tables
        await conn.run_sync(Base.metadata.create_all)

async def db_cleanup(engine):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

@pytest_asyncio.fixture(autouse=False)
async def db_connection():
    cm = UnittestConnectionManager()
    try:
        engine = cm.get_db_engine()
        await db_setup(engine)
        yield cm.get_session_factory()
        await db_cleanup(engine)
    finally:
        await cm.close_connections()
```

More heavyweight; useful for isolated unit tests that need fresh schema each time.

## HTTP Client Fixtures

**Pattern A** (httpx.AsyncClient with ASGITransport):

```python
# app/tests/conftest.py
@pytest.fixture(scope="session")
def app():
    from app.application import get_app
    return get_app()

@pytest.fixture
async def client(app):
    ConnectionManager._instance = None
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
```

**Pattern B** (httpx.AsyncClient with direct app):

```python
# app/tests/conftest.py
def test_app():
    return get_app()

test_app = test_app()

@pytest_asyncio.fixture
async def client():
    async with httpx.AsyncClient(app=test_app, base_url="http://testserver/v1.0") as http_client:
        try:
            yield http_client
        finally:
            await http_client.aclose()
```

Always close the client in `finally`.

## Authenticated Client Fixture

**Register + login + attach cookies** (example pattern):

```python
# app/tests/conftest.py
@pytest.fixture
async def authenticated_client(client: httpx.AsyncClient):
    await client.post(
        "/v1/auth/register",
        json={
            "email": "testuser@example.com",
            "password": "TestPassword123!",
            "first_name": "Test",
            "last_name": "User",
            "role": "sys_admin",
        },
    )
    resp = await client.post(
        "/v1/auth/login",
        json={
            "email": "testuser@example.com",
            "password": "TestPassword123!",
        },
    )
    cookies = resp.cookies
    client.cookies.update(cookies)
    yield client
    await client.post("/v1/auth/logout")
```

Creates a logged-in sys_admin user; subsequent requests use the authenticated session.

## Dependency Override Pattern

**FastAPI dependency injection override** (example pattern):

```python
# app/tests/conftest.py
from app.db.connection import (
    get_connection_handler_for_app,
    get_connection_handler_for_func,
)
from tests.utils import (
    get_test_connection_handler_for_app,
    get_test_connection_handler_for_func,
)

test_app.dependency_overrides[get_connection_handler_for_app] = get_test_connection_handler_for_app
test_app.dependency_overrides[get_connection_handler_for_func] = get_test_connection_handler_for_func
```

Replaces production DB connections with test connections at the module level.

**UnittestConnectionManager** (singleton pattern):

```python
# app/tests/utils.py
from app.utils.metaclasses import Singleton

class UnittestConnectionManager(metaclass=Singleton):
    def __init__(self, db_url=str(loaded_config.db_url)):
        self._db_engine, self._db_session_factory = self._setup_db(db_url)

    @staticmethod
    def _setup_db(db_url):
        async_db_url = db_url.replace("postgresql+psycopg2://", "postgresql+asyncpg://")
        engine = create_async_engine(
            async_db_url,
            echo=loaded_config.DB_ECHO,
            pool_size=2000,
            max_overflow=5000,
            pool_timeout=60,
        )
        session_factory = async_scoped_session(
            sessionmaker(engine, expire_on_commit=False, class_=AsyncSession),
            scopefunc=current_task,
        )
        return engine, session_factory

    async def close_connections(self):
        await self._db_engine.dispose()
```

Singleton ensures all test fixtures share the same connection pool.

## Logging Configuration

**Configure test logging** (example pattern):

```python
# app/tests/conftest.py
@pytest.fixture(scope="session", autouse=True)
def configure_test_logging():
    """Configure logging for tests."""
    configure_logging(
        log_level="DEBUG",
        log_format="text",
        service_name="app-tests",
    )
```

Ensures test runs produce readable logs.
