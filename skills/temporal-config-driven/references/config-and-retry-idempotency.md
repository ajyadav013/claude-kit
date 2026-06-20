# Config, Retry Policies, and Idempotency

## Retry policy structure

Temporal `RetryPolicy` controls how activities retry on transient failures.

### Standard retry policy (production pattern)

```python
from temporalio.common import RetryPolicy
from datetime import timedelta

retry_policy = RetryPolicy(
    initial_interval=timedelta(seconds=1),
    maximum_interval=timedelta(seconds=60),
    maximum_attempts=3,
    backoff_coefficient=2.0,
)
```

> Confirmed against: https://docs.temporal.io/develop/python/failure-detection#retry-policy

**Field meanings**:
- `initial_interval`: First retry delay (1s is common)
- `maximum_interval`: Cap on exponential backoff (60s prevents unbounded waits)
- `maximum_attempts`: Total tries (including initial attempt; 3 = initial + 2 retries)
- `backoff_coefficient`: Multiplier for exponential backoff (2.0 doubles delay each retry: 1s → 2s → 4s → ...)

### Relaxed retry policy (longer intervals)

Production pattern for long-running operations:

```python
retry_policy = RetryPolicy(
    maximum_attempts=3,
    maximum_interval=timedelta(minutes=30)
)
```

Omitting `initial_interval` and `backoff_coefficient` uses Temporal defaults (1s, 2.0). `maximum_interval=30m` allows long retries for slow external services.

### When to use which

- **Quick transient errors** (network blips, rate limits): `initial_interval=1s`, `maximum_interval=60s`, `maximum_attempts=3`
- **Slow external APIs** (database queries, batch operations): `maximum_interval=30m`, `maximum_attempts=5`
- **Non-retryable errors**: Raise `ApplicationError(non_retryable=True)` to skip retries and fail immediately

## Activity timeouts

Temporal has multiple timeout types; the repos use:

### start_to_close_timeout

Time allowed from activity start to completion (including retries). The most common timeout.

```python
await workflow.execute_activity(
    activity_fn,
    args,
    start_to_close_timeout=timedelta(minutes=30),
    retry_policy=retry_policy,
)
```

**Usage**:
- **Inline DAG nodes**: ~300s (5 minutes) for lightweight transforms/http calls
- **Deferred DAG nodes**: ~3600s (1 hour) for long-running batch jobs
- **File processing**: 30-3000 minutes depending on file size

### schedule_to_close_timeout

Total time from activity scheduled to completion (includes time waiting in the queue). Rarely used in the repos (Temporal defaults apply).

### schedule_to_start_timeout

Time allowed for an activity to sit in the queue before a worker picks it up. Not explicitly set in the repos (default: infinite).

> Confirmed against: https://docs.temporal.io/develop/python/failure-detection#activity-timeouts (timeout types and semantics)

## Idempotency via activity_id

Temporal guarantees **at-most-once execution** per unique `(workflow_id, activity_id)` pair. If an activity completes but the workflow crashes before recording the result, Temporal retries by **replaying the recorded result** instead of re-executing.

### execute_activity vs execute_activity_method

Temporal Python SDK provides two ways to invoke activities from workflows:

- **`workflow.execute_activity(fn, args, ...)`**: For standalone activity functions
- **`workflow.execute_activity_method(obj.method, args, ...)`**: For activity methods on a class instance

The `execute_activity_with_activity_id` helper uses `execute_activity_method` because many services organize activities as methods on activity classes (e.g., `DataIngestionActivities().get_start_end_ts`).

### Idempotency helper (execute_activity_with_activity_id)

Production pattern for idempotent activity invocation:

```python
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

**How it works**:
1. Derive `activity_id` from the activity method name (e.g., `process_files.find_vendor_codes` → `"find_vendor_codes"`)
2. Inject `activity_id` into the data payload for logging/correlation
3. Pass `activity_id` to `workflow.execute_activity_method` so Temporal can deduplicate retries

**Why derive from `__name__`**: The activity method name is stable within a workflow definition version. Using it as the ID ensures the same logical step always has the same ID, enabling safe retries.

**Anti-pattern**: Omitting `activity_id` means Temporal generates a unique ID per invocation, breaking idempotency (retries re-execute instead of replaying).

## Workflow ID composition

Production pattern for unique workflow IDs:

```python
from datetime import datetime

workflow_id = f"{workflow['name']}-{uuid}-{int(datetime.now().timestamp())}"
```

**Parts**:
- `workflow['name']`: Human-readable workflow type (e.g., `"EsignDownload"`)
- `uuid`: Request/entity correlation ID (e.g., audit_id, file_id)
- `timestamp`: Uniqueness guarantee (seconds since epoch)

**Why**: Ensures globally unique workflow IDs (Temporal rejects duplicate IDs by default) and enables trace correlation (uuid ties the workflow to a domain entity, timestamp orders events).

**Usage**: Inject into the workflow input payload as `workflow_input["workflow_id"]` so activities can log it.

## Config keys (Temporal client)

Production pattern for Temporal client configuration:

```python
# config/config.py
TEMPORAL_HOST: str = args.TEMPORAL_HOST  # e.g., "temporal.svc.cluster.local:7233"
TEMPORAL_NAMESPACE: str = args.TEMPORAL_NAMESPACE  # e.g., "production"

# utils/temporal_utils.py
async def initialize_client():
    client = await Client.connect(
        config.TEMPORAL_HOST,
        namespace=config.TEMPORAL_NAMESPACE
    )
    return client
```

**TLS note**: In-cluster deployments often use **plaintext** connections (in-cluster gRPC). Temporal Cloud requires `tls=TLSConfig(...)`:

```python
# Internet-confirmed pattern for Temporal Cloud
from temporalio.client import Client, TLSConfig

client = await Client.connect(
    "my-namespace.tmprl.cloud:7233",
    namespace="my-namespace",
    tls=TLSConfig(
        client_cert=<REDACTED>,
        client_private_key=<REDACTED>,
    ),
)
```

## Terminal failures (non-retryable errors)

Raise `ApplicationError(non_retryable=True)` to stop retries and fail the workflow immediately.

```python
from temporalio.exceptions import ApplicationError

@activity.defn
async def validate_input(data: dict):
    if "required_field" not in data:
        # Retrying won't fix a schema error
        raise ApplicationError("Missing required_field", non_retryable=True)
    # ...
```

**Pattern**: After raising a non-retryable error, invoke a `raise_alert` activity to notify monitoring/alerting systems.

## Retry storm prevention

**Anti-pattern**: Unbounded retries (`maximum_attempts` omitted or set to a huge number) on a broken external service can create a retry storm.

**Fix**: Cap `maximum_attempts` at 3-5 and set a reasonable `maximum_interval` (60s for quick retries, 30m for slow services). Combine with circuit-breaker logic in activities if the external service SLA is critical.

## Example: chaining activities with retry policies

Production pattern for chaining activities:

```python
@workflow.defn
class ProcessGCSFilesWorkflow:
    @workflow.run
    async def run(self, data: dict) -> dict:
        retry_policy = RetryPolicy(maximum_attempts=3, maximum_interval=timedelta(minutes=30))
        workflow_id = data.get("workflow_id")
        
        # Step 1: Find vendor codes (fast)
        vendor_codes = await execute_activity_with_activity_id(
            activity_method=activities.find_vendor_codes,
            workflow_id=workflow_id,
            data=data,
            retry_policy=retry_policy,
            start_to_close_timeout=timedelta(minutes=30),
        )
        
        data["vendor_codes"] = vendor_codes["distinct_vendor_codes"]
        
        # Step 2: Verify vendor codes (fast)
        vendor_mapping = await execute_activity_with_activity_id(
            activity_method=activities.verify_vendor_codes,
            workflow_id=workflow_id,
            data=data,
            retry_policy=retry_policy,
            start_to_close_timeout=timedelta(minutes=30),
        )
        
        # Step 3: Dump files to DB (slow, long timeout)
        dump_result = await execute_activity_with_activity_id(
            activity_method=activities.dump_files,
            workflow_id=workflow_id,
            data={"files": data["files"], "mapping": vendor_mapping},
            retry_policy=retry_policy,
            start_to_close_timeout=timedelta(minutes=3000),  # 50 hours for large files
        )
        
        return {"status": "completed"}
```

**Pattern notes**:
- Same `retry_policy` across all activities (simplifies definition)
- `start_to_close_timeout` varies by activity (30m for API calls, 3000m for batch I/O)
- Chain outputs by injecting into `data` for the next activity
