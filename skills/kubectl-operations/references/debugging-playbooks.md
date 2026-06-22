# kubectl debugging playbooks (reference)

Symptom → the commands that find the root cause, fastest path first. The universal first move for *any*
unhealthy resource is **`describe` (read the Events) then `logs --previous`** — `get` shows the symptom,
`describe`/`events` show the cause.

```bash
kubectl get pods -l app=my-service                 # the symptom (STATUS column)
kubectl describe pod <pod>                          # the cause (Events section at the bottom)
kubectl get events --sort-by=.lastTimestamp -n my-namespace
```

## CrashLoopBackOff (container starts then dies, repeatedly)

```bash
kubectl logs <pod> --previous --tail=200           # the crash is in the PREVIOUS instance
kubectl describe pod <pod>                          # Last State: Terminated → Reason/Exit Code
```
- Exit code **1/2** → app error (read `--previous` logs). **137** → SIGKILL/OOM (see OOMKilled).
  **139** → segfault. **143** → SIGTERM (often a too-aggressive liveness probe).
- Liveness probe killing a slow starter → add/extend a `startupProbe` (see
  `kubernetes-workload-hardening`).
- Missing config/secret at boot → see "Config/Secret problems" below.

## ImagePullBackOff / ErrImagePull

```bash
kubectl describe pod <pod>    # Events: "Failed to pull image ... unauthorized / not found / no such host"
```
- **not found / manifest unknown** → wrong tag/digest. Check `get deploy/<d> -o jsonpath='{..image}'`.
- **unauthorized** → missing/expired `imagePullSecrets`, or the ServiceAccount lacks it.
- **no such host / timeout** → registry unreachable from the node (NetworkPolicy/egress/DNS).

## Pending (pod won't schedule)

```bash
kubectl describe pod <pod>    # Events: "0/N nodes are available: ..." gives the exact reason
kubectl get nodes -o wide
kubectl top nodes             # capacity headroom
```
- **Insufficient cpu/memory** → lower requests or scale the cluster.
- **node(s) had untolerated taint** → add a toleration or pick another node pool.
- **didn't match node selector/affinity** → fix `nodeSelector`/affinity.
- **unbound PersistentVolumeClaim** → `kubectl get pvc`; the PVC is Pending (no matching PV/StorageClass).

## OOMKilled (container exceeded its memory limit)

```bash
kubectl describe pod <pod>    # Last State: Terminated, Reason: OOMKilled
kubectl top pod <pod> --containers
```
- Raise the memory `limit`, or fix the leak/batch size. Requests too low can also get a pod evicted under
  node pressure (`describe node` → "evicted").

## A CronJob didn't run

```bash
kubectl get cronjob my-cron                          # SUSPEND true? LAST SCHEDULE long ago?
kubectl describe cronjob my-cron                      # Events: "missed start" / "already active"
kubectl get jobs -l app=my-service --sort-by=.metadata.creationTimestamp
kubectl logs job/<job> --tail=-1                      # the run's logs (if a Job was created)
```
- `SUSPEND: True` → it's paused (`patch cronjob ... suspend:false` to resume).
- `concurrencyPolicy: Forbid` + a still-running prior Job → this fire was skipped by design.
- No Job at all + "missed start" → the controller missed the window (no catch-up). See
  `cron-and-scheduled-jobs` for the scheduling model and the `timeZone`/`startingDeadlineSeconds` gaps.
- Run it now to test: `kubectl create job my-cron-manual --from=cronjob/my-cron`.

## A Service has no endpoints (clients get connection refused)

```bash
kubectl get endpoints my-service        # or: get endpointslices -l kubernetes.io/service-name=my-service
kubectl describe svc my-service         # Selector + Endpoints
kubectl get pods -l <the-svc-selector> -o wide   # do any pods MATCH the selector and are Ready?
```
- **No endpoints** → the Service `selector` matches no Ready pods (label mismatch, or pods failing
  readiness). Fix labels or the readiness probe.
- **Endpoints exist but unreachable** → wrong `targetPort`, or a NetworkPolicy is blocking
  (`kubernetes-workload-hardening`). Test in-cluster: `kubectl run tmp --rm -it --image=busybox -- \
  wget -qO- my-service:80`.

## Can't reach a pod/service to test it

```bash
kubectl port-forward svc/my-service 8080:80      # then curl localhost:8080
kubectl port-forward deploy/my-service 8080:8080
kubectl run curl --rm -it --image=curlimages/curl -- sh   # an in-cluster client
```

## Config / Secret problems (env not what you expect)

```bash
kubectl get pod <pod> -o jsonpath='{.spec.containers[0].env[*].name}{"\n"}'    # which env names exist
kubectl describe pod <pod>           # Events: "couldn't find key X in ConfigMap/Secret"
kubectl get cm app-config -o yaml
kubectl get secret app-secrets -o jsonpath='{.data.KEY}' | base64 -d   # mind exposure
```
- Changed a ConfigMap/Secret but the pod still has the old value → env/volume values are injected at pod
  start; **`kubectl rollout restart deploy/<d>`** to pick them up (unless you use a reloader).

## Exec into a distroless / no-shell container

```bash
kubectl debug -it <pod> --image=busybox --target=<container>   # ephemeral container shares namespaces
kubectl debug node/<node> -it --image=busybox                  # debug the node itself
```

## Node went bad / draining for maintenance

```bash
kubectl get nodes
kubectl describe node <node>          # Conditions: MemoryPressure/DiskPressure/Ready
kubectl cordon <node>                 # stop new scheduling
kubectl drain <node> --ignore-daemonsets --delete-emptydir-data
# ...maintenance...
kubectl uncordon <node>
```

## General triage order (memorize)

1. `get` (symptom) → 2. `describe` / `events` (cause) → 3. `logs --previous` (app's last words) →
4. mitigate (`rollout undo` / `scale` / `delete pod` to respawn) → 5. fix the source and redeploy.
