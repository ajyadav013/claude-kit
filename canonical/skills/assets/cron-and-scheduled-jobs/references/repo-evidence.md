# Representative patterns (generic)

Where each piece of the two cron mechanisms typically lives in a service of this shape. Paths are
illustrative conventions — adapt to the actual repo layout. No internal service, host, registry, or
project names appear here by design.

## Kubernetes CronJob route

| Concern | Typical location | What it holds |
|---|---|---|
| Schedule declaration | `base_values/` or `<env>/values.yaml` → `Projects.<service>.Crons.<job>` | `Schedule`, `Envs` (`MODE=cron`, `CRON_JOB`), `ConcurrencyPolicy`, `Suspend`, `Ttl…` |
| Chart template | `charts/<base-chart>/templates/cron*.yaml` | ranges over `Crons`, renders one `batch/v1` `CronJob` per entry with the fixed defaults |
| Mode dispatch | `entrypoint.py` | reads `MODE`; the `cron` branch calls the one-shot runner |
| One-shot runner | `crons/run.py` (or `cron/run.py`) | resolves `CRON_JOB`, runs one handler, records the metric, handles SIGTERM |
| Registry | `crons/registry.py` / `crons/config.py` / `cron/cron_mapping.py` | `name → callable` or `name → {task, description, schedule}` |
| Metric | `metrics/helper.py` | `record_cron_job_executed(name, status, duration)` |
| Optional retry | `crons/retry_decorator.py` | `@retry_cron(max_retries, no_retry_exceptions=...)` + DB-backed logging |

Key facts observed across services:
- The schedule is always in Helm values; the registry's `schedule` field, when present, is a doc hint
  ("for reference; also defined in the chart").
- The cron pod runs the **same image** as the API/worker — only `MODE`/`CRON_JOB` differ.
- The runner is genuinely one-shot: a single `asyncio` task, then the process exits. No in-app loop.
- Chart-level constants seen repeatedly: `concurrencyPolicy: Forbid`, `failedJobsHistoryLimit: 3`,
  `successfulJobsHistoryLimit: 1`, `restartPolicy: Never`, `ttlSecondsAfterFinished: 300`; **no**
  `timeZone`, **no** `startingDeadlineSeconds`.

## Temporal Schedule route

| Concern | Typical location | What it holds |
|---|---|---|
| Schedule registration | `services/temporal/register_schedules.py` or `<pkg>/scripts/schedules.py` | `ensure`/`create-or-update`, schedule registry list, `ScheduleSpec` |
| Schedule helpers | `services/temporal/utils.py` | `scheduler(...)`, `unpause_schedule`, `delete_schedule`, `update_schedule_cron` |
| Deploy hook | `deploy/schedule-job.yaml` | one-shot `kind: Job` that runs `... schedules ensure` |
| Worker bootstrap | `services/temporal/run_workers.py` | consumes the workflows the schedule fires (see `temporal-config-driven`) |

Key facts observed across services:
- Registration is **idempotent**: `try create_schedule … except → handle.update(...)`.
- It runs as a **one-shot `Job`** (not a `CronJob`), after the worker Deployment is up.
- `ScheduleOverlapPolicy.SKIP` is the overlap convention; `pause_on_failure=True` is common.
- Interval specs (`ScheduleIntervalSpec(every=…, offset=…)`) are used for daily-ish cadences to avoid
  the UTC-cron timezone foot-gun; `time_zone` is generally not set, so cron expressions are UTC.
- Manual fires use `client.start_workflow(...)` or `handle.trigger()`.

## Cross-links

- `temporal-config-driven` — workflow/activity/worker mechanics, retries, idempotency, and the deeper
  schedule-registration reference.
- `containerization-and-deployment` — the multi-`MODE` entrypoint and Helm packaging.
- `kubernetes-workload-hardening` — securityContext/NetworkPolicy/resources for the CronJob pod.
- `observability-and-logging` — the cron execution metric and alerting on missing runs.
