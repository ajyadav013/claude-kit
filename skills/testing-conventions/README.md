# Testing Conventions

Testing patterns and conventions derived from real-world production Python/FastAPI and React services.

## What this skill covers

- **pytest + pytest-asyncio**: Session-scoped event loop, async fixtures, `@pytest.mark.asyncio`
- **Conftest fixtures**: Test DB isolation, authenticated client, dependency overrides, cleanup
- **Async test fixtures**: DAO/service/route testing with `db_connection` session factory
- **Mocking external services**: AsyncMock for Kafka, Temporal, HTTP; unittest.mock.patch for config
- **Factory patterns**: factory.Factory + factory.Faker for reusable test data generation
- **Frontend testing**: Vitest config with jsdom, coverage thresholds, setup files
- **Coverage gaps**: Honest assessment of thin coverage across repos; recommended baseline

## Provenance

Derived from real-world production Python/FastAPI and React services.

## How to apply

1. **For new FastAPI services**: Start with integration test conftest pattern (test DB override, Alembic migrations, authenticated client, cleanup fixtures).
2. **For services with thin coverage**: Establish recommended baseline (DAO layer, service happy path + error cases, route contracts, external mocks).
3. **For unit tests without DB**: Use UnittestConnectionManager + dependency override pattern.
4. **For mocking Kafka/Temporal**: Use AsyncMock fixture patterns for producer/consumer/client.
5. **For frontend components**: Use Vitest config; start with lib/hooks coverage before raising thresholds.

- **Codebase-derived**: Session event loop patterns, test DB isolation, authenticated client fixtures, UnittestConnectionManager singleton, dependency override registration, factory fixtures, AsyncMock for Kafka/Temporal, DAO test structure, Vitest config, coverage gap audit.
- **Internet-confirmed**: pytest-asyncio event loop scope (https://pytest-asyncio.readthedocs.io/), httpx.AsyncClient usage (https://www.python-httpx.org/async/), factory.Factory with LazyAttribute/Faker (https://factoryboy.readthedocs.io/), Vitest jsdom environment (https://vitest.dev/config/), unittest.mock.AsyncMock (https://docs.python.org/3/library/unittest.mock.html).
