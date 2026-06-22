# Representative operational patterns (generic)

kubectl syntax is universal; what's *stack-specific* is which workloads you operate and the runbooks
around them. These are the recurring kubectl touchpoints for this stack's resources, described
generically (no internal cluster, context, namespace, or host names).

## Where kubectl shows up in this stack

| Workload (from other skills) | Typical kubectl operations |
|---|---|
| API/server Deployment (`MODE=server`) | `rollout status`, `rollout restart`, `logs -f deploy/<svc>`, `scale`, `port-forward svc/<svc>` |
| Consumer/worker Deployment (`MODE=consumer`/`worker`) | `logs -l app=<svc>,role=consumer`, `top pod`, `rollout restart` after a config change |
| Temporal worker Deployment (`MODE=temporal_worker`) | `logs`, `rollout restart`; confirm it's up *before* running the schedule-registration Job |
| Schedule-registration Job (`kind: Job`, runs `schedules ensure`) | `kubectl logs job/<job>`, `kubectl get job`, delete + re-apply to re-run |
| CronJob (`Crons` block → `MODE=cron`) | `get cronjob`, `describe cronjob`, `create job --from=cronjob/<c>`, `patch ... suspend` |
| ConfigMap / Secret | `get cm -o yaml`, `get secret -o jsonpath` (decode carefully), `rollout restart` to pick up changes |
| Ingress / Service | `get ing`, `get endpoints`, `describe svc` when clients can't connect |

## Recurring runbook snippets (generic)

```bash
# Pick up a changed ConfigMap/Secret (env is injected at pod start):
kubectl rollout restart deploy/my-service && kubectl rollout status deploy/my-service

# Manually fire a CronJob's job to test it (without waiting for the schedule):
kubectl create job my-cron-manual --from=cronjob/my-cron
kubectl logs -f job/my-cron-manual

# Confirm a worker is registered before running the Temporal schedule-registration Job:
kubectl get deploy my-service-worker
kubectl logs deploy/my-service-worker --tail=50
kubectl apply -f deploy/schedule-job.yaml      # the one-shot Job (see cron-and-scheduled-jobs)

# Roll back a bad deploy fast, then investigate:
kubectl rollout undo deploy/my-service
kubectl logs -l app=my-service --previous --tail=200
```

## Conventions observed

- **Declarative everywhere.** Resources come from Helm-rendered manifests; live `edit`/`patch` is
  break-glass only, because the next deploy overwrites it (drift). Change values/manifests and redeploy.
- **One image, many roles.** The same image runs as server/consumer/worker/cron via `MODE`; when
  operating, target by **label** (`-l app=<svc>` or a `role`/component label) rather than pod name,
  because pod names are ephemeral.
- **Restart to reload config.** Changing a ConfigMap/Secret does not restart pods; `rollout restart` is
  the standard reload.
- **Jobs vs CronJobs.** The schedule-registration step is a one-shot `Job`; the recurring app tasks are
  `CronJob`s. Operate them differently (a Job is re-run by delete+re-apply; a CronJob by
  `create job --from=cronjob` for an ad-hoc fire).

## Cross-links

- `cron-and-scheduled-jobs` — the CronJob/Job model these commands operate.
- `kubernetes-workload-hardening` — the securityContext/NetworkPolicy/RBAC you inspect and the
  least-privilege Roles you test with `auth can-i --as`.
- `containerization-and-deployment` — the images and `MODE` dispatch behind the pods.
- `temporal-config-driven` — the worker Deployments and the schedule-registration Job.
- `observability-and-logging` — `logs`/`events`/`top` alongside metrics, traces, and structured logs.
