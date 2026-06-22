# Kubernetes CronJob + `MODE=cron` (reference)

The k8s route runs a recurring app job in three moving parts: a **Helm values declaration**, the
**rendered CronJob manifest**, and the **app-side one-shot dispatch**. The schedule lives in the first;
the app only learns *which* job to run, via two env vars.

## 1. Declaring the cron in Helm values

Each service has a `Crons` map under its project block. One entry = one CronJob.

```yaml
Projects:
  my-service:
    # ... image, common envs, resources ...
    Crons:
      nightly-report:
        Schedule: "0 2 * * *"             # 5-field cron — the authoritative schedule
        Envs:
          MODE: cron                      # boot the shared image in one-shot cron mode
          CRON_JOB: nightly-report        # selects the registry entry to run
        ConcurrencyPolicy: Forbid         # default; skip a fire while the previous is running
        Suspend: false                    # true = pause without deleting the CronJob
        Parallelism: 1                    # default
        TtlSecondsAfterFinished: 300      # default; GC the finished Job
        # Resources, NodeSelector, Tolerations, ReadinessProbe, LivenessProbe also supported
        # Ignore: true       -> skip rendering this cron entirely
        # IgnoreHealthCheck: true -> drop the readiness/liveness probes for this job
```

Fields the chart understands per cron: `Schedule`, `Envs`, `ConcurrencyPolicy`, `Suspend`,
`Parallelism`, `TtlSecondsAfterFinished`, `Ignore`, `IgnoreHealthCheck`, `Resources`, `NodeSelector`,
`Tolerations`, `Entrypoint`/`Arguments` (override the container command), `Annotations`, `ReadinessProbe`,
`LivenessProbe`.

## 2. The rendered CronJob (and its defaults)

The chart ranges over `Crons` and emits one `batch/v1` `CronJob` per entry. The defaults baked in:

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: <release>-<service>-<job>-cron
spec:
  schedule: "0 2 * * *"                 # from Crons.<job>.Schedule
  concurrencyPolicy: Forbid             # default
  failedJobsHistoryLimit: 3             # fixed in the chart
  successfulJobsHistoryLimit: 1         # fixed in the chart
  suspend: false                        # from Crons.<job>.Suspend
  jobTemplate:
    spec:
      parallelism: 1                    # from Crons.<job>.Parallelism
      ttlSecondsAfterFinished: 300      # from Crons.<job>.TtlSecondsAfterFinished
      template:
        spec:
          restartPolicy: Never          # fixed — a failed fire is a failed Job
          containers:
            - name: <release>-<service>
              image: <registry>/<path>:<tag>     # the SAME service image
              env:
                - { name: MODE, value: "cron" }
                - { name: CRON_JOB, value: "nightly-report" }
                # + project/common envs, downward-API, DB/secret refs merged in
              envFrom:
                - configMapRef: { name: <common-config-map> }
              # readiness/liveness probes are file-mtime based (a health file the job touches),
              # unless IgnoreHealthCheck: true
```

**Two gaps in this chart to design around:**
- **No `timeZone`.** The schedule evaluates in the cluster's zone (typically **UTC**). `"0 2 * * *"`
  is 02:00 UTC. Either compute the UTC time for your intended local hour, or move the job to a Temporal
  interval spec (see `temporal-schedules.md`). Always write the intended local time in a comment.
- **No `startingDeadlineSeconds`.** If the CronJob controller is down across a fire window, that fire is
  **silently skipped** (no catch-up). For jobs where a missed run matters, prefer a Temporal Schedule
  (the server tracks missed windows) or add an external "did it run?" alert.

## 3. App-side: one-shot dispatch, not a daemon

The container starts with `MODE=cron CRON_JOB=<name>`. A multi-mode `entrypoint.py` branches on `MODE`;
the `cron` branch imports the one-shot runner and exits when the single job completes. There is **no**
APScheduler, no `while True`, no in-process timer — the k8s controller owns the cadence.

```python
# entrypoint.py — multi-mode dispatch (server / consumer / worker / cron / temporal_worker)
MODE = os.environ.get("MODE")
if MODE == "server":
    ...
elif MODE == "cron":
    from crons.run import main as cron_main
    print(f"Starting {loaded_config.CRON_JOB} Cron Job")
    asyncio.run(cron_main())             # one job, then the process exits
```

```python
# crons/run.py — resolve CRON_JOB, run once, instrument, handle SIGTERM
import asyncio, signal
from config.docker_config import loaded_config
from crons.registry import CRON_TASKS
from metrics.helper import record_cron_job_executed

async def main():
    name = loaded_config.CRON_JOB
    entry = CRON_TASKS.get(name)
    if not entry:
        raise ValueError(f"No cron job found for name: {name}")

    async def run_once():
        start = asyncio.get_event_loop().time()
        try:
            result = await entry["task"]()                 # rich shape: entry["task"]; simple: entry()
            record_cron_job_executed(name, "success", asyncio.get_event_loop().time() - start)
            return result
        except Exception:
            record_cron_job_executed(name, "error", asyncio.get_event_loop().time() - start)
            raise

    task = asyncio.create_task(run_once())

    def on_sigterm(signum, _frame):
        raise KeyboardInterrupt                            # graceful stop on eviction/rollout
    signal.signal(signal.SIGTERM, on_sigterm)

    try:
        await asyncio.gather(task)
    except KeyboardInterrupt:
        pass                                               # cleanup, then exit
```

## 4. The cron registry

A module maps each `CRON_JOB` name to its handler. Two shapes are in use; pick one per service and be
consistent.

```python
# simple shape — name -> async callable
CRON_TASKS = {
    "nightly-report": generate_nightly_report,
    "hourly-sync": sync_from_upstream,
}
```

```python
# rich shape — name -> {task, description, schedule}
from functools import partial

CRON_TASKS = {
    "nightly-report": {
        "task": generate_nightly_report,
        "description": "Aggregate yesterday's events into the report table",
        "schedule": "0 2 * * *",          # DOC ONLY — the real schedule is in Helm values
    },
    "vendor-sync-a": {
        "task": partial(sync_vendor, "team-a"),   # partials bind per-tenant args to one handler
        "description": "Pull team-a vendor updates",
        "schedule": "0 */1 * * *",        # doc only
    },
}
```

> The rich shape's `schedule` is a hint for humans reading the code. The cluster never sees it — it reads
> `Crons.<job>.Schedule`. Keep a comment in the registry pointing at the Helm values so they don't drift.

## 5. Conventions

- **Make the handler idempotent.** `concurrencyPolicy: Forbid` prevents overlapping pods, but a late or
  manually re-triggered fire can reprocess a window. Upsert, carry a watermark/cursor, or use a dedupe
  key. (`Forbid` is overlap protection, not exactly-once.)
- **Fail loudly.** Raise on error so the exception propagates, the pod exits non-zero, and the failure
  lands in `failedJobsHistoryLimit`. Don't `except: pass`.
- **Optional retry decorator.** Some services wrap the handler in a `@retry_cron(max_retries=..., 
  no_retry_exceptions=(...))` decorator with DB-backed logging for in-process retries within a single
  fire. Keep terminal/validation errors in `no_retry_exceptions` so they don't retry-storm.
- **Emit the metric.** `record_cron_job_executed(name, "success"|"error", duration_seconds)` feeds cron
  dashboards/alerts (see `observability-and-logging`).
- **Keep TTL + history bounded** (`ttlSecondsAfterFinished`, `failedJobsHistoryLimit`,
  `successfulJobsHistoryLimit`) so finished Job pods don't accumulate.

## 6. Operating it

- **Pause** without deleting: `Suspend: true` (re-renders the CronJob with `suspend: true`).
- **Run now** (ad hoc): `kubectl create job --from=cronjob/<name> <name>-manual-<id>`.
- **Inspect**: `kubectl get cronjob`, `kubectl get jobs`, then `kubectl logs job/<name>`.
- **Disable entirely**: `Ignore: true` on the cron entry (the chart skips rendering it).
