---
name: temporal-config-driven
description: Encodes Temporal workflow orchestration patterns derived from production Python/FastAPI services—config-driven worker maps, workflow/activity definitions, retry policies, idempotency via activity_id, cron-based schedules, and DAG-based config-as-data orchestration. Use when implementing or debugging Temporal workflows, workers, activities, retries, schedules, or config-driven orchestration engines. Use when setting up worker bootstrap with graceful shutdown, or when building DAG-based config-as-data orchestration systems.
---

# temporal-config-driven

Temporal workflow orchestration using config-driven worker maps and DAG-based execution.

## When to use

- Implementing Temporal workers with mode-based configuration (WORKER_MODE_CONFIG_MAP)
- Defining workflows with @workflow.defn and activities with @activity.defn
- Setting up retry policies and timeouts for activities
- Ensuring idempotent workflow/activity execution via activity_id
- Building or debugging DAG-based config-as-data orchestration interpreters
- Configuring Temporal client connections (host, namespace, TLS)
- Structuring services/temporal/ directory and worker bootstrap logic
- Setting up cron-based workflow schedules (recurring workflows)
- Implementing graceful worker shutdown (SIGTERM/SIGINT handling)
- Dynamic worker generation for matrix-based task queues (e.g., file_type × business_unit)

## Core conventions

**Worker configuration map**: Assemble workers via a `WORKER_MODE_CONFIG_MAP` dict that maps mode keys to `{ task_queue: str, workflows: [WorkflowClass], activities: [activity_fn] }`. Commonly merge sub-maps for distinct operational domains (audit, vendor operations, file processing, etc.).

```python
WORKER_MODE_CONFIG_MAP = {
    **AUDIT_WORKFLOW_CONFIG_MAP,
    **VENDOR_WORKFLOW_CONFIG_MAP,
    **FILE_OPERATIONS_WORKFLOW_CONFIG_MAP,
}
```

**Dynamic worker generation**: For matrix-based workers (e.g., file_type × business_unit), build workers dynamically with computed task_queue strings like `f"data-ingestion-{file_type}-{business_unit}-task-queue"`.

**Worker bootstrap** (services/temporal/run_workers.py): `worker_main(worker_mode)` initializes the client, retrieves config from `WORKER_MODE_CONFIG_MAP[worker_mode]`, creates a Worker with the task_queue/workflows/activities, and runs it under `asyncio.gather` with health checks. Graceful shutdown via `loop.add_signal_handler(signal.SIGTERM/SIGINT, on_signal_received)`.

**Client initialization**: `await Client.connect(loaded_config.TEMPORAL_HOST, namespace=loaded_config.TEMPORAL_NAMESPACE)`. TLS is absent (in-cluster plaintext); Temporal Cloud would add `tls=`.

**Workflow definitions**: Decorate with `@workflow.defn`, implement `@workflow.run async def run(self, data: dict)`. Activities invoked via `workflow.execute_activity(fn, args, start_to_close_timeout=timedelta(...), retry_policy=RetryPolicy(...))`.

**Activity definitions**: Decorate with `@activity.defn async def`. Accept dict payloads (JSON-serializable) or pydantic dataclasses.

**Idempotency helper**: `execute_activity_with_activity_id(activity_method, workflow_id, data, retry_policy, start_to_close_timeout)` injects `activity_id = activity_method.__name__.split(".")[-1]` to make retries safe.

**Retry policies**: `RetryPolicy(initial_interval=timedelta(seconds=1), maximum_interval=timedelta(seconds=60), maximum_attempts=3, backoff_coefficient=2.0)`. Timeouts: `start_to_close_timeout`, `schedule_to_close_timeout`, `schedule_to_start_timeout`.

**Terminal failures**: Raise `ApplicationError(non_retryable=True)` and invoke a `raise_alert` activity for monitoring.

**Workflow ID composition**: `f"{workflow['name']}-{uuid}-{int(datetime.now().timestamp())}"` ensures uniqueness and idempotency.

**DAG-based config interpreter**: Load a workflow definition (nodes + edges JSON) from DB via an activity. `_execute_dag` builds an adjacency list, finds entry nodes (no incoming edges), and iteratively runs all dependency-satisfied nodes in parallel (`asyncio.gather`). Each node runs INLINE (`execute_inline` activity, ~300s timeout) or DEFERRED (`enqueue_and_wait` activity, ~3600s timeout). Node outputs wire to downstream inputs via `input_mapping` referencing prior node names (`$node_name`).

**Node type dispatch**: `NODE_TYPE_MAP = { "http.request": http_request.execute, "db.upsert": db_upsert.execute, "expr.switch": expr_switch.execute, "transform.map": transform_map.execute, "business_logic": business_logic.execute }`. `execute_inline(node, input_envelope)` dispatches by `node["type"]`.

**Cron-based schedules**: Use `client.create_schedule` with `Schedule(action=ScheduleActionStartWorkflow(...), spec=ScheduleSpec(cron_expressions=[...]))` to trigger workflows on a recurring basis. Common for daily/hourly batch jobs. Schedule IDs must be unique across the namespace.

## Skeleton / example

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

# services/temporal/run_workers.py
async def worker_main(worker_mode):
    await on_startup()
    client = await initialize_client()
    worker_obj = Worker(
        client=client,
        task_queue=WORKER_MODE_CONFIG_MAP[worker_mode]["task_queue"],
        workflows=WORKER_MODE_CONFIG_MAP[worker_mode]["workflows"],
        activities=WORKER_MODE_CONFIG_MAP[worker_mode]["activities"],
    )
    worker_task = asyncio.create_task(worker_obj.run())
    
    loop = asyncio.get_running_loop()
    loop.add_signal_handler(signal.SIGTERM, on_signal_received, None)
    await asyncio.gather(worker_task)

# Workflow definition
from temporalio import workflow
from temporalio.common import RetryPolicy

@workflow.defn
class ProcessGCSFilesWorkflow:
    @workflow.run
    async def run(self, data: dict) -> dict:
        retry_policy = RetryPolicy(
            maximum_attempts=3,
            maximum_interval=timedelta(minutes=30)
        )
        workflow_id = data.get("workflow_id")
        
        result = await execute_activity_with_activity_id(
            activity_method=activity.process_files,
            workflow_id=workflow_id,
            data=data,
            retry_policy=retry_policy,
            start_to_close_timeout=timedelta(minutes=30),
        )
        return result

# Activity definition
@activity.defn
async def process_files(data: dict) -> dict:
    # Activity implementation
    return {"status": "completed"}

# DAG interpreter snippet
async def _execute_dag(self, workflow_def, workflow_input):
    nodes = workflow_def.get("nodes", [])
    edges = workflow_def.get("edges", [])
    graph = self._build_graph(nodes, edges)
    
    executed = set()
    while len(executed) < len(nodes):
        ready_nodes = [
            n for n in nodes 
            if n["name"] not in executed
            and self._are_dependencies_satisfied(n["name"], graph, executed)
        ]
        
        tasks = [self._execute_node(node, graph) for node in ready_nodes]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for i, result in enumerate(results):
            node = ready_nodes[i]
            if isinstance(result, Exception):
                self.failed_nodes[node["name"]] = str(result)
            else:
                self.completed_nodes[node["name"]] = result
                executed.add(node["name"])
    
    return {"completed_nodes": self.completed_nodes, "failed_nodes": self.failed_nodes}

# Temporal Schedule (cron-based workflow)
from temporalio.client import Client, Schedule, ScheduleActionStartWorkflow, ScheduleSpec

async def setup_daily_schedule():
    client = await Client.connect(
        "temporal.svc.cluster.local:7233",
        namespace="production"
    )
    
    await client.create_schedule(
        id="daily-report-schedule",
        schedule=Schedule(
            action=ScheduleActionStartWorkflow(
                GenerateReportWorkflow,
                args={"report_type": "daily"},
                id="daily-report",
                task_queue="report-generation-queue",
            ),
            spec=ScheduleSpec(
                cron_expressions=["0 9 * * *"],  # 9 AM daily
            ),
        ),
        note="Daily report generation",
    )
```

## Anti-patterns to avoid

- Hard-coding task queues or workflows in worker bootstrap (breaks multi-mode deployments)
- Skipping `activity_id` injection in retryable activities (breaks idempotency)
- Omitting `RetryPolicy` or using unbounded `maximum_attempts` (cascading failures)
- Circular dependencies in DAG edges (halts execution)
- Using blocking I/O in activities without proper timeouts
- Ignoring `non_retryable=True` for terminal errors (retry storm)
- TLS/auth config in plaintext in-cluster deployments (security debt if moved to Cloud)
- Creating duplicate schedule IDs across environments (namespace collision; use env-prefixed IDs like `prod-daily-report`)
- Not handling schedule creation errors on re-deploy (may fail if schedule already exists)
- Forgetting graceful shutdown handlers (SIGTERM/SIGINT) in worker processes (unclean pod termination)

## References

- [repo-evidence.md](references/repo-evidence.md) — Real file paths and code snippets from source repos
- [worker-workflow-activity-patterns.md](references/worker-workflow-activity-patterns.md) — Worker config maps, bootstrap, workflow/activity definitions
- [config-and-retry-idempotency.md](references/config-and-retry-idempotency.md) — Retry policies, timeouts, idempotency helpers
- [dag-dsl-interpreter.md](references/dag-dsl-interpreter.md) — DAG-based orchestration, node type dispatch
- [schedules-and-cron.md](references/schedules-and-cron.md) — Cron-based workflow scheduling, lifecycle, anti-patterns
