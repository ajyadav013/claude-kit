# pytest-asyncio Modes and Fixture Decorators

Common patterns and gotchas for pytest-asyncio configuration.

## pytest-asyncio Mode

**Auto mode** (default in older versions, deprecated in 0.21+):
```ini
# pytest.ini or pyproject.toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
```

Auto mode automatically detects `async def test_*` functions and converts them to async tests. No `@pytest.mark.asyncio` required.

**Strict mode** (recommended in 0.21+):
```ini
[tool.pytest.ini_options]
asyncio_mode = "strict"
```

Strict mode requires explicit `@pytest.mark.asyncio` marker on every async test function. Prevents accidental async test execution.

**Most repos use**: Strict mode with explicit `@pytest.mark.asyncio` markers.

## Fixture Decorators: @pytest.fixture vs @pytest_asyncio.fixture

### @pytest.fixture with async def

**Pattern** (most common):
```python
@pytest.fixture
async def client(app):
    async with httpx.AsyncClient(transport=ASGITransport(app=app)) as ac:
        yield ac
```

Works in both auto and strict mode. `@pytest.fixture` with `async def` is supported by pytest-asyncio and is the most common pattern.

### @pytest_asyncio.fixture

**Pattern** (explicit):
```python
@pytest_asyncio.fixture
async def client():
    async with httpx.AsyncClient(app=test_app) as http_client:
        try:
            yield http_client
        finally:
            await http_client.aclose()
```

Explicitly marks the fixture as async. More verbose but clearer intent. Required if you want to distinguish async fixtures from sync fixtures explicitly.

**When to use**: 
- When you want explicit async fixture declaration
- When migrating from older pytest-asyncio versions
- When you have mixed sync/async fixtures and want clarity

**When NOT to use**:
- If you're already using `@pytest.fixture` with `async def` consistently
- If you're targeting pytest-asyncio 0.21+ (auto mode deprecated)

### Session-Scoped Event Loop

**Pattern A** (recommended):
```python
@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()
```

Creates a new event loop once per session. No `async def` needed; this fixture is synchronous.

**Pattern B** (alternative):
```python
@pytest.fixture(scope="session", autouse=True)
def event_loop():
    loop = asyncio.get_event_loop()
    try:
        yield loop
    finally:
        loop.close()
```

Uses the default event loop; always closes in `finally`. `autouse=True` means this fixture runs automatically without being requested.

**Pattern C** (alternative):
```python
@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()
```

Uses the event loop policy to create a new loop; same effect as Pattern A.

## Anti-Pattern: Inconsistent Decorator Usage

**Bad** (mixing styles randomly):
```python
@pytest.fixture
async def dao(db_connection):
    async with db_connection() as session:
        yield TenantDAO(session)

@pytest_asyncio.fixture  # Different decorator for no reason
async def service(dao):
    yield TenantService(dao)
```

**Good** (consistent style):
```python
@pytest.fixture
async def dao(db_connection):
    async with db_connection() as session:
        yield TenantDAO(session)

@pytest.fixture  # Same decorator style
async def service(dao):
    yield TenantService(dao)
```

Pick one style and stick with it. `@pytest.fixture` with `async def` is simpler and works everywhere.

## Recommendation

1. **Use strict mode** (`asyncio_mode = "strict"`) in pytest.ini/pyproject.toml
2. **Use `@pytest.fixture` with `async def`** for all async fixtures (simplest, most common)
3. **Use `@pytest.mark.asyncio`** on all `async def test_*` functions (required in strict mode)
4. **Session-scoped event loop**: Use `@pytest.fixture(scope="session")` with `asyncio.new_event_loop()` (Pattern A)

## References

- pytest-asyncio docs: https://pytest-asyncio.readthedocs.io/en/latest/reference/configuration.html
