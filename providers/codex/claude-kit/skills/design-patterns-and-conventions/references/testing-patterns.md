# Testing Patterns for FastAPI Architectures

Testing strategies and patterns for the layered architecture, dependency injection, and multi-mode entrypoint patterns observed in the repos.

---

## Testing Layered Architecture

### Unit Testing the Service Layer

**Intent:** Test business logic in isolation without HTTP or database concerns.

**Pattern:**
- Mock the DAO/repository layer
- Focus on business rules, validation, orchestration
- Use pytest fixtures for common test data

**Example:**
```python
# tests/test_supplier_service.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from app.supplier.service import create_supplier, SupplierAlreadyExistsError
from app.supplier.models import SupplierCreate

@pytest.fixture
def mock_dao():
    dao = AsyncMock()
    return dao

@pytest.mark.asyncio
async def test_create_supplier_success(mock_dao):
    # Arrange
    mock_dao.supplier_exists_by_email.return_value = False
    mock_dao.create_supplier.return_value = {"id": 1, "name": "Acme Corp", "email": "acme@example.com"}
    data = SupplierCreate(name="Acme Corp", email="acme@example.com")
    
    # Act
    supplier = await create_supplier(data, mock_dao)
    
    # Assert
    assert supplier["name"] == "Acme Corp"
    mock_dao.supplier_exists_by_email.assert_called_once_with("acme@example.com")
    mock_dao.create_supplier.assert_called_once()

@pytest.mark.asyncio
async def test_create_supplier_duplicate_email(mock_dao):
    # Arrange
    mock_dao.supplier_exists_by_email.return_value = True
    data = SupplierCreate(name="Acme Corp", email="acme@example.com")
    
    # Act & Assert
    with pytest.raises(SupplierAlreadyExistsError):
        await create_supplier(data, mock_dao)
```

---

## Testing Routers (Integration Tests)

**Intent:** Test HTTP endpoints end-to-end, including validation, serialization, and response envelopes.

**Pattern:**
- Use FastAPI `TestClient`
- Mock dependencies (database, Kafka, external APIs) via `app.dependency_overrides`
- Assert response status, headers, and JSON structure (ResponseData envelope)

**Example:**
```python
# tests/test_supplier_router.py
import pytest
from fastapi.testclient import TestClient
from app.main import get_app
from app.connection import get_connection_handler_for_app

@pytest.fixture
def client():
    app = get_app()
    # Override database dependency with mock
    async def mock_connection_handler():
        mock_handler = MagicMock()
        mock_handler.session = AsyncMock()
        yield mock_handler
    
    app.dependency_overrides[get_connection_handler_for_app] = mock_connection_handler
    return TestClient(app)

def test_create_supplier_endpoint(client):
    # Arrange
    payload = {"name": "Acme Corp", "email": "acme@example.com"}
    
    # Act
    response = client.post("/supplier", json=payload)
    
    # Assert
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["data"]["name"] == "Acme Corp"
    assert data["message"] == "Supplier created successfully"

def test_create_supplier_validation_error(client):
    # Arrange
    payload = {"name": ""}  # Missing required email, empty name
    
    # Act
    response = client.post("/supplier", json=payload)
    
    # Assert
    assert response.status_code == 400
    data = response.json()
    assert data["success"] is False
    assert len(data["errors"]) > 0
```

---

## Testing DAO/Repository Layer

**Intent:** Test data access logic with a real or in-memory database.

**Pattern:**
- Use an in-memory SQLite database or a test PostgreSQL instance (via Docker)
- Use pytest fixtures to set up/tear down database schema and seed data
- Test queries, transactions, rollback behavior

**Example:**
```python
# tests/test_supplier_dao.py
import pytest
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_scoped_session
from sqlalchemy.orm import sessionmaker
from asyncio import current_task
from app.supplier.dao import SupplierDao
from app.supplier.models import SupplierCreate, Supplier

@pytest.fixture
async def async_session():
    # In-memory SQLite for tests
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)  # Create tables
    
    session_factory = async_scoped_session(
        sessionmaker(engine, expire_on_commit=False, class_=AsyncSession),
        scopefunc=current_task,
    )
    session = session_factory()
    yield session
    await session.close()
    await engine.dispose()

@pytest.mark.asyncio
async def test_create_supplier(async_session):
    # Arrange
    dao = SupplierDao(async_session)
    data = SupplierCreate(name="Acme Corp", email="acme@example.com")
    
    # Act
    supplier = await dao.create_supplier(data)
    await async_session.commit()
    
    # Assert
    assert supplier.id is not None
    assert supplier.name == "Acme Corp"
    
    # Verify persistence
    fetched = await dao.get_supplier_by_id(supplier.id)
    assert fetched.email == "acme@example.com"
```

---

## Testing Dependency Injection

**Intent:** Ensure `Depends()` generators clean up resources correctly.

**Pattern:**
- Test that the dependency yields the expected object
- Test that cleanup (close, rollback) happens in `finally` even on exception

**Example:**
```python
# tests/test_connection_handler.py
import pytest
from app.connection import get_connection_handler_for_app, ConnectionHandler

@pytest.mark.asyncio
async def test_connection_handler_cleanup():
    # Arrange
    gen = get_connection_handler_for_app()
    
    # Act
    handler = await gen.__anext__()
    
    # Assert: handler is yielded
    assert isinstance(handler, ConnectionHandler)
    assert handler.session is not None
    
    # Act: trigger cleanup
    try:
        await gen.__anext__()
    except StopAsyncIteration:
        pass  # Expected; generator exhausted after cleanup
    
    # Assert: session is closed (mock or check actual close)
    # (In real test, you'd spy on handler.close() to verify it was called)
```

---

## Testing Multi-Mode Entrypoint

**Intent:** Ensure the correct `main()` function is called based on `MODE`.

**Pattern:**
- Mock `loaded_config.MODE` to different values
- Assert the correct main function is invoked

**Example:**
```python
# tests/test_entrypoint.py
import pytest
from unittest.mock import patch, MagicMock

@patch("entrypoint.loaded_config")
@patch("entrypoint.server_main")
@patch("entrypoint.consumer_main")
@patch("entrypoint.worker_main")
def test_entrypoint_server_mode(mock_worker, mock_consumer, mock_server, mock_config):
    # Arrange
    mock_config.MODE = "server"
    
    # Act
    import entrypoint  # Import triggers the if/elif logic
    
    # Assert
    mock_server.assert_called_once()
    mock_consumer.assert_not_called()
    mock_worker.assert_not_called()

@patch("entrypoint.loaded_config")
@patch("entrypoint.consumer_main")
def test_entrypoint_consumer_mode(mock_consumer, mock_config):
    # Arrange
    mock_config.MODE = "consumer"
    
    # Act
    import entrypoint
    
    # Assert
    mock_consumer.assert_called_once()
```

---

## Testing Singleton Metaclass

**Intent:** Ensure only one instance is created, even with multiple calls.

**Pattern:**
- Instantiate the class multiple times
- Assert all references point to the same instance

**Example:**
```python
# tests/test_singleton.py
from global_utils.metaclasses import Singleton

def test_singleton_single_instance():
    # Arrange
    class MyClass(metaclass=Singleton):
        def __init__(self):
            self.value = 42
    
    # Act
    instance1 = MyClass()
    instance2 = MyClass()
    
    # Assert
    assert instance1 is instance2  # Same object
    instance1.value = 100
    assert instance2.value == 100  # Shared state
```

---

## Testing Response Envelope

**Intent:** Ensure all endpoints return the uniform `ResponseData` shape.

**Pattern:**
- Test successful responses (success=True, data present)
- Test error responses (success=False, errors present)
- Validate JSON schema

**Example:**
```python
# tests/test_response_envelope.py
from app.utils import ResponseData

def test_response_data_ok():
    # Act
    response = ResponseData.ok(data={"id": 1, "name": "Test"}, message="Created")
    
    # Assert
    assert response.success is True
    assert response.data == {"id": 1, "name": "Test"}
    assert response.message == "Created"
    assert response.errors == []

def test_response_data_error():
    # Act
    response = ResponseData.error(errors=["Invalid email", "Name too short"], message="Validation failed")
    
    # Assert
    assert response.success is False
    assert response.data is None
    assert response.message == "Validation failed"
    assert len(response.errors) == 2
```

---

## Testing Kafka Integration

**Intent:** Test Kafka producer/consumer logic without a real Kafka broker.

**Pattern:**
- Use `aiokafka` test utilities or mock the producer/consumer
- Test message serialization, topic routing, handler dispatch

**Example (mocked producer):**
```python
# tests/test_kafka_producer.py
import pytest
from unittest.mock import AsyncMock, patch
from services.kafka.producer.producer import AsyncEventEmitterWrapper

@pytest.mark.asyncio
@patch("services.kafka.producer.producer.AIOKafkaProducer")
async def test_produce_message(mock_producer_class):
    # Arrange
    mock_producer = AsyncMock()
    mock_producer_class.return_value = mock_producer
    emitter = AsyncEventEmitterWrapper()
    
    # Act
    await emitter.emit("test-topic", {"event": "user.created", "user_id": 123})
    
    # Assert
    mock_producer.send_and_wait.assert_called_once()
    call_args = mock_producer.send_and_wait.call_args
    assert call_args[0][0] == "test-topic"  # Topic
    # Verify serialized message contains expected data
```

**Example (mocked consumer):**
```python
# tests/test_kafka_consumer.py
import pytest
from unittest.mock import AsyncMock, patch
from services.kafka.consumer.consumer import handle_message

@pytest.mark.asyncio
async def test_handle_message():
    # Arrange
    message = {"event": "user.created", "user_id": 123}
    mock_handler = AsyncMock()
    
    # Act
    await handle_message(message, mock_handler)
    
    # Assert
    mock_handler.assert_called_once_with(message)
```

---

## Testing Temporal Workflows

**Intent:** Test Temporal workflow logic in isolation.

**Pattern:**
- Use Temporal's test server or mock the workflow/activity context
- Test workflow execution paths, activity retries, error handling

**Example:**
```python
# tests/test_temporal_workflow.py
import pytest
from temporalio.testing import WorkflowEnvironment
from services.temporal.workflows import MyWorkflow
from services.temporal.activities import my_activity

@pytest.mark.asyncio
async def test_workflow_execution():
    # Arrange
    async with await WorkflowEnvironment.start_time_skipping() as env:
        # Act
        result = await env.client.execute_workflow(
            MyWorkflow.run,
            "test-input",
            id="test-workflow-id",
            task_queue="test-queue",
        )
        
        # Assert
        assert result == "expected-output"
```

---

## Summary: Test Coverage Checklist

| Layer | What to test | Tools |
|-------|--------------|-------|
| **Service** | Business logic, validation, orchestration | pytest, AsyncMock |
| **Router** | HTTP endpoints, request/response validation, envelope | TestClient, dependency_overrides |
| **DAO** | Queries, transactions, rollback | In-memory DB (SQLite), pytest fixtures |
| **Dependency Injection** | Resource cleanup, session scoping | pytest, AsyncMock |
| **Multi-mode entrypoint** | MODE-based dispatch | Mock loaded_config |
| **Singleton** | Single instance guarantee | Direct instantiation tests |
| **Response Envelope** | JSON shape, success/error fields | Pydantic model tests |
| **Kafka** | Producer/consumer, serialization, handler dispatch | Mock AIOKafkaProducer/Consumer |
| **Temporal** | Workflow execution, activity retries | Temporal test environment |

**Target Coverage:**
- Aim for >70% code coverage on critical paths (service layer, DAO, routers)
- 100% coverage on business logic (service methods)
- Integration tests for all public API endpoints
- Smoke tests for multi-mode entrypoints (server, consumer, worker)

---

## CI/CD Integration

**Pattern:** Run tests automatically on every commit/PR.

**Example (GitHub Actions):**
```yaml
# .github/workflows/test.yml
name: Test
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:15
        env:
          POSTGRES_PASSWORD: test
        options: >-
          --health-cmd pg_isready
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      - run: pip install -r requirements.txt
      - run: pytest --cov=app --cov-report=xml
      - run: coverage report --fail-under=70  # Fail if coverage < 70%
```

**Anti-pattern to avoid:**
- No tests (most repos currently have near-zero coverage)
- Tests that depend on external services (Kafka, real databases) without mocks/fixtures
- Flaky tests (race conditions, timing issues in async tests)
- Tests that share state (one test's data leaks into another)
