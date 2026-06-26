# temporal-config-driven

Temporal workflow orchestration patterns derived from real-world production Python/FastAPI services, encoding:

- **Config-driven worker maps** (`WORKER_MODE_CONFIG_MAP`) for mode-based task queue/workflow/activity assembly
- **Workflow and activity definitions** using Temporal Python SDK decorators (@workflow.defn, @activity.defn)
- **Retry policies, timeouts, and idempotency** via `activity_id` injection (execute_activity_with_activity_id helper)
- **DAG-based config interpreter** for config-as-data orchestration (nodes + edges JSON)
- **Cron-based workflow schedules** for recurring workflows (daily, hourly, custom intervals)
- **Client initialization** patterns (host, namespace, TLS-optional)
- **Dynamic worker generation** for matrix-based workers (e.g., file_type × business_unit)
- **Graceful shutdown** patterns (SIGTERM/SIGINT handling in worker processes)

## Related skill

For Temporal **fundamentals** — durable execution, why workflows must be deterministic (history
replay), safely changing running workflows (patching/worker versioning), testing
(time-skipping/replay), signals/queries/updates, and non-Python SDKs — use the complementary
**`temporal-developer`** skill. This skill assumes those fundamentals and focuses on the
config-driven worker-map / DAG-as-data architecture.

## Source provenance

Derived from real-world production Python/FastAPI services implementing Temporal orchestration at scale.

## How to apply

1. **Review SKILL.md** for the "When to use" triggers and core conventions.
2. **Copy the worker config map pattern** from `references/worker-workflow-activity-patterns.md` when setting up a new Temporal service.
3. **Use the idempotency helper** (`execute_activity_with_activity_id`) for all retryable activities.
4. **Reference retry policy templates** in `references/config-and-retry-idempotency.md` when defining workflows.
5. **Study the DAG-based config interpreter** in `references/dag-dsl-interpreter.md` if implementing or debugging config-driven DAG orchestration.
6. **Set up cron-based schedules** using patterns from `references/schedules-and-cron.md` for recurring workflows (daily reports, batch jobs, periodic syncs).

## Provenance

- **Codebase-derived**: Worker maps, bootstrap logic, @workflow.defn/@activity.defn patterns, retry policies, idempotency helpers, DAG interpreter architecture, NODE_TYPE_MAP dispatch.
- **Internet-confirmed**: Temporal RetryPolicy fields (`initial_interval`, `maximum_interval`, `maximum_attempts`, `backoff_coefficient`) and timeout types (`start_to_close_timeout`, `schedule_to_close_timeout`, `schedule_to_start_timeout`) confirmed against Temporal Python SDK documentation.

> Confirmed against: https://docs.temporal.io/develop/python/failure-detection#retry-policy (RetryPolicy parameters and timeout types)
