# Choosing a mechanism + operational concerns (reference)

## Decision matrix

Start from the job's needs, not the tooling. Walk these in order — the first "yes" usually decides it.

| Question | If yes → |
|---|---|
| Is the work already a Temporal workflow? | **Temporal Schedule** (don't fork it into a CronJob) |
| Must a *missed* fire be visible / caught up later? | **Temporal Schedule** (server tracks missed windows; the CronJob chart has no `startingDeadlineSeconds`) |
| Do you need overlap handling finer than "skip if running"? | **Temporal Schedule** (`BUFFER_ONE`, `CANCEL_OTHER`, …) |
| Should a failing run pause the schedule (not fire-and-fail forever)? | **Temporal Schedule** (`pause_on_failure`) |
| Do you need backfill / replay of past windows? | **Temporal Schedule** |
| Is the run long-lived and must survive worker/pod restarts mid-run? | **Temporal Schedule** (durable workflow) |
| Is it a short, self-contained task where "skip if still running" is enough? | **Kubernetes CronJob** |
| Do you want the fewest moving parts and the schedule as plain Helm config? | **Kubernetes CronJob** |

Rules of thumb:
- **Default to the k8s CronJob** for simple periodic app tasks — it's the least machinery and the
  schedule is one line of Helm config.
- **Reach for Temporal** the moment you need scheduling *observability or control* the CronJob can't
  give you (missed-run tracking, overlap policy, pause-on-failure, backfill, durability).
- **Never run both** for the same logical job — it fires twice. Pick one home for the schedule.

## Concurrency / overlap

- **k8s CronJob:** `concurrencyPolicy` is coarse — `Forbid` (default here; skip if the last is still
  running), `Allow`, or `Replace`. It prevents overlapping *pods*; it does **not** make a handler
  exactly-once. A late or manually re-triggered fire can still reprocess a window — the handler must be
  idempotent.
- **Temporal:** `ScheduleOverlapPolicy` is rich — `SKIP` (convention here), `BUFFER_ONE`, `BUFFER_ALL`,
  `CANCEL_OTHER`, `TERMINATE_OTHER`, `ALLOW_ALL`. Choose based on whether a long run should skip,
  queue, or pre-empt the next.

## Timezone

Both routes default to **UTC** here, and getting this wrong is the most common "it ran at the wrong
time" bug:
- **k8s CronJob:** the chart sets no `timeZone`, so `Schedule` evaluates in the cluster zone (UTC).
  Compute the UTC time for your intended local hour, and comment the local intent
  (`# 07:30 UTC = 13:00 IST`).
- **Temporal:** `cron_expressions` evaluate in UTC unless `time_zone` is set (it isn't here). Prefer a
  `ScheduleIntervalSpec(every=..., offset=...)` — the offset places the fire at the local wall-clock
  time explicitly and dodges DST/zone ambiguity for fixed-interval cadences.

## Missed runs / catch-up

- **k8s CronJob:** no `startingDeadlineSeconds` in this chart → if the controller is down across a fire
  window, that fire is **silently skipped**, no catch-up. For jobs where a missed run matters, either
  move to Temporal or add an external "did it run in the last N hours?" alert keyed on the execution
  metric.
- **Temporal:** the server records missed windows; overlap/backfill policies decide whether to catch up.

## History / cleanup

- **k8s CronJob:** the chart fixes `failedJobsHistoryLimit: 3` and `successfulJobsHistoryLimit: 1`, and
  `ttlSecondsAfterFinished` (default 300) GCs finished Job pods. Keep these bounded so pods don't pile
  up; bump the failed-history limit temporarily when debugging a flaky job.
- **Temporal:** runs are workflow executions, retained per the namespace's retention policy and visible
  in the Temporal UI.

## Suspend vs pause

- **k8s CronJob:** `Suspend: true` in Helm values (renders `suspend: true`) stops new fires without
  deleting the CronJob. In-flight jobs continue. `Ignore: true` removes the CronJob from the render
  entirely.
- **Temporal:** `pause()/unpause()` on the schedule handle (also auto-paused by `pause_on_failure`).
  Paused schedules keep their definition and history; unpausing resumes future fires.

## Observability

- Emit `record_cron_job_executed(name, "success"|"error", duration_seconds)` from the cron runner so
  every fire is a data point (see `observability-and-logging`). Build the alert on **absence of
  success** (a cron that silently stops is invisible otherwise), not just on errors.
- For Temporal, the server UI shows recent/next fires, paused state, and per-run history — but still
  alert on "no successful run in the expected window" so a paused-on-failure schedule is noticed.
- Log with the job name and a run/correlation id so a single fire is greppable end to end.

## Idempotency (both routes)

Neither route guarantees exactly-once delivery of *effects*. Design every scheduled handler to be safe
to run twice:
- upsert instead of insert; carry a watermark/cursor; or derive a deterministic dedupe/run key from the
  window (e.g. the date) so re-processing the same window is a no-op.
- For Temporal, a deterministic workflow id per window makes a duplicate fire a no-op (the server
  rejects a duplicate running id); see `temporal-config-driven` for `activity_id`-based idempotency.
