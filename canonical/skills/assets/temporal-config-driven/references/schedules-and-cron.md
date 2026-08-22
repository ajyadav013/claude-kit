# Temporal Schedules and Cron-Based Workflows

Temporal Schedules enable **cron-based recurring workflows** without external cron daemons. The scheduler is managed by Temporal Server and guarantees at-least-once execution.

## Schedule creation pattern

Production pattern for creating Temporal schedules:

```python
from temporalio.client import Client, Schedule, ScheduleActionStartWorkflow, ScheduleSpec
from datetime import timedelta

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

**Parameters**:
- `workflow_to_schedule`: The workflow class to run (e.g., `TempUploadWorkflow`)
- `queue`: Task queue name
- `cron_id`: Unique schedule ID (namespace-scoped; must be globally unique)
- `cron_expressions`: List of cron expressions (standard 5-field format: `"minute hour day month weekday"`)
- `args`: Input payload for the workflow (dict)
- `note`: Human-readable description

## Common cron expressions

```python
# Daily at 9 AM
cron_expressions=["0 9 * * *"]

# Every hour
cron_expressions=["0 * * * *"]

# Every 30 minutes
cron_expressions=["*/30 * * * *"]

# Weekdays at 6 AM
cron_expressions=["0 6 * * 1-5"]

# Multiple schedules (OR logic)
cron_expressions=["0 9 * * *", "0 21 * * *"]  # 9 AM and 9 PM daily
```

## Usage example

```python
async def start_schedules():
    try:
        # Daily upload workflow at 9 AM
        scheduler(
            workflow_to_schedule=TempUploadWorkflow,
            queue="temp-upload-queue",
            cron_id="temp-upload-daily",
            cron_expressions=["0 9 * * *"],
            args={"mode": "daily"},
            note="Daily temp file upload",
        )
        
        # Hourly sync workflow
        scheduler(
            workflow_to_schedule=LogisticsDashboardSyncWorkflow,
            queue="logistics-sync-queue",
            cron_id="logistics-sync-hourly",
            cron_expressions=["0 * * * *"],
            args={},
            note="Hourly logistics dashboard sync",
        )
        
        # Email notifications every 30 minutes
        scheduler(
            workflow_to_schedule=EmailNotificationWorkflow,
            queue="email-notification-queue",
            cron_id="email-notification-30min",
            cron_expressions=["*/30 * * * *"],
            args={},
            note="Email notifications every 30 minutes",
        )
        
    except Exception as e:
        logger.error(f"Error starting schedules: {e}")
        raise
```

## Schedule lifecycle

### Creating a schedule

```python
await client.create_schedule(id="my-schedule", schedule=Schedule(...))
```

**Idempotency**: `create_schedule` may raise an exception if the schedule ID already exists (exception type varies by SDK version). Best practice is to handle this on re-deploy:

```python
# Internet-confirmed pattern
try:
    await client.create_schedule(id=cron_id, schedule=schedule)
except Exception as e:
    if "already exists" in str(e).lower():
        logger.warning(f"Schedule {cron_id} already exists, skipping creation")
    else:
        raise
```

> Note: Production services may create schedules once on initial deployment without explicit error handling.

### Updating a schedule

```python
handle = client.get_schedule_handle(id="my-schedule")
await handle.update(lambda schedule: Schedule(...))
```

### Pausing a schedule

```python
handle = client.get_schedule_handle(id="my-schedule")
await handle.pause(note="Paused for maintenance")
```

### Resuming a schedule

```python
handle = client.get_schedule_handle(id="my-schedule")
await handle.unpause()
```

### Deleting a schedule

```python
handle = client.get_schedule_handle(id="my-schedule")
await handle.delete()
```

## Schedule guarantees

- **At-least-once execution**: If Temporal Server is down during a scheduled time, the workflow runs when the server recovers.
- **Backfill**: By default, missed schedules run immediately on catch-up. Configure `backfill_window` to limit this.
- **Timezone**: Cron expressions are UTC by default. Use `ScheduleSpec(timezone="America/New_York")` for local time.

## Schedule spec options

```python
from temporalio.client import ScheduleSpec, ScheduleIntervalSpec, ScheduleCalendarSpec
from datetime import timedelta

# Cron-based (most common)
spec = ScheduleSpec(cron_expressions=["0 9 * * *"])

# Interval-based (every N seconds/minutes/hours)
spec = ScheduleSpec(
    intervals=[ScheduleIntervalSpec(every=timedelta(hours=1))]
)

# Calendar-based (specific day of month/week)
spec = ScheduleSpec(
    calendars=[
        ScheduleCalendarSpec(
            hour=9,
            day_of_month=1,  # First of every month
        )
    ]
)

# Timezone-aware
spec = ScheduleSpec(
    cron_expressions=["0 9 * * *"],
    timezone="America/New_York",
)
```

## Anti-patterns

- **Duplicate schedule IDs across environments**: Schedule IDs are namespace-scoped. Use environment prefixes (`prod-daily-report`, `dev-daily-report`) to avoid collisions.
- **Not handling schedule creation errors**: Re-deploying workers that call `create_schedule` may fail if the schedule already exists. Handle idempotency by catching exceptions or using `update` instead of `create`.
- **Unbounded backfill**: If a schedule is paused for days, resuming triggers backfill of all missed runs. Set `backfill_window` to limit this:
  ```python
  schedule = Schedule(
      action=...,
      spec=...,
      policy=SchedulePolicy(
          backfill_window=timedelta(hours=24),  # Only backfill last 24 hours
      ),
  )
  ```
- **Ignoring timezone**: Cron expressions default to UTC. If your business logic assumes local time, set `timezone` explicitly.

## References

> Confirmed against: https://docs.temporal.io/develop/python/schedules (Schedule creation, cron expressions, backfill, timezone)
