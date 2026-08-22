# Example Patterns

Representative code patterns from production Temporal services.

## Example Service 1: DAG-based orchestration service

**Patterns**: Worker config map assembly, DAG interpreter architecture, NODE_TYPE_MAP dispatch.

### services/temporal/config.py

```python
from app.workflows import (
    AUDIT_WORKFLOW_CONFIG_MAP, VENDOR_WORKFLOW_CONFIG_MAP,
    FILE_OPERATIONS_WORKFLOW_CONFIG_MAP
)

WORKER_MODE_CONFIG_MAP = {
    **AUDIT_WORKFLOW_CONFIG_MAP,
    **VENDOR_WORKFLOW_CONFIG_MAP,
    **FILE_OPERATIONS_WORKFLOW_CONFIG_MAP,
}

async def trigger_workflow_config(workflow_config_name: str, uuid, workflow_input: dict):
    workflow = WORKER_MODE_CONFIG_MAP[workflow_config_name]
    workflow_id = f"{workflow['name']}-{uuid}-{int(datetime.now().timestamp())}"
    workflow_class = workflow["workflows"][0]
    # ...
```

### services/temporal/run_workers.py

```python
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
    loop.add_signal_handler(signal.SIGINT, on_signal_received, None)
    await asyncio.gather(*worker_tasks, return_exceptions=True)
```

### apps/orchestrator/interpreter.py

```python
@workflow.defn
class ConfigDrivenDAGWorkflow:
    def __init__(self):
        self.completed_nodes: Dict[str, Any] = {}
        self.failed_nodes: Dict[str, str] = {}
        self.current_inputs: Dict[str, Any] = {}
    
    @workflow.run
    async def run(self, workflow_input: Dict[str, Any]) -> Dict[str, Any]:
        workflow_def = await workflow.execute_activity(
            load_workflow_definition,
            workflow_def_id,
            start_to_close_timeout=workflow.timedelta(seconds=30),
        )
        result = await self._execute_dag(workflow_def, workflow_input)
        return result
    
    async def _execute_dag(self, workflow_def, workflow_input):
        nodes = workflow_def.get("nodes", [])
        edges = workflow_def.get("edges", [])
        graph = self._build_graph(nodes, edges)
        entry_nodes = self._find_entry_nodes(nodes, edges)
        
        executed = set()
        while len(executed) < len(nodes):
            ready_nodes = []
            for node in nodes:
                if node["name"] in executed:
                    continue
                if self._are_dependencies_satisfied(node["name"], graph, executed):
                    ready_nodes.append(node)
            
            tasks = []
            for node in ready_nodes:
                task = self._execute_node(node, graph)
                tasks.append(task)
            
            results = await asyncio.gather(*tasks, return_exceptions=True)
            # Process results...
```

### apps/orchestrator/activities/inline.py

```python
NODE_TYPE_MAP = {
    "http.request": http_request.execute,
    "db.upsert": db_upsert.execute,
    "expr.switch": expr_switch.execute,
    "transform.map": transform_map.execute,
    "business_logic": business_logic.execute,
}

@activity.defn
async def execute_inline(node: Dict[str, Any], input_envelope: Dict[str, Any]) -> Dict[str, Any]:
    node_name = node["name"]
    node_type = node["type"]
    config = node.get("config", {})
    
    if node_type not in NODE_TYPE_MAP:
        raise ValueError(f"Unknown node type: {node_type}")
    
    execute_func = NODE_TYPE_MAP[node_type]
    context = NodeContext(
        trace_id=input_envelope.get("trace_id"),
        idempotency_key=input_envelope.get("idempotency_key"),
    )
    result = await execute_func(context, config, input_envelope)
    return {"status": "completed", "output": result}
```

---

## Example Service 2: Dynamic worker generation service

**Patterns**: Dynamic worker generation for matrix-based workers.

### services/temporal/initialize_worker_tasks.py

```python
async def get_worker_tasks(client):
    data_ingestion_activities = DataIngestionActivities()
    worker_tasks = []
    
    for file_type, business_units in FILE_TYPE_BUSINESS_UNIT_MAPPING.items():
        for business_unit in business_units:
            worker_obj = Worker(
                client=client,
                task_queue=f"data-ingestion-{file_type}-{business_unit}-task-queue",
                workflows=[DataIngestionWorkflow],
                activities=[
                    data_ingestion_activities.get_start_end_ts,
                    data_ingestion_activities.generate_data_query,
                    # ...
                ],
            )
            worker_task = asyncio.create_task(worker_obj.run())
            worker_tasks.append((worker_obj, worker_task))
    
    return worker_tasks
```

---

## Example Service 3: File processing service

**Patterns**: `execute_activity_with_activity_id` helper, workflow/activity structure, retry policies.

### utils/temporal_utils.py

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

### workflows/process_files/workflow.py

```python
from temporalio import workflow
from temporalio.common import RetryPolicy

@workflow.defn
class ProcessFilesWorkflow:
    @workflow.run
    async def run(self, data: dict) -> dict:
        retry_policy = RetryPolicy(
            maximum_attempts=3,
            maximum_interval=timedelta(minutes=30)
        )
        workflow_id = data.get("workflow_id")
        
        distinct_vendor_codes = await execute_activity_with_activity_id(
            activity_method=process_files_activity.find_vendor_codes,
            workflow_id=workflow_id,
            data=data,
            retry_policy=retry_policy,
            start_to_close_timeout=timedelta(minutes=30),
        )
        # Chained activities...
```

### utils/temporal_utils.py

```python
from temporalio.client import Client

async def initialize_client() -> Client:
    worker_client = await Client.connect(
        config.TEMPORAL_HOST,
        namespace=config.TEMPORAL_NAMESPACE
    )
    logger.info("Workflow client initialized!")
    return worker_client
```

---

## Example Service 4: Workflow orchestration service

**Patterns**: Worker config map pattern, workflow trigger helpers.

### temporal/config.py

```python
from temporal.workflow.config import WORKFLOW_CONFIG_MAP

WORKER_MODE_CONFIG_MAP = {**WORKFLOW_CONFIG_MAP}

async def trigger_workflow_config(workflow_config_name: str, task_queue: str, uuid: str, workflow_input: dict):
    workflow = WORKER_MODE_CONFIG_MAP[workflow_config_name]
    workflow_id = f"{workflow['name']}-{uuid}-{int(datetime.now().timestamp())}"
    workflow_class = workflow["workflows"][0]
    workflow_input["workflow_id"] = workflow_id
    client = await initialize_client()
    handle = await client.start_workflow(
        workflow_class.run,
        workflow_input,
        id=workflow_id,
        task_queue=task_queue,
    )
    return handle
```

---

## Example Service 5: Scheduled workflows service

**Patterns**: services/temporal/ directory structure, scheduler helper, cron-based schedules.

### services/temporal/utils.py

```python
async def scheduler(
    workflow_to_schedule,
    queue: str,
    cron_id: str,
    cron_expressions: list[str],
    args: dict | None = None,
    note: str = "",
):
    client = await Client.connect(
        config.TEMPORAL_HOST, 
        namespace=config.TEMPORAL_NAMESPACE
    )

    await client.create_schedule(
        id=cron_id,
        schedule=Schedule(
            action=ScheduleActionStartWorkflow(
                workflow_to_schedule,
                args=args or {},
                id=cron_id,
                task_queue=queue,
            ),
            spec=ScheduleSpec(
                cron_expressions=cron_expressions,
            ),
        ),
        note=note,
    )
```

### services/temporal/start_schedules.py

```python
async def start_schedules():
    try:
        scheduler(
            workflow_to_schedule=TempUploadWorkflow,
            queue="temp-upload-queue",
            cron_id="temp-upload-daily",
            cron_expressions=["0 9 * * *"],
            args={"mode": "daily"},
            note="Daily temp file upload",
        )
        
        scheduler(
            workflow_to_schedule=LogisticsDashboardSyncWorkflow,
            queue="logistics-sync-queue",
            cron_id="logistics-sync-hourly",
            cron_expressions=["0 * * * *"],
            args={},
            note="Hourly logistics dashboard sync",
        )
        
    except Exception as e:
        logger.error(f"Error starting schedules: {e}")
        raise
```

### services/temporal/config.py
### services/temporal/run_workers.py

*(Same patterns as other services — worker maps, client initialization, graceful shutdown)*
