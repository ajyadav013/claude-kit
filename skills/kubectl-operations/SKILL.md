---
name: kubectl-operations
description: Operating Kubernetes workloads with kubectl — the full command surface (get/describe/explain, apply/create/edit/patch, logs/exec/port-forward/cp/debug/events/top, rollout/scale/autoscale, config/contexts/namespaces, auth can-i, jobs & cronjobs, node cordon/drain) plus output formatting (-o jsonpath/custom-columns/go-template), label/field selectors, dry-run + diff, and day-2 debugging playbooks (CrashLoopBackOff, ImagePullBackOff, Pending, OOMKilled, a cron that didn't fire, a Service with no endpoints). Context/namespace safety first. Use when running kubectl against a cluster, inspecting or changing a Deployment/Job/CronJob/StatefulSet/pod, tailing logs, exec-ing into a container, port-forwarding, rolling out or rolling back, checking RBAC, formatting kubectl output, or debugging why a workload is unhealthy.
---

# kubectl Operations

`kubectl` is the operational interface to the workloads the other skills define — the Deployments,
`MODE`-dispatched pods, Temporal-worker Deployments, CronJobs, and Helm-rendered resources. This skill
is the day-2 command surface: how to inspect, change, debug, roll out, and roll back, and how to do it
**safely** (the right context and namespace first, read before write, dry-run before apply).

> Companion skills: `cron-and-scheduled-jobs` (the CronJobs/Jobs you operate here),
> `kubernetes-workload-hardening` (the securityContext/RBAC you inspect with `auth can-i` / `-o yaml`),
> `containerization-and-deployment` (the images + `MODE` pods you're running), `temporal-config-driven`
> (the worker Deployments + schedule-registration Job), and `observability-and-logging` (`logs`/`events`/
> `top` complement metrics/traces).

## When to use

- Running **any** kubectl command against a cluster
- Inspecting a **Deployment / StatefulSet / DaemonSet / Job / CronJob / Pod / Service / ConfigMap / Secret**
- **Tailing logs**, **exec-ing** into a container, **port-forwarding**, copying files
- **Rolling out / restarting / rolling back** a Deployment; **scaling** a workload
- **Formatting** kubectl output (jsonpath, custom-columns, go-template) or filtering with selectors
- Checking **RBAC** (`auth can-i`) or impersonating (`--as`)
- **Debugging** an unhealthy workload (crash loops, image pull errors, pending pods, OOM, missing endpoints)
- Operating **CronJobs/Jobs** — manual run, suspend, inspecting a cron that didn't fire

## Safety first: context and namespace

The single most common kubectl accident is running the right command against the **wrong cluster or
namespace**. Make the preamble a habit:

```bash
kubectl config current-context          # WHICH cluster am I about to touch?
kubectl config get-contexts             # list all; * marks current
kubectl config use-context <ctx>        # switch cluster
kubectl config set-context --current --namespace=<ns>   # pin a default namespace
kubectl -n <ns> get pods                # or scope per-command with -n
```

- **Read before you write.** `get`/`describe`/`logs` are safe; `apply`/`edit`/`patch`/`scale`
  change state. Confirm the context line before any write.
- **Never hand-edit production resources** that a GitOps/Helm pipeline owns — `kubectl edit`/`patch` on a
  Helm-managed object is overwritten on the next deploy and causes drift. Change the source (values/
  manifests) and redeploy. Use `edit`/`patch` only for break-glass, and reconcile after.
- **Dry-run + diff before apply** (see below). Prefer `--dry-run=server` (the API validates it).
- Set a **distinct prompt/color per cluster** (e.g. via `kube-ps1`) so prod is visually obvious.
- **`kubectl delete` is disabled here.** This kit ships a `guard-kubectl-delete` guardrail that blocks
  `kubectl delete` from an agent session — a delete is far too easy to misfire against the wrong
  namespace or cluster. To remove or replace a workload, change the Git/Helm source and let the pipeline
  reconcile; to stop one now, `kubectl scale --replicas=0`; to undo a bad rollout, `kubectl rollout undo`.
  Read-only checks like `kubectl auth can-i delete …` still work.

## Core conventions — command map by task

| Task | Command(s) |
|---|---|
| List / inspect | `get`, `describe`, `explain`, `api-resources` |
| See full spec | `get <res> <name> -o yaml` |
| Create / change | `apply -f`, `create`, `edit`, `patch`, `set`, `replace` (delete is guarded — see Safety) |
| Preview a change | `apply -f x.yaml --dry-run=server -o yaml`, `diff -f x.yaml` |
| Logs | `logs`, `logs -f`, `logs --previous`, `logs -l app=x --all-containers` |
| Get a shell / run a command | `exec -it <pod> -- sh`, `run`, `debug` |
| Reach a pod/service locally | `port-forward`, `proxy` |
| Copy files | `cp` |
| Roll out / back | `rollout status`, `rollout restart`, `rollout undo`, `rollout history` |
| Scale | `scale`, `autoscale` |
| Events (why?) | `events`, `get events --sort-by=.lastTimestamp`, `describe` |
| Resource usage | `top pod`, `top node` (needs metrics-server) |
| Labels / annotations | `label`, `annotate` |
| Access checks | `auth can-i`, `auth can-i --list`, `--as` |
| Jobs / CronJobs | `create job --from=cronjob/<name>`, `get/describe job`, patch `suspend` |
| Node ops | `cordon`, `drain`, `uncordon`, `taint` |
| Wait for a condition | `wait --for=condition=Ready pod -l app=x` |

### Inspecting resources

```bash
kubectl get pods                                   # current namespace
kubectl get pods -A                                # all namespaces (--all-namespaces)
kubectl get pods -o wide                           # + node, IP
kubectl get deploy,svc,cm -l app=my-service        # multiple kinds, label-filtered
kubectl get pod my-pod -o yaml                     # full live spec
kubectl describe pod my-pod                        # events + state + why (read the Events section)
kubectl explain deployment.spec.template.spec      # schema/docs for any field
kubectl api-resources                              # every resource kind + shortname + apiGroup
kubectl get events --sort-by=.lastTimestamp        # recent cluster events
kubectl get pods -A | grep -i crashloop            # quick text filter (prefer -l / --field-selector / jsonpath when you can)
```

### Applying & changing (with a preview)

```bash
kubectl diff -f deploy.yaml                         # what WOULD change vs live
kubectl apply -f deploy.yaml --dry-run=server -o yaml   # validate w/o applying
kubectl apply -f deploy.yaml                        # declarative create/update (preferred)
kubectl apply -k ./overlays/prod                   # kustomize
kubectl set image deploy/my-service app=registry.example.com/app:v2   # targeted image bump
kubectl scale deploy/my-service --replicas=3
kubectl patch deploy/my-service --type=merge -p '{"spec":{"replicas":3}}'
# To REMOVE a workload, change the Git/Helm source and reconcile, or stop it with `scale --replicas=0`.
# `kubectl delete` is blocked by the guard-kubectl-delete guardrail (see "Safety first: context and namespace").
```

Prefer **`apply`** (declarative) over imperative `create`/`replace` for anything you manage as files.

### Debugging a workload

```bash
kubectl logs -f deploy/my-service                   # follow logs of a deployment's pod
kubectl logs my-pod -c sidecar --previous           # previous (crashed) container's logs
kubectl logs -l app=my-service --all-containers --tail=200
kubectl exec -it my-pod -- sh                       # shell in (bash/sh)
kubectl debug -it my-pod --image=busybox --target=app   # ephemeral debug container (distroless pods)
kubectl port-forward svc/my-service 8080:80         # reach the service at localhost:8080
kubectl cp my-pod:/var/log/app.log ./app.log        # copy out
kubectl top pod -l app=my-service                   # live CPU/memory (metrics-server)
```

### Rollouts & scaling

```bash
kubectl rollout status deploy/my-service            # block until the rollout completes/fails
kubectl rollout restart deploy/my-service           # re-roll pods (e.g. to pick up a changed Secret)
kubectl rollout history deploy/my-service           # revisions
kubectl rollout undo deploy/my-service              # roll back to the previous revision
kubectl rollout undo deploy/my-service --to-revision=3
kubectl autoscale deploy/my-service --min=2 --max=10 --cpu=70%   # --cpu takes 70% or 500m; add --memory=70%
```

### Jobs, CronJobs & one-off runs

```bash
kubectl get cronjob                                 # SCHEDULE, SUSPEND, LAST SCHEDULE
kubectl get jobs                                    # COMPLETIONS, DURATION
kubectl create job my-job-manual --from=cronjob/my-cron   # run a CronJob's job NOW (ad hoc)
kubectl patch cronjob/my-cron -p '{"spec":{"suspend":true}}'   # pause a CronJob
kubectl logs job/my-job-manual                      # logs of the job's pod
kubectl logs -l job-name=my-job-manual --tail=-1    # all pods of the job
```

> A cron that "didn't run": check `get cronjob` (is `SUSPEND` true? what's `LAST SCHEDULE`?), then
> `describe cronjob/<name>` (Events: "missed start"), then the Job/pod logs. See
> `cron-and-scheduled-jobs` for the scheduling model.

### RBAC & access checks

```bash
kubectl auth can-i create deployments -n my-namespace      # yes/no for ME
kubectl auth can-i --list -n my-namespace                  # everything I can do here
kubectl auth can-i get secrets --as=system:serviceaccount:my-namespace:my-sa   # check a SA
```

### Node operations (cluster admin)

```bash
kubectl get nodes -o wide
kubectl cordon <node>          # mark unschedulable
kubectl drain <node> --ignore-daemonsets --delete-emptydir-data   # evict pods for maintenance
kubectl uncordon <node>        # schedulable again
kubectl top node               # node CPU/memory
```

## Skeleton / example — triaging a failed rollout

```bash
# 0. Confirm WHERE you are.
kubectl config current-context && kubectl config view --minify -o jsonpath='{..namespace}{"\n"}'

# 1. What's broken?
kubectl get pods -l app=my-service                  # STATUS: CrashLoopBackOff / ImagePullBackOff / Pending
kubectl rollout status deploy/my-service --timeout=60s   # fails fast if the roll is stuck

# 2. Why? Events first, then logs.
kubectl describe pod -l app=my-service              # Events at the bottom say the real reason
kubectl logs -l app=my-service --previous --tail=100   # last words of the crashed container

# 3. Mitigate (roll back is usually fastest).
kubectl rollout undo deploy/my-service
kubectl rollout status deploy/my-service

# 4. If config-related: confirm the env/secret the pod actually got.
kubectl get pod <pod> -o jsonpath='{.spec.containers[0].env[*].name}{"\n"}'
```

## Anti-patterns to avoid

- **Running a write command without checking the context/namespace first** — the classic "oops, that was
  prod" incident. Always confirm `current-context` before `apply`/`scale`/`rollout`.
- **`kubectl edit`/`patch` on a Helm/GitOps-managed resource** — it's silently reverted on next deploy
  and creates drift. Change the source and redeploy; reserve live edits for break-glass.
- **Reaching for `kubectl delete`** — it's intentionally excluded from this skill and blocked by the
  `guard-kubectl-delete` guardrail (deletes from an agent session misfire too easily). To stop a
  workload, `scale --replicas=0`; to roll back, `rollout undo`; to remove a resource, delete it from the
  Git/Helm source and let the pipeline reconcile.
- **`get` when you needed `describe`** — `get` shows status; the *reason* (failed mounts, scheduling,
  probe failures, image pull) is in `describe` Events and `kubectl events`.
- **Forgetting `--previous`** on a crash-looping pod — the live container may be too young to have logs;
  the crash is in the previous instance.
- **`-o yaml` / `get secret` dumped to a shared terminal** — Secret values are base64 (not encrypted);
  redacting matters. Don't paste them into tickets/logs.
- **`kubectl apply` of a file that was previously `create`d imperatively** — ownership/last-applied
  mismatch. Pick declarative (`apply`) and stay there.
- **`--force --grace-period=0` as a habit** — force-deleting pods can leave StatefulSet/PV state
  inconsistent. Use it only when you understand the consequence.
- **No `--dry-run`/`diff` before applying to prod** — preview server-side first.
- **Long imperative one-liners instead of a manifest** — not reproducible or reviewable; for anything
  lasting, write YAML and `apply` it.

## References

- [command-reference.md](./references/command-reference.md) — The full command surface, grouped
  (inspect, create/change, debug, rollout/scale, config, jobs, nodes, advanced), with the flags that
  matter for each.
- [output-formats-and-selectors.md](./references/output-formats-and-selectors.md) — `-o
  wide/yaml/json/name/jsonpath/custom-columns/go-template`, `--sort-by`, label selectors (`-l`), field
  selectors (`--field-selector`), `--watch`, and ready-to-use JSONPath recipes.
- [debugging-playbooks.md](./references/debugging-playbooks.md) — Symptom → command playbooks:
  CrashLoopBackOff, ImagePullBackOff, Pending/unschedulable, OOMKilled, a cron that didn't fire, a
  Service with no endpoints, config/secret problems.
- [context-namespace-rbac.md](./references/context-namespace-rbac.md) — kubeconfig structure, contexts &
  namespaces, current-context safety, `auth can-i`, impersonation, and `kubectx`/`kubens`/krew.
- [repo-evidence.md](./references/repo-evidence.md) — Representative operational patterns described
  generically.
