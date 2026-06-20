# DAG-based Config Interpreter (Config-as-Data Orchestration)

The **DAG-based config interpreter** is a distinctive config-as-DATA orchestration pattern that executes workflows defined as JSON (nodes + edges) rather than hard-coded Python. The workflow loads a workflow definition from the database and executes the DAG by running nodes in parallel when dependencies are satisfied.

## Architecture

Production pattern for DAG-based orchestration:

### Workflow definition shape (JSON)

```json
{
  "id": 123,
  "name": "sample_workflow",
  "version": 1,
  "nodes": [
    {
      "name": "start",
      "type": "http.request",
      "config": {
        "url": "https://api.example.com/start",
        "method": "POST"
      },
      "inline": true,
      "input_mapping": {}
    },
    {
      "name": "process",
      "type": "transform.map",
      "config": {
        "mapping": {
          "result": "$start.response"
        }
      },
      "inline": true,
      "input_mapping": {
        "data": "$start"
      }
    }
  ],
  "edges": [
    {"from": "start", "to": "process"}
  ]
}
```

**Node fields**:
- `name`: Unique node identifier (used in input_mapping references)
- `type`: Node type key for dispatch (e.g., `"http.request"`, `"db.upsert"`, `"transform.map"`, `"expr.switch"`, `"business_logic"`)
- `config`: Node-type-specific configuration (URL, SQL, mapping, etc.)
- `inline`: `true` = run in `execute_inline` activity (~300s timeout), `false` = run in `enqueue_and_wait` activity (~3600s timeout)
- `input_mapping`: Maps input keys to prior node outputs (e.g., `{"data": "$start"}` wires the output of node `"start"` to the `"data"` input of this node)

**Edge fields**:
- `from`: Source node name
- `to`: Target node name (dependency: target waits for source to complete)

## DAG workflow class

### Initialization

```python
@workflow.defn
class ConfigDrivenDAGWorkflow:
    def __init__(self):
        self.completed_nodes: Dict[str, Any] = {}
        self.failed_nodes: Dict[str, str] = {}
        self.current_inputs: Dict[str, Any] = {}
```

**State**:
- `completed_nodes`: Map of node name → output (result from `execute_inline`/`enqueue_and_wait`)
- `failed_nodes`: Map of node name → error message
- `current_inputs`: Workflow-level inputs (updated as nodes complete)

### Workflow run method

```python
@workflow.run
async def run(self, workflow_input: Dict[str, Any]) -> Dict[str, Any]:
    workflow_run_id = workflow_input.get("workflow_run_id")
    workflow_def_id = workflow_input.get("workflow_def_id")
    
    # Load workflow definition from DB
    workflow_def = await workflow.execute_activity(
        load_workflow_definition,
        workflow_def_id,
        start_to_close_timeout=workflow.timedelta(seconds=30),
    )
    
    # Execute the DAG
    result = await self._execute_dag(workflow_def, workflow_input)
    
    return result
```

**Flow**:
1. Extract `workflow_def_id` from input
2. Load workflow definition (nodes + edges JSON) via an activity
3. Execute the DAG (parallel execution engine)
4. Return final result (completed_nodes + failed_nodes)

## DAG execution engine (_execute_dag)

```python
async def _execute_dag(self, workflow_def, workflow_input):
    nodes = workflow_def.get("nodes", [])
    edges = workflow_def.get("edges", [])
    
    # Build adjacency list
    graph = self._build_graph(nodes, edges)
    
    # Find entry nodes (no incoming edges)
    entry_nodes = self._find_entry_nodes(nodes, edges)
    
    # Initialize inputs with workflow input
    self.current_inputs = workflow_input.copy()
    
    # Execute nodes in topological order
    executed = set()
    while len(executed) < len(nodes):
        # Find nodes with all dependencies satisfied
        ready_nodes = []
        for node in nodes:
            if node["name"] in executed:
                continue
            if self._are_dependencies_satisfied(node["name"], graph, executed):
                ready_nodes.append(node)
        
        if not ready_nodes:
            # Circular dependency or missing nodes
            remaining = [n["name"] for n in nodes if n["name"] not in executed]
            raise Exception(f"Circular dependency or missing nodes: {remaining}")
        
        # Execute ready nodes in parallel
        tasks = [self._execute_node(node, graph) for node in ready_nodes]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Process results
        for i, result in enumerate(results):
            node = ready_nodes[i]
            if isinstance(result, Exception):
                self.failed_nodes[node["name"]] = str(result)
            else:
                self.completed_nodes[node["name"]] = result
                executed.add(node["name"])
    
    return {
        "status": "completed",
        "completed_nodes": self.completed_nodes,
        "failed_nodes": self.failed_nodes,
    }
```

**Algorithm**:
1. Build adjacency list `graph` from edges
2. Initialize `executed` set (tracks completed nodes)
3. Loop until all nodes executed:
   - Find `ready_nodes` (dependencies satisfied, not yet executed)
   - Raise if no ready nodes (circular dependency)
   - Run all ready nodes in parallel (`asyncio.gather`)
   - Process results: store in `completed_nodes` or `failed_nodes`
   - Add successful nodes to `executed`
4. Return final state

**Parallelism**: All nodes with satisfied dependencies run concurrently (wave-based execution). Example: if 3 nodes depend on a single entry node, all 3 run in parallel once the entry node completes.

## Node execution (_execute_node)

```python
async def _execute_node(self, node, graph):
    node_name = node["name"]
    node_type = node["type"]
    config = node.get("config", {})
    inline = node.get("inline", True)
    
    # Prepare input from dependencies
    node_input = self._prepare_node_input(node, graph)
    
    if inline:
        # Execute inline node (lightweight, ~300s timeout)
        result = await workflow.execute_activity(
            execute_inline,
            node,
            node_input,
            start_to_close_timeout=workflow.timedelta(seconds=300),
            retry_policy=workflow.RetryPolicy(
                initial_interval=workflow.timedelta(seconds=1),
                maximum_interval=workflow.timedelta(seconds=60),
                maximum_attempts=3,
            ),
        )
    else:
        # Execute deferred node (long-running, ~3600s timeout)
        result = await workflow.execute_activity(
            enqueue_and_wait,
            node,
            node_input,
            start_to_close_timeout=workflow.timedelta(seconds=3600),
            retry_policy=workflow.RetryPolicy(
                initial_interval=workflow.timedelta(seconds=5),
                maximum_interval=workflow.timedelta(seconds=300),
                maximum_attempts=5,
            ),
        )
    
    # Update current inputs with node output
    if result and "output" in result:
        self.current_inputs[node_name] = result["output"]
    
    return result
```

**Inline vs deferred**:
- `inline=true`: Run in `execute_inline` activity (300s timeout, 3 retries, 60s max interval)
- `inline=false`: Run in `enqueue_and_wait` activity (3600s timeout, 5 retries, 300s max interval)

**Why two modes**: Inline for quick API calls/transforms; deferred for batch jobs that may take hours.

## Input mapping (_prepare_node_input)

```python
def _prepare_node_input(self, node, graph):
    node_name = node["name"]
    input_mapping = node.get("input_mapping", {})
    
    # Start with workflow-level inputs
    node_input = self.current_inputs.copy()
    
    # Apply input mapping
    for input_key, source_path in input_mapping.items():
        if source_path.startswith("$"):
            # Reference to another node's output
            source_node = source_path[1:]  # Remove $
            if source_node in self.completed_nodes:
                node_input[input_key] = self.completed_nodes[source_node]
            else:
                # Fallback to current_inputs
                node_input[input_key] = self.current_inputs.get(source_node)
        else:
            # Direct value
            node_input[input_key] = source_path
    
    return node_input
```

**Input mapping DSL**:
- `$node_name`: Wire the output of `node_name` to this input key
- Any other string: Use as a literal value

**Example**:
```json
{
  "name": "process",
  "input_mapping": {
    "data": "$start",
    "mode": "batch"
  }
}
```
→ `node_input = { "data": <output of start node>, "mode": "batch", ...workflow_input }`

## Node type dispatch (execute_inline activity)

Production pattern for node type dispatch:

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
    
    # Create node context
    context = NodeContext(
        trace_id=input_envelope.get("trace_id"),
        idempotency_key=input_envelope.get("idempotency_key"),
    )
    
    # Execute the node
    result = await execute_func(context, config, input_envelope)
    
    return {
        "status": "completed",
        "output": result,
        "node_name": node_name,
        "node_type": node_type,
    }
```

**Extensibility**: Add new node types by registering in `NODE_TYPE_MAP` and implementing an `async def execute(context, config, input_envelope)` function.

## Graph helpers

### _build_graph

```python
def _build_graph(self, nodes, edges):
    graph = {node["name"]: [] for node in nodes}
    for edge in edges:
        from_node = edge["from"]
        to_node = edge["to"]
        if from_node in graph:
            graph[from_node].append(to_node)
    return graph
```

Builds adjacency list: `graph[node_name] = [downstream_node_1, downstream_node_2, ...]`

### _find_entry_nodes

```python
def _find_entry_nodes(self, nodes, edges):
    incoming_edges = set()
    for edge in edges:
        incoming_edges.add(edge["to"])
    
    entry_nodes = []
    for node in nodes:
        if node["name"] not in incoming_edges:
            entry_nodes.append(node["name"])
    
    return entry_nodes
```

Finds nodes with no incoming edges (DAG roots).

### _are_dependencies_satisfied

```python
def _are_dependencies_satisfied(self, node_name, graph, executed):
    for from_node, to_nodes in graph.items():
        if node_name in to_nodes and from_node not in executed:
            return False
    return True
```

Checks if all upstream nodes (dependencies) are in the `executed` set.

## Signals and queries

### Signals (external updates)

```python
@workflow.signal
async def node_completed(self, signal: NodeCompleted):
    self.completed_nodes[signal.node_run_id] = signal.output_envelope

@workflow.signal
async def node_failed(self, signal: NodeFailed):
    self.failed_nodes[signal.node_run_id] = signal.error_envelope
```

**Use case**: External systems can signal node completion/failure (e.g., a long-running batch job triggers a webhook that signals the workflow).

### Queries (status inspection)

```python
@workflow.query
def status(self) -> Dict[str, Any]:
    return {
        "completed_nodes": list(self.completed_nodes.keys()),
        "failed_nodes": list(self.failed_nodes.keys()),
        "current_inputs": self.current_inputs,
    }

@workflow.query
def timeline(self) -> List[Dict[str, Any]]:
    timeline = []
    for node_name, result in self.completed_nodes.items():
        timeline.append({"node": node_name, "status": "completed", "result": result})
    for node_name, error in self.failed_nodes.items():
        timeline.append({"node": node_name, "status": "failed", "error": error})
    return timeline
```

**Use case**: External monitoring/dashboards query workflow state without blocking execution.

## Anti-patterns

- **Circular dependencies in edges**: DAG execution halts with exception `"Circular dependency or missing nodes"`
- **Missing nodes in edges**: If an edge references a non-existent node, `_build_graph` skips it (silent failure)
- **Unbounded inline nodes**: Setting `inline=true` for a 10-hour batch job will timeout (use `inline=false` for long-running tasks)
- **Input mapping to non-existent nodes**: `$nonexistent` resolves to `None` (fallback to `current_inputs.get(nonexistent)`), causing downstream errors

## Example workflow definition

```json
{
  "id": 456,
  "name": "user_onboarding",
  "version": 1,
  "nodes": [
    {
      "name": "create_user",
      "type": "db.upsert",
      "config": {
        "table": "users",
        "data": {"email": "user@example.com"}
      },
      "inline": true,
      "input_mapping": {}
    },
    {
      "name": "send_welcome_email",
      "type": "http.request",
      "config": {
        "url": "https://mail.example.com/send",
        "method": "POST"
      },
      "inline": true,
      "input_mapping": {
        "user_id": "$create_user.id"
      }
    },
    {
      "name": "provision_resources",
      "type": "business_logic",
      "config": {"action": "provision"},
      "inline": false,
      "input_mapping": {
        "user_id": "$create_user.id"
      }
    }
  ],
  "edges": [
    {"from": "create_user", "to": "send_welcome_email"},
    {"from": "create_user", "to": "provision_resources"}
  ]
}
```

**Execution flow**:
1. `create_user` runs first (entry node)
2. Once `create_user` completes, `send_welcome_email` and `provision_resources` run in parallel
3. `send_welcome_email` gets `user_id` from `create_user` output via `$create_user.id`
4. `provision_resources` is `inline=false` (long timeout, more retries)
5. Workflow completes when all 3 nodes succeed
