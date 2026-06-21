# Worker, Workflow, and Activity Patterns

## Worker configuration map structure

The `WORKER_MODE_CONFIG_MAP` is the core data structure that drives worker assembly. It maps a mode key (string) to a config dict containing:

- `task_queue` (str): The Temporal task queue name
- `workflows` (list): Workflow classes decorated with `@workflow.defn`
- `activities` (list): Activity functions/methods decorated with `@activity.defn`
- `name` (optional str): Human-readable workflow name for ID composition

### Static assembly

Merge sub-maps by domain:

```python
# services/temporal/config.py
from app.workflows import (
    AUDIT_WORKFLOW_CONFIG_MAP,
    VENDOR_WORKFLOW_CONFIG_MAP,
    FILE_OPERATIONS_WORKFLOW_CONFIG_MAP,
)

WORKER_MODE_CONFIG_MAP = {
    **AUDIT_WORKFLOW_CONFIG_MAP,
    **VENDOR_WORKFLOW_CONFIG_MAP,
    **FILE_OPERATIONS_WORKFLOW_CONFIG_MAP,
}
```

Each sub-map looks like:

```python
AUDIT_WORKFLOW_CONFIG_MAP = {
    "esign_download": {
        "task_queue": "esign-download-queue",
        "name": "EsignDownload",
        "workflows": [EsignDownloadWorkflow],
        "activities": [
            esign_activities.document_status_check,
            esign_activities.download_signed_document,
            esign_activities.get_audit_trail,
        ],
    },
}
```

### Dynamic generation

For matrix-based workers (file_type × business_unit), compute task_queue strings dynamically:

```python
# services/temporal/initialize_worker_tasks.py
async def get_worker_tasks(client):
    activities = DataIngestionActivities()
    worker_tasks = []
    
    for file_type, business_units in FILE_TYPE_BUSINESS_UNIT_MAPPING.items():
        for business_unit in business_units:
            worker_obj = Worker(
                client=client,
                task_queue=f"data-ingestion-{file_type}-{business_unit}-task-queue",
                workflows=[DataIngestionWorkflow],
                activities=[
                    activities.get_start_end_ts,
                    activities.generate_data_query,
                    activities.execute_query_to_temp_table,
                    activities.export_csv_from_temp_table,
                    activities.upload_file_to_storage,
                    activities.update_file_name_and_watermark,
                    activities.raise_alert,
                ],
            )
            worker_task = asyncio.create_task(worker_obj.run())
            worker_tasks.append((worker_obj, worker_task))
    
    return worker_tasks
```

## Worker bootstrap and lifecycle

### services/temporal/run_workers.py pattern

```python
import asyncio
import signal
from temporalio.worker import Worker
from utils.temporal_utils import initialize_client
from services.temporal.config import WORKER_MODE_CONFIG_MAP

async def worker_main(worker_mode):
    await on_startup()
    
    health_task = asyncio.create_task(_healthz())
    ready_task = asyncio.create_task(_readyz())
    
    client = await initialize_client()
    worker_obj = Worker(
        client=client,
        task_queue=WORKER_MODE_CONFIG_MAP[worker_mode]["task_queue"],
        workflows=WORKER_MODE_CONFIG_MAP[worker_mode]["workflows"],
        activities=WORKER_MODE_CONFIG_MAP[worker_mode]["activities"],
    )
    worker_task = asyncio.create_task(worker_obj.run())
    
    worker_tasks = [health_task, ready_task, worker_task]
    
    async def async_shutdown():
        await worker_obj.shutdown()
        health_task.cancel()
        ready_task.cancel()
        worker_task.cancel()
        try:
            await asyncio.gather(health_task, ready_task, worker_task)
        except asyncio.CancelledError:
            logger.error("Tasks cancelled")
    
    def on_signal_received(*args, **kwargs):
        asyncio.create_task(async_shutdown())
    
    loop = asyncio.get_running_loop()
    loop.add_signal_handler(signal.SIGTERM, on_signal_received, None)
    loop.add_signal_handler(signal.SIGINT, on_signal_received, None)
    
    try:
        await asyncio.gather(*worker_tasks, return_exceptions=True)
    except asyncio.CancelledError:
        logger.error("ALL TASKS CANCELLED")
    
    await on_shutdown()
```

**Key behaviors**:
- **Health and readiness endpoints** run as parallel tasks (`_healthz()`, `_readyz()`) for Kubernetes liveness/readiness probes
- Worker runs under `asyncio.create_task` and joins via `asyncio.gather`
- **Graceful shutdown**: `add_signal_handler` for SIGTERM/SIGINT triggers `worker_obj.shutdown()` and cancels all tasks
- `return_exceptions=True` prevents one task failure from killing the group
- `await on_startup()` and `await on_shutdown()` hooks for DB connection pools, metrics clients, etc.

### Health and readiness endpoints

Health (`/healthz`) and readiness (`/readyz`) endpoints are HTTP servers running on separate asyncio tasks for Kubernetes probes:

```python
async def _healthz():
    """Liveness probe: always returns 200 OK if the process is running."""
    # Simple HTTP server on port 8080
    pass

async def _readyz():
    """Readiness probe: returns 200 OK only when worker is connected to Temporal."""
    # Check Temporal client health
    pass
```

These run in parallel with the worker task and are cancelled on shutdown.

## Workflow definitions

Decorate with `@workflow.defn`, implement `@workflow.run async def run(self, data: dict)`:

```python
from temporalio import workflow
from temporalio.common import RetryPolicy
from datetime import timedelta

@workflow.defn
class ProcessGCSFilesWorkflow:
    @workflow.run
    async def run(self, data: dict) -> dict:
        retry_policy = RetryPolicy(
            maximum_attempts=3,
            maximum_interval=timedelta(minutes=30)
        )
        workflow_id = data.get("workflow_id")
        
        result_1 = await execute_activity_with_activity_id(
            activity_method=activities.step_one,
            workflow_id=workflow_id,
            data=data,
            retry_policy=retry_policy,
            start_to_close_timeout=timedelta(minutes=30),
        )
        
        data["step_one_output"] = result_1
        
        result_2 = await execute_activity_with_activity_id(
            activity_method=activities.step_two,
            workflow_id=workflow_id,
            data=data,
            retry_policy=retry_policy,
            start_to_close_timeout=timedelta(minutes=10),
        )
        
        return {"status": "completed", "result": result_2}
```

**Pattern notes**:
- Chain activities by passing outputs as inputs to subsequent activities
- Extract `workflow_id` from input payload for correlation
- Use the same `retry_policy` object across related activities (adjust timeouts per activity)

## Activity definitions

Decorate with `@activity.defn`, accept dict payloads (or pydantic models):

```python
from temporalio import activity

@activity.defn
async def process_files(data: dict) -> dict:
    activity_id = data.get("activity_id")
    workflow_id = data.get("workflow_id")
    
    logger.info("Processing files", activity_id=activity_id, workflow_id=workflow_id)
    
    # Activity logic
    result = await do_processing(data)
    
    return {"status": "completed", "data": result}
```

**Pattern notes**:
- Extract `activity_id` and `workflow_id` from payload for logging and correlation
- Return dict payloads (JSON-serializable)
- Log entry/exit with activity_id for trace correlation

## Idempotency helper (execute_activity_with_activity_id)

Production pattern for idempotent activity invocation:

```python
from temporalio import workflow

async def execute_activity_with_activity_id(
    activity_method, workflow_id, data, retry_policy, start_to_close_timeout
):
    activity_id = activity_method.__name__.split(".")[-1]
    data["activity_id"] = activity_id
    if "workflow_id" not in data and workflow_id is not None:
        data["workflow_id"] = workflow_id
    return await workflow.execute_activity_method(
        activity_method,
        data,
        start_to_close_timeout=start_to_close_timeout,
        retry_policy=retry_policy,
        activity_id=activity_id,
    )
```

**Why**: Temporal uses `activity_id` to deduplicate retries. Injecting `activity_method.__name__` ensures the same activity invocation within a workflow run always has the same ID, making retries idempotent.

**Usage**: Replace raw `workflow.execute_activity` calls with this helper for all retryable activities.

## Workflow triggering

Production pattern for triggering workflows:

```python
from datetime import datetime

async def trigger_workflow_config(workflow_config_name: str, uuid, workflow_input: dict):
    workflow = WORKER_MODE_CONFIG_MAP[workflow_config_name]
    workflow_id = f"{workflow['name']}-{uuid}-{int(datetime.now().timestamp())}"
    workflow_class = workflow["workflows"][0]
    workflow_input["workflow_id"] = workflow_id
    
    client = await initialize_client()
    handle = await client.start_workflow(
        workflow_class.run,
        workflow_input,
        id=workflow_id,
        task_queue=workflow["task_queue"],
    )
    
    return handle
```

**Pattern notes**:
- Workflow ID composition: `{name}-{uuid}-{timestamp}` for uniqueness and traceability
- Inject `workflow_id` into the input payload so activities can access it
- Return the workflow handle for status queries or result awaits

## Client initialization

Production pattern for Temporal client initialization:

```python
from temporalio.client import Client
from config.config import config

async def initialize_client() -> Client:
    worker_client = await Client.connect(
        config.TEMPORAL_HOST,
        namespace=config.TEMPORAL_NAMESPACE
    )
    logger.info("Workflow client initialized!")
    return worker_client
```

**Pattern notes**:
- TLS is absent (in-cluster plaintext); Temporal Cloud would add `tls=TLSConfig(...)`
- Namespace isolates workflows across environments (dev, staging, prod)
- Config keys: `TEMPORAL_HOST`, `TEMPORAL_NAMESPACE` (from docker_config / env)
