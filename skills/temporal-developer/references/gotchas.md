# Gotchas (the cross-language anti-patterns that cost the most time)

Conceptual traps that recur in every SDK. See `references/{language}/gotchas.md` upstream for the
language-specific symptoms.

## Non-idempotent activities

Activities run **at least once** — retries and worker failures cause re-execution. An external call
without an idempotency key can double-charge a card, send duplicate emails, or create duplicate rows.
**Fix:** pass an idempotency key (workflow ID, activity ID, or a domain key like order ID) to every
external mutation. Local Activities are faster but still retried — same rule applies.

## Side effects / non-determinism in workflow code

Workflow code runs on the first execution **and every replay**. Any side effect (log, metric,
notification) fires multiple times; any non-deterministic call (clock, random, I/O, threads) breaks
replay. **Fix:** use the SDK's replay-safe variants for logging/time/UUID/random; put everything else
in an activity. (See `determinism.md`.)

## Multiple workers running different code

If worker A runs part of a workflow on v1 and worker B (v2) picks it up, replay can mismatch.
**Fix in prod:** worker versioning or patching. **Fix in dev:** kill old workers before starting new
ones; ensure every worker on a task queue runs identical code. Workflows started on old code keep
running after you change it — in *dev only*, terminate stale ones.

## Retry policy mistakes

- **Failing too fast** — `maximum_attempts=1` everywhere turns transient blips into workflow
  failures. Reserve it for truly non-retryable ops; otherwise let exponential backoff ride out
  transient errors.
- **Wrong classification** — **retryable**: network errors, timeouts, rate limits, transient
  unavailability. **Non-retryable**: invalid input, auth failures, business-rule violations, not-found.
  Mark them correctly or you get infinite retries on bad input (or hard failures on a blip).

## Query / update-validator misuse

Queries and update **validators** are strictly **read-only and non-blocking** — they must not mutate
state (non-determinism on replay) and must not await activities/timers/conditions (timeouts,
deadlocks). Need to mutate-and-return? Use an **Update**. Need to trigger async work? Use a **Signal**
or **Update**. *(Query to peek, Signal to push, Update to pop.)*

## Cancellation not handled

- **Workflow cancellation:** cleanup after the cancellation point won't run unless protected — use
  cancellation scopes / `try…finally` for compensation and resource release.
- **Activity cancellation:** an activity only learns it was cancelled if it **heartbeats** and
  **checks** for cancellation. Otherwise it runs to completion, wasting compute and delaying the
  workflow. Heartbeat long-running activities and react to the cancellation signal.

## Swallowing errors

Catching without handling produces silent failures and workflows that "succeed" despite errors. Log
and decide deliberately: re-raise, fall back, or document why ignoring is safe.

## Payload size limits

Hard limits: **2 MB** per payload, **4 MB** per gRPC message, **50 MB** per workflow history (aim for
< 10 MB). **Fix:** store large blobs externally (S3/GCS) and pass references, use a compression codec,
or chunk across activities. Unbounded history → use **Continue-as-New** to reset it.

## Dev-server / CLI gotchas

- `temporal server start-dev` is **in-memory and single-process** — state is lost on restart
  (`--db-filename` persists it) and it is **never** for production.
- `temporal workflow update` is a **command group**, not one command — use
  `update execute|start|result|describe`.
- On `workflow update start`, `--wait-for-stage` only accepts `accepted`.
- On `workflow reset`, `--reapply-type` only accepts `Signal` or `None`.
