---
name: cron-and-scheduled-jobs
description: Scheduled / recurring jobs across the two mechanisms this stack uses — Kubernetes CronJobs (the schedule is declared in Helm values under a Crons block, and the app is invoked one-shot via MODE=cron + CRON_JOB into a Python cron registry) and Temporal Schedules (recurrence owned by the Temporal server via cron_expressions or interval specs, with overlap policy, pause-on-failure, and idempotent create-or-update registration run as a one-shot k8s Job). Covers how each is configured, how the schedule maps to the code that runs, concurrency/timezone/history, observability, and choosing between them. Use when adding a periodic or scheduled job, wiring a MODE=cron entrypoint and cron registry, declaring a CronJob in Helm values, registering or updating a Temporal schedule, or deciding between a Kubernetes CronJob and a Temporal Schedule.
---

# Cron & Scheduled Jobs

Two mechanisms run recurring work in this stack, and they put the *schedule* in two very different
places. Knowing which one you're in tells you where the schedule lives and what owns the recurrence:

1. **Kubernetes CronJob** — the cluster's `CronJob` controller is the scheduler. It fires a fresh pod
   on the schedule; the pod runs the **same service image** booted in a one-shot `MODE=cron` that
   executes a single named job from a Python registry and exits. The schedule lives in **Helm values**,
   never in the app.
2. **Temporal Schedule** — the **Temporal server** is the durable scheduler. A `Schedule` object fires
   a workflow on a cron expression or interval; a missed window, catch-up, pause, and backfill are all
   first-class. The schedule lives in **a registration step** (run once / idempotently on deploy).

> Companion skills: `temporal-config-driven` (workflow/activity/worker mechanics, retries, idempotency,
> and the deeper schedule-registration reference — this skill cross-links it rather than repeating it),
> `containerization-and-deployment` (the `MODE`-dispatch entrypoint and Helm packaging),
> `kubernetes-workload-hardening` (securityContext/NetworkPolicy for the CronJob pod), and
> `observability-and-logging` (the cron execution metric).

## When to use

- Adding a **periodic / scheduled job** to a service and deciding where the schedule belongs
- Wiring a **`MODE=cron` entrypoint** and registering a job in the **Python cron registry**
- Declaring a **CronJob in Helm values** (`Crons` block) and understanding the rendered manifest
- **Registering or updating a Temporal Schedule** (cron vs interval, overlap, pause-on-failure)
- Deploying schedule registration as a **one-shot k8s `Job`**
- Choosing between a **Kubernetes CronJob** and a **Temporal Schedule**
- Debugging "the job didn't run", overlapping runs, timezone drift, or piled-up executions

## Two mechanisms at a glance

| | **Kubernetes CronJob + `MODE=cron`** | **Temporal Schedule** |
|---|---|---|
| Scheduler | k8s `CronJob` controller | Temporal server |
| Where the schedule lives | Helm `values.yaml` → `Crons.<name>.Schedule` | a registration step (`create_schedule`) |
| What runs | one-shot pod: `MODE=cron CRON_JOB=<name>` → registry handler → exit | a Temporal workflow |
| Recurrence units | 5-field cron only | cron **or** interval (`every=` + `offset=`) |
| Overlap control | `concurrencyPolicy: Forbid` (coarse) | `ScheduleOverlapPolicy.SKIP/BUFFER_ONE/...` (rich) |
| Missed-run visibility | none (the pod just didn't run) | first-class (server tracks it) |
| Pause / backfill / manual fire | suspend the CronJob (no backfill) | `pause`/`unpause`/`backfill`/`trigger` |
| Retry across fires | none (pod exits; next fire is fresh) | per-fire `pause_on_failure` + workflow RetryPolicy |
| Best for | simple, self-contained periodic app tasks | durable/long jobs needing overlap, catch-up, visibility |

## Core conventions

### Kubernetes CronJob + `MODE=cron`

**The schedule is config, not code.** You declare a cron under the service's `Crons` block in Helm
values; the chart renders one `kind: CronJob` per entry. The job's *only* app-side coupling is two env
vars — `MODE=cron` and `CRON_JOB=<name>` — that tell the shared image which single job to run.

```yaml
# Helm values — Projects.<service>.Crons.<job-name>
Crons:
  nightly-report:
    Schedule: "0 2 * * *"            # 5-field cron (the authoritative schedule)
    Envs:
      MODE: cron                     # boot the image in one-shot cron mode
      CRON_JOB: nightly-report       # which registry entry to run
    ConcurrencyPolicy: Forbid        # default; don't start a fire if the last is still running
    Suspend: false                   # set true to pause without deleting
    TtlSecondsAfterFinished: 300     # GC the finished Job pod
    # Parallelism, Resources, NodeSelector, Tolerations also supported
```

The rendered CronJob carries sensible defaults from the chart: `concurrencyPolicy: Forbid`,
`failedJobsHistoryLimit: 3`, `successfulJobsHistoryLimit: 1`, `restartPolicy: Never`,
`ttlSecondsAfterFinished: 300`. **The chart has no `timeZone` and no `startingDeadlineSeconds`** — so
the schedule evaluates in the cluster's timezone (usually UTC) and a controller that's down past a fire
window silently skips it. Plan around both (see `references/choosing-and-operations.md`).

**The app side is a one-shot dispatcher, not a daemon.** A multi-mode `entrypoint.py` reads `MODE`; the
`cron` branch runs a single job from a registry and the process exits. There is no in-process scheduler
or loop — k8s owns the cadence.

```python
# entrypoint.py — the cron branch of the MODE dispatch
if MODE == "cron":                    # (server / consumer / worker / temporal_worker handled above)
    from crons.run import main as cron_main
    asyncio.run(cron_main())          # runs ONE job named by CRON_JOB, then exits

# crons/run.py — look up CRON_JOB, run it once, record the outcome
async def main():
    name = loaded_config.CRON_JOB
    entry = CRON_TASKS.get(name)
    if not entry:
        raise ValueError(f"No cron job found for name: {name}")
    start = asyncio.get_event_loop().time()
    try:
        result = await entry["task"]()                       # one-shot
        record_cron_job_executed(name, "success", asyncio.get_event_loop().time() - start)
        return result
    except Exception:
        record_cron_job_executed(name, "error", asyncio.get_event_loop().time() - start)
        raise
```

**The registry maps a name to a handler.** Two shapes are common — a plain `name → async callable`, or a
richer `name → {task, description, schedule}`. In the rich shape the `schedule` field is
**documentation only**; the authoritative schedule is the Helm `Crons` entry. Keep them in sync by
convention (the registry comment should point at the Helm values).

```python
# crons/registry.py — rich shape (schedule is a doc hint, NOT the real schedule)
CRON_TASKS = {
    "nightly-report": {
        "task": generate_nightly_report,
        "description": "Aggregate yesterday's events into the report table",
        "schedule": "0 2 * * *",        # for reference; defined for real in Helm values
    },
}
# simple shape: CRON_TASKS = {"nightly-report": generate_nightly_report}
```

Conventions that matter for CronJobs:
- **Idempotency is the job's responsibility.** `concurrencyPolicy: Forbid` prevents *overlap*, not
  *re-runs* — a retried/late fire may reprocess the same window. Make the handler safe to run twice
  (upsert, watermark/cursor, or a dedupe key).
- **Exit non-zero on failure.** `restartPolicy: Never` + a raised exception marks the Job failed and
  surfaces in `failedJobsHistoryLimit`. Don't swallow the exception.
- **Handle SIGTERM** for a graceful stop on pod eviction/rollout.
- **Emit the execution metric** (`record_cron_job_executed(name, status, duration)`) so cron health is
  observable — see `observability-and-logging`.

### Temporal Schedule

When the work is already a Temporal workflow, or needs durability / overlap control / catch-up /
visibility, let the Temporal **server** own the recurrence with a `Schedule`. The workflow/activity
mechanics live in `temporal-config-driven`; this skill covers the **scheduling dimension**.

**Prefer an interval spec over a cron expression for daily-ish cadences.** Temporal evaluates
`cron_expressions` in **UTC** by default (the chart/clients here don't set `time_zone`), so
`["0 9 * * *"]` fires at 09:00 *UTC*, not local. An interval with an offset is timezone-explicit and
avoids the foot-gun:

```python
from datetime import timedelta
from temporalio.client import (
    Schedule, ScheduleActionStartWorkflow, ScheduleIntervalSpec,
    ScheduleOverlapPolicy, SchedulePolicy, ScheduleSpec,
)

# Two fires/day, offset so they land at ~09:00 / 21:00 local (UTC+5:30 here):
spec = ScheduleSpec(
    intervals=[ScheduleIntervalSpec(every=timedelta(hours=12), offset=timedelta(hours=3, minutes=30))]
)
# (cron form, if you must: ScheduleSpec(cron_expressions=["0 2 * * *"]) — remember it's UTC)
```

**Register idempotently, and run it as a one-shot Job.** Build the schedule from the `spec` above plus
an `action` and `policy`, then register it safely:

```python
schedule = Schedule(
    action=ScheduleActionStartWorkflow(ReportWorkflow.run, {"mode": "daily"},
                                       id="nightly-report-run", task_queue="report-queue"),
    spec=spec,
    policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP, pause_on_failure=True),
)
# create-or-update: try client.create_schedule(...) / except "already exists" -> handle.update(...)
```

**Registration is a deploy step, not worker startup** — a separate one-shot k8s `kind: Job` (not a
CronJob) runs `python -m <pkg>.schedules ensure` after the worker Deployment is up, writing the schedule
into Temporal, which then fires it. The full create-or-update loop, the CLI, and the lifecycle helpers
(`pause`/`unpause`/`delete`/`update`) are owned by the **`temporal-config-driven`** skill; the Job
manifest, the interval/overlap details, and the manual-trigger snippet are in
`references/temporal-schedules.md`.

### Choosing between them

- **Kubernetes CronJob** when the task is a simple, self-contained periodic job, runs to completion in
  one shot, and `Forbid` overlap is enough. Lowest moving parts; the schedule is plain Helm config.
- **Temporal Schedule** when the job is long or durable, needs **overlap policy** finer than Forbid,
  **catch-up / backfill**, **per-fire pause-on-failure**, **missed-run visibility**, or is already a
  Temporal workflow. The server gives you scheduling observability a CronJob can't.

Don't run both for the same job (double fires). See `references/choosing-and-operations.md` for the
full decision matrix and the timezone/overlap/history details.

## Skeleton / example

A "nightly report" job, shown both ways. **Pick one** — they're alternatives, not layers.

```text
Kubernetes CronJob route                      Temporal Schedule route
────────────────────────                      ───────────────────────
Helm values: Crons.nightly-report             schedules.py: ensure() create-or-update
  Schedule "0 2 * * *"                           ScheduleSpec(intervals=[every=24h, offset=...])
  Envs MODE=cron CRON_JOB=nightly-report         overlap=SKIP, pause_on_failure=True
        │ k8s CronJob controller fires a pod   deploy: one-shot Job runs `... schedules ensure`
        ▼                                              │ Temporal server fires the workflow
entrypoint MODE=cron → crons/run.main()                ▼
  CRON_TASKS["nightly-report"]["task"]()        ReportWorkflow.run  (worker consumes it)
  record_cron_job_executed(...) → exit
```

See `references/kubernetes-cronjob.md` and `references/temporal-schedules.md` for the complete,
copy-ready versions of each.

## Anti-patterns to avoid

- **Putting the real schedule in app config.** For the k8s route the registry's `schedule` field is a
  doc hint only — the cluster reads the Helm `Crons.Schedule`. Editing the Python value changes nothing.
- **Assuming local time.** Both k8s CronJob (no `timeZone` in this chart) and Temporal `cron_expressions`
  evaluate in **UTC** here. Use interval+offset (Temporal) or compute the UTC cron, and write the
  intended local time in a comment.
- **Relying on `concurrencyPolicy` for correctness.** `Forbid` stops overlap, not duplicate processing.
  Non-idempotent handlers corrupt data on a late/retried fire.
- **Swallowing the exception** so the pod exits 0 — the failure never shows in
  `failedJobsHistoryLimit` and the job looks healthy while doing nothing.
- **Registering a Temporal schedule at worker startup**, or with a bare `create_schedule` that crashes
  the second deploy on "already exists." Use a one-shot Job + create-or-update.
- **Confusing a registration `Job` with a `CronJob`.** The schedule-registration manifest is a `Job`
  (runs once); the recurrence is owned by Temporal, not by re-running the Job.
- **Running the same job as both a k8s CronJob and a Temporal schedule** — it fires twice.
- **No execution metric / no alert** — a cron that silently stops is invisible until something
  downstream is missing. Emit `record_cron_job_executed` and alert on missing successes.
- **Unbounded history / no TTL** — leftover Job pods pile up; keep `ttlSecondsAfterFinished` and the
  history limits.

## References

- [kubernetes-cronjob.md](./references/kubernetes-cronjob.md) — The Helm `Crons` values schema, the
  rendered CronJob and its defaults, the `MODE=cron` entrypoint + one-shot runner, registry shapes,
  instrumentation/retry, and the `timeZone`/`startingDeadlineSeconds` gaps.
- [temporal-schedules.md](./references/temporal-schedules.md) — Cron vs interval specs, overlap and
  pause-on-failure policy, idempotent create-or-update registration, the one-shot registration Job,
  manual trigger, and lifecycle helpers (cross-links `temporal-config-driven`).
- [choosing-and-operations.md](./references/choosing-and-operations.md) — Decision matrix and the
  cross-cutting operational concerns: concurrency, timezone, history limits, missed runs/catch-up,
  suspend vs pause, and observability.
- [repo-evidence.md](./references/repo-evidence.md) — Representative patterns described generically.
