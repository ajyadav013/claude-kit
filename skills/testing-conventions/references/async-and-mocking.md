# Async and Mocking

Patterns for async test fixtures, mocking external services, and factory-based test data generation.

## Async Test Fixtures

**Function-scoped DAO fixture** (example pattern):

```python
# app/tests/brand/test_dao.py
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
```

Wraps DAO instantiation in async context manager from `db_connection` session factory. Each test can create test data via a separate session.

**@pytest.mark.asyncio required** (standard practice):

```python
# app/tests/test_slack_alert.py
@patch("config.docker_config.loaded_config", MockConfig)
@patch("app.utils.slack.alerts.publish_slack_alert_push_event")
@pytest.mark.asyncio
async def test_raise_slack_alert_success(mock_publish_event, valid_slack_alert_schema):
    mock_publish_event.return_value = True
    response = await raise_slack_alert(valid_slack_alert_schema)
    assert response["success"]
    mock_publish_event.assert_called_once()
```

All async test functions require `@pytest.mark.asyncio` decorator.

## Mocking External Services

### AsyncMock for Kafka

**Producer mock** (example pattern):

```python
# app/tests/conftest.py
@pytest.fixture
async def mock_kafka_producer():
    """Mock Kafka producer for testing."""
    from unittest.mock import AsyncMock
    
    producer = AsyncMock()
    producer.emit = AsyncMock()
    producer.emit_batch = AsyncMock()
    producer.close = AsyncMock()
    
    return producer
```

**Consumer mock** (example pattern):

```python
# app/tests/conftest.py
@pytest.fixture
async def mock_kafka_consumer():
    """Mock Kafka consumer for testing."""
    from unittest.mock import AsyncMock
    
    consumer = AsyncMock()
    consumer.start = AsyncMock()
    consumer.stop = AsyncMock()
    consumer.__aiter__ = AsyncMock()
    
    return consumer
```

### AsyncMock for Temporal

**Client mock** (example pattern):

```python
# app/tests/conftest.py
@pytest.fixture
async def mock_temporal_client():
    """Mock Temporal client for testing."""
    from unittest.mock import AsyncMock
    
    client = AsyncMock()
    client.start_workflow = AsyncMock(return_value="test_workflow_id")
    client.get_workflow_handle = AsyncMock()
    client.health_check = AsyncMock(return_value=True)
    
    return client
```

**Activity/workflow info mocks** (example pattern):

```python
# app/tests/unit/temporal/conftest.py
@pytest.fixture(scope="function")
def mock_activity_info():
    """Fixture providing mock activity info."""
    info_mock = MagicMock()
    info_mock.workflow_run_id = str(uuid4())
    return info_mock

@pytest.fixture(scope="function")
def mock_workflow_info():
    """Fixture providing mock workflow info."""
    info = MagicMock()
    info.workflow_id = str(uuid4())
    info.run_id = str(uuid4())
    return info
```

### Mock DAO/Service Pattern

**Mock DAO with AsyncMock methods** (example pattern):

```python
# app/tests/unit/webhook/conftest.py
@pytest.fixture
def mock_webhook_delivery_dao():
    """Mock WebhookDeliveryDAO fixture."""
    dao = MagicMock()
    dao.get_by_pk = AsyncMock()
    dao.get_by_chain_step_id = AsyncMock()
    dao.create_delivery = AsyncMock()
    dao.get_records_by_fields = AsyncMock()
    return dao

@pytest.fixture
def mock_webhook_chain_step_dao():
    """Mock WebhookChainStepDAO fixture."""
    dao = MagicMock()
    dao.get_by_pk = AsyncMock()
    dao.get_by_chain_config_id = AsyncMock()
    dao.create_step = AsyncMock()
    dao.update_by_pk = AsyncMock()
    dao.delete_by_pk = AsyncMock()
    return dao
```

**Mock service** (example pattern):

```python
# app/tests/unit/temporal/conftest.py
@pytest.fixture(scope="function")
def mock_webhook_chain_step_service():
    """Fixture providing mock webhook chain step service."""
    service_mock = AsyncMock()
    service_mock.get_steps_by_chain_config = AsyncMock()
    return service_mock

@pytest.fixture(scope="function")
def mock_async_http_client():
    """Fixture providing mock async HTTP client."""
    client_mock = AsyncMock()
    client_mock.fetch = AsyncMock()
    client_mock.close = AsyncMock()
    return client_mock
```

### unittest.mock.patch for Config/HTTP

**Patching config objects** (example pattern):

```python
# app/tests/test_slack_alert.py
from unittest.mock import patch

class MockConfig:
    SENTRY_ENVIRONMENT = "test"
    SLACK_BOT_TOKEN = "xoxb-<REDACTED>"  # fake value for tests
    SLACK_ALERT_CHANNEL_ID = "C12345678"
    HOSTNAME = "test-host"

@patch("config.docker_config.loaded_config", MockConfig)
def test_generate_slack_error_alert_message(valid_slack_alert_schema):
    payload = generate_slack_error_alert_message(valid_slack_alert_schema)
    assert MockConfig.SENTRY_ENVIRONMENT in payload["blocks"][1]["text"]["text"]
```

**Patching async functions** (example pattern):

```python
# app/tests/test_slack_alert.py
@patch("app.utils.slack.alerts.publish_slack_alert_push_event")
@pytest.mark.asyncio
async def test_raise_slack_alert_failure(mock_publish_event, valid_slack_alert_schema):
    mock_publish_event.side_effect = Exception("Kafka error")
    response = await raise_slack_alert(valid_slack_alert_schema)
    assert not response["success"]
    mock_publish_event.assert_called_once()
```

## Factory Patterns

### factory.Factory with Faker

**WebhookDeliveryCreate factory** (example pattern):

```python
# app/tests/unit/webhook/conftest.py
import factory

class WebhookDeliveryCreateFactory(factory.Factory):
    """Factory for creating WebhookDeliveryCreate test data."""

    class Meta:
        model = WebhookDeliveryCreate

    webhook_chain_step_id = factory.LazyAttribute(lambda n: uuid4())
    step_number = factory.Sequence(lambda n: n + 1)
    url = factory.Faker("url")
    http_method = factory.Faker("random_element", elements=["GET", "POST", "PUT", "DELETE"])
    headers = {"Content-Type": "application/json", "Authorization": "Bearer token"}
    payload = {"user_id": "test123", "amount": 100.50}
    status_code = factory.Faker("random_element", elements=[200, 201, 400, 404, 500])
    delivery_status = factory.Faker("random_element", elements=["success", "failed", "pending"])
    retry_count = factory.Faker("random_int", min=0, max=3)
```

**WorkflowConfig factory** (example pattern):

```python
# app/tests/unit/webhook/conftest.py
class WorkflowConfigFactory(factory.Factory):
    """Factory for creating workflow config test data."""

    class Meta:
        model = WorkflowConfigBase

    name = factory.Faker("company")
    description = factory.Faker("text", max_nb_chars=200)
    workflow_supported_config_id = factory.LazyAttribute(lambda n: str(uuid4()))
    service_name = factory.Faker("word")
    queue_name = factory.Faker("word")
    config_data = {"max_steps": 10, "timeout": 300, "retry_policy": {"max_attempts": 3}}
    is_active = True
```

### Factory Fixtures

**Sample data fixtures** (example pattern):

```python
# app/tests/unit/webhook/conftest.py
@pytest.fixture
def sample_webhook_chain_step():
    """Fixture providing sample webhook chain step data."""
    return WebhookChainStepFactory()

@pytest.fixture
def sample_webhook_delivery_create():
    """Fixture providing sample webhook delivery create data."""
    return WebhookDeliveryCreateFactory()
```

**Dict-based factory** (example pattern):

```python
# app/tests/unit/temporal/conftest.py
class WebhookDeliveryFactory(factory.Factory):
    """Factory for creating webhook delivery test data."""

    class Meta:
        model = dict

    id = factory.LazyAttribute(lambda n: str(uuid4()))
    delivery_status = "success"
    status_code = 200
    response_body = factory.LazyAttribute(lambda n: '{"token": "abc123", "user": {"id": 456}}')
    webhook_chain_step_id = factory.LazyAttribute(lambda n: str(uuid4()))
    url = factory.Faker("url")
    http_method = "POST"
```

## Parametrized Fixtures

**Template resolution test cases** (example pattern):

```python
# app/tests/unit/temporal/conftest.py
@pytest.fixture(
    params=[
        ("simple_template", "${data.user_id}", {"user_id": "123"}, "123"),
        ("nested_template", "${data.user.name}", {"user": {"name": "John"}}, "John"),
        ("step_reference", "${steps[1].response.token}", {}, "__DB_FETCH_NEEDED__:1:response.token"),
        (
            "array_template",
            ["${data.primary_token}", "${data.fallback_token}", "default"],
            {"fallback_token": "fallback123"},
            "fallback123",
        ),
    ]
)
def template_resolution_fixture(request):
    """Parametrized fixture for template resolution test cases."""
    test_name, template, data, expected = request.param
    return {"test_name": test_name, "template": template, "data": data, "expected": expected}
```

**Condition evaluation test cases** (example pattern):

```python
# app/tests/unit/temporal/conftest.py
@pytest.fixture(
    params=[
        (
            {"type": "equals", "field": "current_response.status_code", "value": 200},
            {"current_response": {"status_code": 200}},
            True,
        ),
        (
            {"type": "not_equals", "field": "current_response.status_code", "value": 404},
            {"current_response": {"status_code": 200}},
            True,
        ),
        (
            {"type": "contains", "field": "current_response.body", "value": "success"},
            {"current_response": {"body": "operation success"}},
            True,
        ),
    ]
)
def condition_evaluation_fixture(request):
    """Parametrized fixture for condition evaluation test cases."""
    condition, context, expected = request.param
    return {"condition": condition, "context": context, "expected": expected}
```

**HTTP request test cases** (example pattern):

```python
# app/tests/unit/temporal/conftest.py
@pytest.fixture(
    params=[
        ("GET", {"page": 1, "limit": 10}, {}),
        ("POST", {"name": "John"}, {"notify": True}),
        ("PUT", {"status": "active"}, {"version": 2}),
        ("DELETE", {}, {"reason": "cleanup"}),
    ]
)
def http_request_fixture(request):
    """Parametrized fixture for HTTP request test cases."""
    method, payload, query_params = request.param
    return {"method": method, "payload": payload, "query_params": query_params}
```

## Connection Handler Mocking

**Lightweight connection handler** (example pattern):

```python
# app/tests/unit/temporal/conftest.py
@pytest.fixture(scope="function")
def connection_handler():
    """Fixture providing mock database connection handler - no real DB needed."""
    handler_mock = MagicMock()
    handler_mock.session = MagicMock()
    handler_mock.session_commit = AsyncMock()
    handler_mock.close = AsyncMock()
    return handler_mock
```

No real database required; tests run in-memory against mocked DAOs.
