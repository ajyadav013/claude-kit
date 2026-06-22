# Cron & Scheduled Jobs

A stack-derived skill for **scheduled / recurring jobs** as this stack actually runs them — across the
two mechanisms it uses and where each one keeps the schedule.

The same business need ("run this every night") is implemented two opposite ways here, and the
confusing part is *where the schedule lives*:

- **Kubernetes CronJob** — the schedule is **Helm config** (`Crons.<name>.Schedule`); the cluster fires
  a one-shot pod that runs the shared image in `MODE=cron` and dispatches a single named job from a
  Python registry, then exits. There is no in-app scheduler.
- **Temporal Schedule** — the schedule is a **server-owned object** registered by a one-shot deploy step;
  Temporal fires a workflow, with overlap policy, pause-on-failure, catch-up, and manual triggers.

## What this skill covers

- **k8s CronJob route**: the Helm `Crons` values block → the rendered `CronJob` and its defaults
  (`concurrencyPolicy: Forbid`, history limits, `restartPolicy: Never`, `ttlSecondsAfterFinished`); the
  `MODE=cron` + `CRON_JOB` entrypoint dispatch; the one-shot runner; simple vs rich cron registries;
  the execution metric and retry; and the chart's missing `timeZone`/`startingDeadlineSeconds`.
- **Temporal Schedule route**: `cron_expressions` vs `ScheduleIntervalSpec` (and why intervals dodge the
  UTC-cron foot-gun); `ScheduleOverlapPolicy.SKIP` + `pause_on_failure`; idempotent create-or-update
  registration; the one-shot k8s `Job` that registers a schedule; manual trigger and lifecycle helpers.
- **Choosing between them** and the cross-cutting operational concerns (concurrency, timezone, history,
  missed runs, suspend vs pause, observability).

## Relationship to other skills

- `temporal-config-driven` — the **workflow/activity/worker** mechanics (retries, idempotency, worker
  bootstrap) and the deeper schedule-registration reference. This skill owns the **scheduling /
  recurrence dimension** and the **CronJob-vs-Temporal decision**, and cross-links rather than repeats.
- `containerization-and-deployment` — the multi-`MODE` entrypoint and Helm packaging that the CronJob
  route builds on.
- `kubernetes-workload-hardening` — securityContext / NetworkPolicy / resources for the CronJob pod.
- `observability-and-logging` — the `record_cron_job_executed` metric and alerting on missing runs.

## How to use

Read `SKILL.md` for the conventions, the two-mechanism decision table, and both copy-ready skeletons.
See `references/` for the field-by-field Helm/CronJob detail, the Temporal schedule patterns, and the
operational decision matrix.

> Stack-derived: encodes a real Python/FastAPI + Kubernetes + Temporal deployment topology. **Not**
> wired into `claude-kit init`; install it deliberately. All names (service, registry, namespace, job
> names, hosts) are generic placeholders — no internal services, hosts, project IDs, or cluster names.
