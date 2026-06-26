# Language starters (compact)

Every SDK follows the same shape: **define** activities + a workflow → **register** both in a Worker
bound to a task queue → **start** the workflow from a client. Keep workflow and activity definitions
in **separate files** (sandboxes reload workflow files on every execution; mixing hurts performance).
These are minimal starters — for the full per-language API use the upstream link at the bottom.

## Python (`temporalio`, Python 3.9+, async; sandboxed)

```python
# activities/greet.py
from temporalio import activity
@activity.defn
def greet(name: str) -> str:
    return f"Hello, {name}!"

# workflows/greeting.py
from datetime import timedelta
from temporalio import workflow
with workflow.unsafe.imports_passed_through():      # import activities through the sandbox
    from activities.greet import greet
@workflow.defn
class GreetingWorkflow:
    @workflow.run
    async def run(self, name: str) -> str:
        return await workflow.execute_activity(
            greet, name, start_to_close_timeout=timedelta(seconds=30))

# worker.py
import asyncio, concurrent.futures
from temporalio.client import Client
from temporalio.worker import Worker
async def main():
    client = await Client.connect("localhost:7233")
    with concurrent.futures.ThreadPoolExecutor(max_workers=100) as ex:   # sync activities need an executor
        await Worker(client, task_queue="my-task-queue",
                     workflows=[GreetingWorkflow], activities=[greet],
                     activity_executor=ex).run()
asyncio.run(main())
```

Notes: prefer **sync** activities (safer/easier to debug); async activities need async-safe libs
throughout (`aiohttp`, not `requests`). Use `workflow.logger` (not `print`). Don't mix workflows and
activities in one file. `gevent` is incompatible.

## Go (`go.temporal.io/sdk`; no sandbox — determinism by convention)

```go
// activity.go
func Greet(ctx context.Context, name string) (string, error) { return "Hello, " + name + "!", nil }

// workflow.go
func GreetingWorkflow(ctx workflow.Context, name string) (string, error) {
    ctx = workflow.WithActivityOptions(ctx, workflow.ActivityOptions{StartToCloseTimeout: time.Minute})
    var out string
    err := workflow.ExecuteActivity(ctx, Greet, name).Get(ctx, &out)
    return out, err
}

// worker/main.go
c, _ := client.Dial(client.Options{})            // defaults to localhost:7233
defer c.Close()
w := worker.New(c, "my-task-queue", worker.Options{})
w.RegisterWorkflow(GreetingWorkflow)
w.RegisterActivity(Greet)
_ = w.Run(worker.InterruptCh())
```

Use `workflow.Now`, `workflow.Sleep`, `workflow.SideEffect` (never `time.Now`, `time.Sleep`, `rand`)
inside a workflow. Run the optional `workflowcheck` analyzer in CI.

## TypeScript (`@temporalio/*`; isolated V8 sandbox)

```ts
// activities.ts
export async function greet(name: string): Promise<string> { return `Hello, ${name}!`; }

// workflows.ts
import * as wf from '@temporalio/workflow';
import type * as activities from './activities';
const { greet } = wf.proxyActivities<typeof activities>({ startToCloseTimeout: '1 minute' });
export async function greeting(name: string): Promise<string> { return greet(name); }

// worker.ts
import { Worker } from '@temporalio/worker';
import * as activities from './activities';
const worker = await Worker.create({
  workflowsPath: require.resolve('./workflows'), activities, taskQueue: 'my-task-queue' });
await worker.run();
```

The sandbox swaps `Date.now`/`Math.random` for deterministic variants; still keep I/O in activities.

## Starting a workflow (client, any SDK — Python shown)

```python
handle = await client.start_workflow(
    GreetingWorkflow.run, "world", id="greeting-1", task_queue="my-task-queue")
print(await handle.result())
# or the one-shot: await client.execute_workflow(...)
```

## Upstream per-language depth

The kit ships compact starters only. For the full guides — **Java, .NET, Ruby, Rust** (not shown
above), per-language determinism/testing/versioning/error-handling, and integrations (OpenAI Agents
SDK, Google ADK, …) — use the authoritative MIT source:

- https://github.com/temporalio/skill-temporal-developer (`references/{python,go,typescript,java,dotnet,ruby,rust}/`)
- https://docs.temporal.io
