# Example Patterns

Representative code patterns observed in production FastAPI services.

## Example: AsyncSession setup with async_scoped_session

**Pattern:** AsyncSession factory with current_task scope, FastAPI lifespan context manager.

- `app/connection.py` — AsyncSession factory with current_task scope

```python
from sqlalchemy.ext.asyncio import (
    AsyncSession, create_async_engine, async_scoped_session, AsyncEngine
)
from sqlalchemy.orm import sessionmaker
from asyncio import current_task

class ConnectionManager:
    _db_engine: AsyncEngine
    _db_session_factory: Callable[..., AsyncSession]

    @staticmethod
    def _setup_db() -> Tuple[AsyncEngine, Callable[..., AsyncSession]]:
        db_url = str(settings.database_url)
        engine = create_async_engine(
            db_url, echo=settings.db_echo, pool_pre_ping=True
        )
        session_factory = async_scoped_session(
            sessionmaker(engine, expire_on_commit=False, class_=AsyncSession),
            scopefunc=current_task
        )
        return engine, session_factory

    async def close_connections(self) -> None:
        await self._db_engine.dispose()
```

- `app/lifetime.py` — FastAPI lifespan

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    _init_connections()
    yield
    await _close_connections()

# In application.py:
app = FastAPI(lifespan=lifespan, ...)
```

## Example: AsyncSession with postgresql+asyncpg

**Pattern:** AsyncSession factory with current_task scope, postgresql+asyncpg driver URL replacement.

- `app/connection.py` — AsyncSession factory

```python
from sqlalchemy.ext.asyncio import (
    AsyncSession, create_async_engine, async_scoped_session, AsyncEngine
)
from sqlalchemy.orm import sessionmaker
from asyncio import current_task

class ConnectionManager:
    _db_engine: AsyncEngine
    _db_session_factory: Callable[..., AsyncSession]

    @staticmethod
    def _setup_db() -> Tuple[AsyncEngine, Callable[..., AsyncSession]]:
        db_url = str(settings.POSTGRES_READ_WRITE)
        async_db_url = db_url.replace("postgresql://", "postgresql+asyncpg://")
        engine = create_async_engine(
            async_db_url, echo=settings.DB_ECHO, pool_pre_ping=True
        )
        session_factory = async_scoped_session(
            sessionmaker(engine, expire_on_commit=False, class_=AsyncSession),
            scopefunc=current_task
        )
        return engine, session_factory

    async def close_connections(self) -> None:
        await self._db_engine.dispose()
```

- `app/lifetime.py` — FastAPI lifespan

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI

@asynccontextmanager
async def lifespan(app: FastAPI):
    _init_connections()
    yield
    await _close_connections()

# In application.py:
app = FastAPI(lifespan=lifespan, ...)
```

## Example: Sync Kafka consumer → async handler bridge

**Pattern:** Blocking kafka-python consumer in thread, async handlers via run_coroutine_threadsafe.

- `services/kafka/consumer.py` — Blocking consumer in thread, async handlers via run_coroutine_threadsafe

```python
import asyncio
from kafka import KafkaConsumer as SyncKafkaConsumer

def _run_kafka_consumer(loop: asyncio.AbstractEventLoop, consumer_state: dict):
    consumer = SyncKafkaConsumer(
        bootstrap_servers=["broker1:9093"],
        security_protocol="SASL_SSL",
        sasl_mechanism="GSSAPI",
        # ...
    )
    consumer.subscribe(topics)

    for tp, messages in consumer.poll(timeout_ms=5000).items():
        upload_coros = []
        for msg in messages:
            for task_fn in topic_tasks:
                upload_coros.append(task_fn(payload))

        async def _upload_batch(coros):
            return await asyncio.gather(*coros)

        future = asyncio.run_coroutine_threadsafe(_upload_batch(upload_coros), loop)
        future.result()  # block thread until handlers complete
        consumer.commit()

async def main():
    loop = asyncio.get_running_loop()
    await asyncio.gather(
        asyncio.to_thread(_run_kafka_consumer, loop, {}),
        _healthz(),
        _readyz()
    )
```

- `app/lifetime.py` — FastAPI lifespan

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    _init_connections()
    yield
    await _close_connections()
```

- `requirements/requirements.txt` — gcloud-aio-storage (async GCS client)

```
gcloud-aio-storage
```

## Example: Worker concurrency with graceful shutdown

**Pattern:** asyncio.gather for worker concurrency, signal-based graceful shutdown, AsyncHTTPClient wrapper.

- `services/temporal/run_workers.py` — gather + signal handlers

```python
import asyncio
import signal

async def worker_main():
    await on_startup()
    client = await initialize_client()
    worker_tasks = await get_worker_tasks(client)
    health_task = asyncio.create_task(_healthz())
    ready_task = asyncio.create_task(_readyz())
    worker_tasks.extend([(None, health_task), (None, ready_task)])

    async def async_shutdown():
        for worker_obj, worker_task in worker_tasks:
            if worker_obj:
                await worker_obj.shutdown()
            worker_task.cancel()
        await asyncio.gather(*[task for _, task in worker_tasks], return_exceptions=True)

    def on_signal_received(*args, **kwargs):
        asyncio.create_task(async_shutdown())

    loop = asyncio.get_running_loop()
    loop.add_signal_handler(signal.SIGTERM, on_signal_received, None)
    loop.add_signal_handler(signal.SIGINT, on_signal_received, None)

    await asyncio.gather(*[task for _, task in worker_tasks], return_exceptions=True)
    await on_shutdown()
```

- `global_utils/http.py` — AsyncHTTPClient wrapper

```python
import aiohttp

class AsyncHTTPClient:
    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None

    async def close(self) -> None:
        if self.session:
            await self.session.close()
            self.session = None

    async def fetch(
        self, method: str, url: str, retries: int = 1, delay: float = 0.5,
        payload: Optional[dict] = None, headers: Optional[dict] = None, **kwargs
    ):
        if not self.session:
            self.session = aiohttp.ClientSession()
        # retry loop + response processing
```

## Example: Sync-in-async anti-pattern

**Pattern:** Anti-pattern example — sync BigQuery client blocking async code.

- `utils/bigquery_utils.py` — WRONG: sync client in async context (no offloading)

```python
from google.cloud import bigquery

class BigQueryUtils:
    def __init__(self, project_id: str):
        self.client = bigquery.Client(project=project_id)  # SYNC

    def query_data(self, query: str):
        query_job = self.client.query(query)  # BLOCKS event loop
        results = query_job.result()  # BLOCKS
        return [dict(row) for row in results]

# Called from async Temporal activities WITHOUT asyncio.to_thread(...)
```

**Correct fix:** Wrap in `asyncio.to_thread(...)` or use an async client.

## Example: Async request library with circuit breaker

**Pattern:** Async HTTP library with protocol plugins, circuit breaker, retry, pydantic models.

- `async_requests/request.py` — Unified async request function

```python
from async_requests.models import ProtocolInfo, ResponseModel, CircuitBreakerConfig

async def request(
    url: str,
    data: Optional[Union[Dict, str]] = None,
    protocol: str = '',
    protocol_info: Union[Dict, ProtocolInfo] = None,
    **kwargs
) -> ResponseModel:
    # Protocol plugin registry (HTTP, FTP, SFTP)
    # Circuit breaker + retry via protocol_info.circuit_breaker_config
    # Returns pydantic ResponseModel
```

- `async_requests/models.py` — Pydantic models

```python
class CircuitBreakerConfig(BaseModel):
    maximum_failures: Optional[int] = None
    timeout: Optional[int] = None
    retry_config: Optional[RetryConfig] = None

class ProtocolInfo(BaseModel):
    request_type: str
    timeout: Optional[int] = None
    headers: Optional[Dict[str, Any]] = None
    circuit_breaker_config: Optional[CircuitBreakerConfig] = None

class ResponseModel(BaseModel):
    url: str
    payload: Any
    external_call_request_time: str
    error_message: Optional[str] = None
```
