# Temporal Schedule Registration Patterns

This reference captures the **idempotent schedule registration** pattern for Temporal cron workflows, derived from production services.

## Registration module structure

Production services organize schedule registration in a dedicated module (e.g., `services/temporal/register_schedules.py` or `app/temporal/register_schedules.py`) that:

1. Imports workflow classes and task queue constants from the worker config
2. Defines a list of schedule configurations (ID, cron, workflow input)
3. Iterates through the list, creating each schedule with idempotency handling
4. Exports a `register_all_schedules()` entry point for CLI or deployment hooks

## Idempotent create_schedule pattern

The core pattern wraps `client.create_schedule` in a try/except block that catches "already exists" errors and logs a skip message:

```python
from temporalio.client import (
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleSpec,
)

async def register_domain_schedules():
    client = await get_temporal_client()
    
    schedules = [
        {
            "id": "data-sync-daily",
            "cron": "0 6 * * *",
            "workflow_id": "data-sync-daily-run",
            "input": {"sync_type": "full"},
        },
        {
            "id": "report-generation-monthly",
            "cron": "0 9 1 * *",
            "workflow_id": "report-monthly-run",
            "input": {"report_period": "last_month"},
        },
    ]
    
    for sched in schedules:
        try:
            await client.create_schedule(
                sched["id"],
                Schedule(
                    action=ScheduleActionStartWorkflow(
                        DomainWorkflow.run,
                        sched["input"],
                        id=sched["workflow_id"],
                        task_queue="domain-task-queue",
                    ),
                    spec=ScheduleSpec(cron_expressions=[sched["cron"]]),
                ),
            )
            logger.info("Schedule '%s' created with cron '%s'", sched["id"], sched["cron"])
        except Exception as e:
            if "already" in str(e).lower():
                logger.info("Schedule '%s' already exists — skipping", sched["id"])
            else:
                logger.exception("Failed to create schedule '%s'", sched["id"])
                raise
```

**Why idempotency matters**: Re-deploying a service that calls `create_schedule` during startup will fail if schedules already exist. The idempotency check allows the registration script to run on every deploy without errors.

## Common cron patterns

```python
# Daily at 6 AM UTC
"0 6 * * *"

# Daily at 11:59 PM UTC (end-of-day batch)
"59 23 * * *"

# Monthly on the 28th at 11:59 PM (end-of-month batch)
"59 23 28 * *"

# Every hour at the top of the hour
"0 * * * *"

# Weekdays at 9 AM
"0 9 * * 1-5"
```

## Integration with worker config

Schedules reference task queues defined in `WORKER_MODE_CONFIG_MAP`:

```python
# services/temporal/config.py
BATCH_PROCESSING_QUEUE = "batch_processing_queue"
REPORTING_QUEUE = "reporting_queue"

WORKER_MODE_CONFIG_MAP = {
    "batch_processor": {
        "task_queue": BATCH_PROCESSING_QUEUE,
        "workflows": [BatchProcessingWorkflow],
        "activities": [process_files, validate_data],
    },
    "reporter": {
        "task_queue": REPORTING_QUEUE,
        "workflows": [ReportGenerationWorkflow],
        "activities": [generate_report, send_notification],
    },
}

# services/temporal/register_schedules.py
async def register_batch_schedules():
    client = await get_temporal_client()
    await client.create_schedule(
        "batch-daily",
        Schedule(
            action=ScheduleActionStartWorkflow(
                BatchProcessingWorkflow.run,
                {"mode": "daily"},
                id="batch-daily-run",
                task_queue=BATCH_PROCESSING_QUEUE,  # Must match worker config
            ),
            spec=ScheduleSpec(cron_expressions=["0 6 * * *"]),
        ),
    )
```

Workers started with `--mode batch_processor` will poll `BATCH_PROCESSING_QUEUE` and execute workflows triggered by the schedule.

## Schedule action parameters

```python
ScheduleActionStartWorkflow(
    workflow_class.run,           # Workflow method (e.g., MyWorkflow.run)
    workflow_input,                # dict payload passed to workflow
    id="workflow-instance-id",     # Unique workflow ID (one per schedule trigger)
    task_queue="my-task-queue",    # Must match a worker's task_queue
    execution_timeout=timedelta(minutes=60),  # Optional workflow timeout
)
```

**Workflow ID strategy**: Use a static ID per schedule (e.g., `"daily-batch-run"`) if you want only one instance running at a time. Use dynamic IDs (e.g., `f"batch-{timestamp}"`) if concurrent runs are allowed.

## CLI entry point pattern

```python
# services/temporal/register_schedules.py
async def register_all_schedules() -> None:
    await register_batch_schedules()
    await register_reporting_schedules()
    await register_sync_schedules()

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(register_all_schedules())
```

**Usage**: `python -m services.temporal.register_schedules` (run once on deployment or idempotently on every deploy).

## Deployment integration

Common deployment patterns:

1. **One-time registration**: Run `register_schedules.py` manually after deploying the Temporal cluster. Schedules persist across worker restarts.
2. **Deployment hook**: Add a post-deploy step in CI/CD that runs `python -m services.temporal.register_schedules`. Idempotency ensures no errors on re-runs.
3. **Worker startup hook**: Call `register_all_schedules()` in the worker bootstrap script before starting the worker. Safe due to idempotency, but adds startup time.

## Anti-patterns

- **Hard-coded schedule IDs without environment prefix**: Schedules are namespace-scoped. Use env-prefixed IDs (`prod-daily-batch`, `dev-daily-batch`) to avoid collisions across environments.
- **No idempotency check**: `create_schedule` raises an exception if the schedule already exists. Always catch "already exists" errors or use `get_schedule_handle().update()` for updates.
- **Mismatched task queue**: The `task_queue` in `ScheduleActionStartWorkflow` must match a worker's `task_queue` from `WORKER_MODE_CONFIG_MAP`. Mismatches result in workflows that never execute.
- **Static workflow IDs without deduplication intent**: Using the same workflow ID for every schedule trigger means only one instance can run at a time (subsequent triggers fail). Use dynamic IDs if concurrent runs are expected.
- **Creating schedules in worker bootstrap without idempotency**: Workers may restart frequently (scaling, deploys). Schedule creation must be idempotent or moved to a one-time deployment hook.

## Example: Multi-schedule registration

```python
from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

from temporalio.client import Schedule, ScheduleActionStartWorkflow, ScheduleSpec

from app.temporal.client import get_temporal_client
from app.temporal.config import SYNC_QUEUE, REPORT_QUEUE
from app.workflows import DataSyncWorkflow, ReportGenerationWorkflow

logger = logging.getLogger("app.temporal.register_schedules")


async def register_sync_schedules() -> None:
    client = await get_temporal_client()
    
    sync_schedules = [
        {
            "id": "data-sync-hourly",
            "cron": "0 * * * *",
            "workflow_id": "data-sync-hourly-run",
            "input": {"sync_mode": "incremental"},
        },
        {
            "id": "data-sync-daily",
            "cron": "0 6 * * *",
            "workflow_id": "data-sync-daily-run",
            "input": {"sync_mode": "full"},
        },
    ]
    
    for sched in sync_schedules:
        try:
            await client.create_schedule(
                sched["id"],
                Schedule(
                    action=ScheduleActionStartWorkflow(
                        DataSyncWorkflow.run,
                        sched["input"],
                        id=sched["workflow_id"],
                        task_queue=SYNC_QUEUE,
                    ),
                    spec=ScheduleSpec(cron_expressions=[sched["cron"]]),
                ),
            )
            logger.info("Schedule '%s' created", sched["id"])
        except Exception as e:
            if "already" in str(e).lower():
                logger.info("Schedule '%s' already exists — skipping", sched["id"])
            else:
                logger.exception("Failed to create schedule '%s'", sched["id"])
                raise


async def register_report_schedules() -> None:
    client = await get_temporal_client()
    
    try:
        await client.create_schedule(
            "monthly-report",
            Schedule(
                action=ScheduleActionStartWorkflow(
                    ReportGenerationWorkflow.run,
                    {"report_type": "monthly"},
                    id="monthly-report-run",
                    task_queue=REPORT_QUEUE,
                    execution_timeout=timedelta(minutes=120),
                ),
                spec=ScheduleSpec(cron_expressions=["0 9 1 * *"]),
            ),
        )
        logger.info("Schedule 'monthly-report' created")
    except Exception as e:
        if "already" in str(e).lower():
            logger.info("Schedule 'monthly-report' already exists — skipping")
        else:
            logger.exception("Failed to create schedule 'monthly-report'")
            raise


async def register_all_schedules() -> None:
    await register_sync_schedules()
    await register_report_schedules()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(register_all_schedules())
```

## References

- [schedules-and-cron.md](schedules-and-cron.md) — Temporal schedule creation, lifecycle, and cron expressions
- Temporal Python SDK docs: https://docs.temporal.io/develop/python/schedules
