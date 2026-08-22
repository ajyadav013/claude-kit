# Determinism (why workflows replay, and the rules that follow)

Workflows are durable because Workers **re-execute the workflow code from the top** to rebuild state
— after a crash, a cache eviction, or when a long timer fires. Instead of re-running side effects,
the SDK matches each operation your code emits (a **Command**) against the recorded **Event History**
and feeds back the stored result.

```
First run:   code → Commands → Server stores Events
Replay:      code runs again → Commands compared to stored Events
             match  → reuse stored result, continue
             differ → NondeterminismError (workflow blocks until code is fixed)
```

Every orchestration operation maps Command → Event, e.g.:

| Workflow code     | Command                       | Event                          |
|-------------------|-------------------------------|--------------------------------|
| Execute activity  | `ScheduleActivityTask`        | `ActivityTaskScheduled`        |
| Sleep / timer     | `StartTimer`                  | `TimerStarted`                 |
| Child workflow    | `StartChildWorkflowExecution` | `ChildWorkflowExecutionStarted`|
| Complete workflow | `CompleteWorkflowExecution`   | `WorkflowExecutionCompleted`   |

If replayed code emits a *different* Command than history recorded (or in a different order), replay
fails. Classic trap: branching on wall-clock time — `if now().hour < 12` takes one branch at first
run and the other on replay, producing a different `ScheduleActivityTask`.

## Sources of non-determinism (keep all of these OUT of workflow code)

- **Time**: `now()`, `time.time()`, `Date.now()`
- **Randomness / IDs**: `random()`, `Math.random()`, `uuid4()`
- **External state**: files, env vars, DBs, HTTP/network calls
- **Unordered iteration**: map/dict/set iteration order (language-dependent)
- **Concurrency/threads**: races that change ordering or outcome

## The central rule

**Put non-determinism and side effects in Activities.** An Activity runs *once per attempt* outside
replay, with durable recorded results, automatic retries, and timeouts. The workflow only
orchestrates. For a few common cases the SDK gives you replay-safe variants to use *inside* the
workflow instead of an activity — durable time, sleep, UUID, random, and a replay-aware logger
(e.g. `workflow.now()`, `workflow.sleep()`, `workflow.uuid4()`, `workflow.logger`; names vary by
SDK). Everything else → an activity.

## How much the SDK protects you (varies by language)

- **Python** — sandbox intercepts and aborts many non-deterministic calls *at runtime*, early.
- **TypeScript** — isolated V8 sandbox; auto-replaces common sources with deterministic variants.
- **Java / Go / .NET** — **no sandbox**; determinism is by convention (`Workflow.*` / `workflow.*`
  safe APIs). Violations usually surface only at *replay*. Optional static analyzers exist
  (`temporal-workflowcheck` for Java, `workflowcheck` for Go).
- **Ruby** — runtime illegal-call tracing on the workflow fiber + a durable fiber scheduler.
- **Rust** — runtime detection for external async wake sources; use SDK primitives (`ctx.timer()`,
  the SDK `select!`), avoid synchronous non-determinism by convention.

Regardless of SDK, **it is your responsibility** to keep workflow code deterministic. Don't rely on
the sandbox catching everything — write replay tests (`testing.md`).

## Recovery

- **Accidental non-determinism introduced by a code change** → revert workflow code to match history,
  restart the worker; the workflow auto-recovers.
- **Intentional logic change on running workflows** → use the **Patching API** or terminate-and-restart
  (`versioning.md`). Never just "edit and redeploy" a workflow with open executions.

## Best practices

1. Use SDK-provided safe variants for time / random / UUID / logging.
2. Move *all* I/O to activities; the workflow only orchestrates.
3. Write **replay tests** before deploying workflow changes.
4. Use **patching** for intentional changes to in-flight workflows.
5. Keep workflows small and focused — complexity is where non-determinism hides.
