# Async Boundaries

Patterns for crossing sync/async boundaries and the sync-in-async trap.

## The sync→async bridge (blocking library dispatching async handlers)

**Problem:** A blocking library (kafka-python, blocking I/O) must dispatch async coroutines.

**Solution:** Run the sync code in a thread via `asyncio.to_thread`, pass the event loop reference, and dispatch coroutines back with `asyncio.run_coroutine_threadsafe`.

**Pattern (Kafka consumer bridge):**

```python
import asyncio
from kafka import KafkaConsumer as SyncKafkaConsumer

def _run_kafka_consumer(loop: asyncio.AbstractEventLoop, consumer_state: dict):
    """Blocking kafka-python consumer running in a thread.
    
    Async tasks are scheduled on *loop* via run_coroutine_threadsafe so they
    execute on the main event loop instead of spawning a new one per message.
    """
    consumer = SyncKafkaConsumer(
        bootstrap_servers=["broker1:9093"],
        security_protocol="SASL_SSL",
        sasl_mechanism="GSSAPI",
        group_id="my-group",
        enable_auto_commit=False,
        # ...
    )
    consumer.subscribe(["topic1", "topic2"])

    while True:
        records = consumer.poll(timeout_ms=5000)
        if not records:
            continue

        # Collect async handlers
        upload_coros = []
        for tp, messages in records.items():
            for msg in messages:
                payload = {"topic": msg.topic, "value": msg.value}
                for task_fn in topic_tasks:
                    upload_coros.append(task_fn(payload))

        # Dispatch batch to event loop and wait for completion
        async def _upload_batch(coros):
            return await asyncio.gather(*coros)

        future = asyncio.run_coroutine_threadsafe(_upload_batch(upload_coros), loop)
        future.result()  # blocks the thread until all handlers complete

        consumer.commit()

async def main():
    loop = asyncio.get_running_loop()
    consumer_state = {}
    await asyncio.gather(
        asyncio.to_thread(_run_kafka_consumer, loop, consumer_state),
        _healthz(consumer_state),
        _readyz()
    )
```

**Key points:**

- The consumer runs in a dedicated thread (`asyncio.to_thread`).
- The event loop reference is passed to the thread.
- `run_coroutine_threadsafe(coro, loop)` schedules the coroutine on the main loop, returning a `concurrent.futures.Future`.
- Calling `.result()` blocks the thread until the coroutine completes (safe since the thread is dedicated to the consumer).
- **Do NOT call `asyncio.run(coro)` inside the thread** — it spawns a second event loop, causing "loop already running" errors.

## The sync-in-async trap (blocking cloud clients)

**Problem:** Sync clients (google-cloud-bigquery, google-cloud-storage, boto3) block the event loop when called from async code.

**Anti-pattern:**

```python
from google.cloud import bigquery

class BigQueryUtils:
    def __init__(self, project_id: str):
        self.client = bigquery.Client(project=project_id)  # SYNC

    def query_data(self, query: str):
        query_job = self.client.query(query)  # BLOCKS
        results = query_job.result()  # BLOCKS
        return [dict(row) for row in results]

# Called from async Temporal activity:
async def my_activity():
    bq = BigQueryUtils("my-project")
    return bq.query_data("SELECT * FROM table")  # BLOCKS EVENT LOOP
```

**Why this is bad:**

- The `bigquery.Client` makes synchronous HTTP requests and blocks the event loop.
- All other async tasks (handlers, health checks, workers) are frozen until the query completes.
- Throughput and latency degrade significantly under load.

**Fix 1: Offload to thread**

```python
import asyncio
from google.cloud import bigquery

async def my_activity():
    client = bigquery.Client(project="my-project")

    def _query():
        query_job = client.query("SELECT * FROM table")
        results = query_job.result()
        return [dict(row) for row in results]

    return await asyncio.to_thread(_query)
```

**Fix 2: Use an async client (if available)**

```python
# For Google Cloud Storage:
from gcloud.aio.storage import Storage

async def my_activity():
    async with Storage() as client:
        blob = await client.download("my-bucket", "path/to/file")
        return blob

# For AWS (not observed in repos, but standard practice):
import aioboto3

async def my_activity():
    session = aioboto3.Session()
    async with session.client("s3") as s3:
        obj = await s3.get_object(Bucket="my-bucket", Key="key")
        return await obj["Body"].read()
```

**Fix 3: Use `loop.run_in_executor`** (older pattern, equivalent to `to_thread`)

```python
async def my_activity():
    loop = asyncio.get_running_loop()
    client = bigquery.Client(project="my-project")

    def _query():
        job = client.query("SELECT * FROM table")
        return [dict(row) for row in job.result()]

    return await loop.run_in_executor(None, _query)
```

## Async client availability cheat sheet

| Service | Sync client | Async client | Notes |
|---------|-------------|--------------|-------|
| Google BigQuery | `google-cloud-bigquery` | None (wrap in `to_thread`) | No official async client; always wrap |
| Google Cloud Storage | `google-cloud-storage` | `gcloud-aio-storage` | Prefer async client |
| AWS S3 | `boto3` | `aioboto3` | Prefer async client |
| PostgreSQL | `psycopg2` | `asyncpg` | Always use asyncpg |
| Kafka | `kafka-python` | `aiokafka` | Use aiokafka unless GSSAPI/Kerberos required (not supported in aiokafka 0.7.x) |
| HTTP | `requests` | `aiohttp` | Always use aiohttp |

## When to use each approach

- **Async client exists and is mature:** Use it (asyncpg, aiokafka, aiohttp, gcloud-aio-storage).
- **Async client missing features you need:** Use the sync client wrapped in `asyncio.to_thread(...)`. Example: kafka-python supports SASL_SSL+GSSAPI Kerberos; aiokafka (as of 0.7.x) does not.
- **No async client exists:** Wrap in `asyncio.to_thread(...)`. Example: google-cloud-bigquery has no official async client.
- **Mixed sync/async library (e.g., kafka-python dispatching async handlers):** Use the bridge pattern (`to_thread` + `run_coroutine_threadsafe`).
- **Tiny blocking operation (milliseconds):** Usually safe to call directly, but measure. If in doubt, wrap it.

## Debugging tips

- **Symptom:** High p95/p99 latency, low throughput, tasks queuing up.
- **Check:** Add event loop monitoring (uvloop has diagnostics; asyncio has `loop.slow_callback_duration`).
- **Trace:** Use `asyncio.create_task(..., name="task_name")` and log task transitions.
- **Profile:** Use `py-spy` or `austin` to catch sync blocking calls in async code paths.
