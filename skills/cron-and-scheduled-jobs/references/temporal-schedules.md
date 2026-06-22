# Temporal Schedules (reference)

When the recurrence needs durability, overlap control, catch-up, or visibility — or the work is already
a Temporal workflow — let the **Temporal server** own the schedule.

**The registration mechanics and lifecycle helpers are owned by the `temporal-config-driven` skill** —
its `references/schedule-registration.md` (idempotent create-or-update loop, CLI entry point, deployment
integration, multi-schedule registry) and `references/schedules-and-cron.md` (create / update / pause /
unpause / delete, schedule guarantees, backfill). This reference cross-links those instead of restating
them, and covers only what they don't: the **interval-vs-cron timezone choice**, the **overlap / pause
policy**, the **k8s Job that registers a schedule**, and the **k8s-CronJob-vs-Temporal decision**.

## Cron expression vs interval spec (the timezone choice)

A `ScheduleSpec` can fire on `cron_expressions` or `intervals`. **Prefer intervals for daily-ish
cadences in this stack**, because Temporal evaluates `cron_expressions` in **UTC** by default (these
services don't set the spec's `time_zone`), so a naive `["0 9 * * *"]` fires at 09:00 *UTC*, not local.

```python
from datetime import timedelta
from temporalio.client import ScheduleIntervalSpec, ScheduleSpec

# Interval + offset is timezone-explicit. every=12h with a 3h30m offset = ~09:00 / 21:00 at UTC+5:30.
twice_daily = ScheduleSpec(
    intervals=[ScheduleIntervalSpec(every=timedelta(hours=12), offset=timedelta(hours=3, minutes=30))]
)

# Cron form — fine for "top of the hour" cadences where UTC is acceptable, or compute the UTC time:
hourly = ScheduleSpec(cron_expressions=["0 * * * *"])   # every hour, on the hour (UTC)
```

The offset *is* the timezone handling: choose `every` for the period and `offset` to place the fire at
the local wall-clock time you want; always write the intended local time in a comment. (The SDK also
accepts a `time_zone` on the spec; these services don't use it, preferring the explicit offset.)

## Policy: overlap and pause-on-failure

```python
from temporalio.client import ScheduleOverlapPolicy, SchedulePolicy

policy = SchedulePolicy(
    overlap=ScheduleOverlapPolicy.SKIP,   # if the previous run is still going, skip this fire
    pause_on_failure=True,                # a failed run pauses the schedule instead of failing forever
)
```

- `ScheduleOverlapPolicy.SKIP` is the convention here — a long run never piles up on the next fire.
  Other options (`BUFFER_ONE`, `BUFFER_ALL`, `CANCEL_OTHER`, `TERMINATE_OTHER`, `ALLOW_ALL`) queue or
  pre-empt instead of skipping.
- `pause_on_failure=True` stops a broken schedule after a failure so it doesn't fire-and-fail every
  window; recover with `unpause()` once fixed.

> This `spec` and `policy` are the inputs to schedule registration. The **create-or-update loop** that
> registers them idempotently (try `create_schedule` / on "already exists" → `handle.update(...)`), the
> CLI entry point, and the multi-schedule registry are documented once in `temporal-config-driven` →
> `references/schedule-registration.md`. Pass this `spec`/`policy` into that loop — don't re-implement it
> here.

## The k8s Job that registers the schedule

This is the piece `temporal-config-driven` doesn't cover: how registration actually runs in the cluster.
Workers *consume* the workflows; a separate **one-shot k8s `kind: Job`** writes the schedule into
Temporal, run after the worker Deployment is up. Re-applying is safe because registration is
create-or-update; a completed Job won't re-run on its own (delete + re-apply to force it).

```yaml
apiVersion: batch/v1
kind: Job                                  # one-shot — registers the schedule, then the server fires it
metadata:
  name: ensure-schedule
  namespace: my-namespace
spec:
  backoffLimit: 3
  template:
    spec:
      restartPolicy: OnFailure
      containers:
        - name: ensure-schedule
          image: registry.example.com/my-service-worker:<tag>
          command: ["python", "-m", "myservice.schedules", "ensure"]   # the create-or-update entry point
          env:
            - { name: TEMPORAL_HOST, value: "temporal.example.svc:7233" }
            - { name: TEMPORAL_NAMESPACE, value: "default" }
            - { name: TEMPORAL_TASK_QUEUE, value: "report-queue" }
```

> A `kind: Job`, **not** a `kind: CronJob`: the recurrence is owned by the Temporal **Schedule** this Job
> creates, not by re-running the Job. (Contrast the k8s CronJob route, where the cluster itself is the
> scheduler — see `kubernetes-cronjob.md`.)

## Manual ad-hoc fire

To run one execution outside the schedule (smoke test / manual backfill), start the workflow directly or
trigger the schedule:

```python
await client.start_workflow(ReportWorkflow.run, {"mode": "daily"},
                            id="nightly-report-adhoc", task_queue="report-queue")
# or, via the schedule:  await client.get_schedule_handle("nightly-report").trigger()
```

The other lifecycle operations — `pause` / `unpause` / `delete` / `update`, and the
`... schedules pause|unpause|delete` CLI — are documented in `temporal-config-driven` →
`references/schedules-and-cron.md`.

## Why Temporal over a k8s CronJob (recap)

Use a Temporal Schedule when you need any of: rich **overlap policy** (finer than CronJob's `Forbid`),
**missed-run visibility / catch-up / backfill**, **per-fire pause-on-failure**, durable long-running
fires that survive worker restarts, or first-class **manual trigger** — none of which the k8s CronJob
route gives you. For a simple one-shot periodic task, the CronJob route is less machinery; see
`choosing-and-operations.md`.
