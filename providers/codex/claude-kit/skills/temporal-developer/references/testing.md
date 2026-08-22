# Testing workflows

Three test layers, all runnable from a normal test framework (pytest, Jest/Vitest, `go test`, JUnit,
…). Examples below are Python (`temporalio.testing`); the *shape* is identical across SDKs — see
`references/{language}/testing.md` upstream for exact APIs.

## 1. Functional tests — run the workflow in a local environment

Start a local test environment, run a Worker inside it with your workflow + activities registered,
then drive it through the env's client. Use a **fresh UUID** for the task queue and workflow ID per
test so tests don't collide.

```python
import uuid, pytest
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker
from workflows import MyWorkflow
from activities import my_activity

@pytest.mark.asyncio
async def test_workflow():
    tq = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_local() as env:
        async with Worker(env.client, task_queue=tq,
                          workflows=[MyWorkflow], activities=[my_activity]):
            result = await env.client.execute_workflow(
                MyWorkflow.run, "input", id=str(uuid.uuid4()), task_queue=tq)
            assert result == ...
```

`start_local()` is shareable across tests (e.g. a session fixture). For workflows that sleep/use
timers, use **time-skipping** (`start_time_skipping()`) so a month-long timer resolves instantly —
but it **cannot** be shared between tests, so reach for it only when you must.

## 2. Mock activities — test orchestration in isolation

Register a stand-in activity under the **same name** to bypass real I/O:

```python
@activity.defn(name="compose_greeting")
async def compose_greeting_mocked(arg: str) -> str:
    return "mocked result"
# ... run a Worker with activities=[compose_greeting_mocked]
```

Test **failure paths**, not just happy paths: have a mock raise `ApplicationError(non_retryable=True)`
and assert the workflow surfaces `WorkflowFailureError`; cover retry exhaustion and cancellation too.

## 3. Signals / queries / updates

Use `start_workflow` (not `execute_workflow`) to get a handle, then drive it:

```python
handle = await env.client.start_workflow(MyWorkflow.run, ..., id=..., task_queue=tq)
await handle.signal(MyWorkflow.my_signal, "data")
assert await handle.query(MyWorkflow.get_status) == "expected"
result = await handle.result()
```

## 4. Replay tests — guard against non-determinism regressions

The most important test when you *change* a workflow: replay a recorded history through the new code.
If the code would emit a different Command sequence, the replayer raises — catching a determinism
break *before* it reaches production.

```python
from temporalio.worker import Replayer
replayer = Replayer(workflows=[MyWorkflow])
await replayer.replay_workflow(history)   # history saved from prod/staging
```

Save histories from real runs (`temporal workflow show --output json`, or fetch via the client) and
replay them in CI. Pair this with the `versioning.md` workflow whenever you touch a live workflow.

## Checklist

- [ ] Happy path runs in a local env
- [ ] Failure paths: activity retry exhaustion, non-retryable error, cancellation
- [ ] Signals/queries/updates exercised via a handle
- [ ] Replay test against a saved history for any changed workflow
