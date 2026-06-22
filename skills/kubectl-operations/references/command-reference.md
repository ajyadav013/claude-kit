# kubectl command reference (grouped)

The full `kubectl` surface, grouped the way `kubectl --help` groups it, with the flags that matter.
Global flags that apply almost everywhere: `-n/--namespace`, `-A/--all-namespaces`, `-l/--selector`,
`-o/--output`, `--context`, `--dry-run=client|server|none`, `-f/--filename`, `--field-selector`,
`-v=N` (verbosity; `-v=6`..`9` shows the API requests).

Discover anything: `kubectl <cmd> --help`, `kubectl api-resources`, `kubectl explain <res>.<field>`.

## Basic — create & inspect

| Command | What it does | Common flags / examples |
|---|---|---|
| `get` | List/print resources | `-o wide\|yaml\|json\|name`, `-l app=x`, `-A`, `-w` (watch), `--sort-by`, `--show-labels` |
| `describe` | Human-readable detail + **Events** | `describe pod <p>`, `describe deploy/<d>` |
| `explain` | Schema/docs for a field | `explain pod.spec.containers`, `--recursive` |
| `create` | Imperatively create a resource | `create deployment`, `create configmap`, `create secret generic`, `create job --from=cronjob/<c>` |
| `run` | Start a one-off pod | `run tmp --image=busybox -it --rm -- sh`; scaffold a manifest: `run app --image=img --restart=Never --dry-run=client -o yaml` |
| `expose` | Make a Service from a workload | `expose deploy/my-service --port=80 --target-port=8080` |
| `set` | Change a specific field | `set image deploy/d app=img:v2`, `set env deploy/d KEY=val`, `set resources`, `set serviceaccount deploy/d my-sa`, `set selector`, `set subject` |
| `edit` | Open a live resource in `$EDITOR` | `edit deploy/d` (break-glass; avoid on GitOps-managed objects) |
| `delete` | Remove resources | `delete -f x.yaml`, `delete pod <p>`, `--grace-period`, `--force` (last resort) |

`create` imperative generators are handy with `--dry-run=client -o yaml` to scaffold a manifest:

```bash
kubectl create deployment my-service --image=registry.example.com/app:v1 \
  --dry-run=client -o yaml > deploy.yaml         # scaffold, then edit + apply
kubectl create configmap app-config --from-file=./config/ --dry-run=client -o yaml
kubectl create secret generic app-secrets --from-literal=API_KEY=REDACTED --dry-run=client -o yaml
```

## Deploy — rollout, scale, autoscale

| Command | What it does | Examples |
|---|---|---|
| `rollout status` | Wait for a rollout to finish | `rollout status deploy/d --timeout=120s` |
| `rollout restart` | Re-roll pods (pick up changed Secret/CM) | `rollout restart deploy/d` |
| `rollout history` | List revisions | `rollout history deploy/d`, `--revision=3` |
| `rollout undo` | Roll back | `rollout undo deploy/d`, `--to-revision=2` |
| `rollout pause/resume` | Freeze/continue a rollout | `rollout pause deploy/d` |
| `scale` | Set replica count | `scale deploy/d --replicas=5`, `--current-replicas=3` (guard) |
| `autoscale` | Create an HPA | `autoscale deploy/d --min=2 --max=10 --cpu=70%` (also `--cpu=500m`, `--memory=70%`) |

## Troubleshooting & debugging

| Command | What it does | Examples |
|---|---|---|
| `logs` | Container logs | `logs -f deploy/d`, `logs <p> -c <ctr> --previous`, `logs -l app=x --all-containers --tail=200 --since=1h` |
| `exec` | Run a command in a container | `exec -it <p> -- sh`, `exec <p> -c <ctr> -- env` |
| `attach` | Attach to a running process's stdio | `attach -it <p>` |
| `debug` | Ephemeral/debug container or node | `debug -it <p> --image=busybox --target=<ctr>`; `debug node/<n> -it --image=busybox` |
| `port-forward` | Forward local port → pod/svc | `port-forward svc/my-service 8080:80`, `port-forward <p> 5432` |
| `proxy` | Local proxy to the API server | `proxy --port=8001` then `curl localhost:8001/api/...` |
| `cp` | Copy files in/out | `cp <p>:/path ./local`, `cp ./local <p>:/path` (needs `tar` in the container) |
| `events` | Cluster events (1.23+) | `events --for pod/<p>`, `events -A --sort-by=.lastTimestamp` |
| `top` | Live CPU/memory (metrics-server) | `top pod -l app=x --containers`, `top node` |
| `auth` | Access review | `auth can-i create pods`, `auth can-i --list`, `auth whoami` |

## Advanced — apply, diff, patch, replace, wait, kustomize

| Command | What it does | Examples |
|---|---|---|
| `apply` | Declarative create/update (preferred) | `apply -f dir/`, `apply -k overlay/`, `--server-side`, `--prune` (careful) |
| `diff` | Show what `apply` would change | `diff -f x.yaml` |
| `patch` | Patch a field | `patch deploy/d --type=merge -p '{"spec":{"replicas":3}}'`; types: `strategic` (default), `merge`, `json` |
| `replace` | Replace a whole resource | `replace -f x.yaml`, `--force` (delete+recreate) |
| `wait` | Block on a condition | `wait --for=condition=Ready pod -l app=x --timeout=120s`, `--for=delete`, `--for=jsonpath=...` |
| `kustomize` | Render kustomize output | `kustomize ./overlay` (or `apply -k`) |

> `apply --prune` deletes live resources no longer present in the applied set — powerful but dangerous if
> the label scope is wrong. Always `--dry-run=server` first and scope it (`apply --prune -l app=x -f dir/`).

## Settings — labels, annotations, completion

| Command | Examples |
|---|---|
| `label` | `label pod <p> tier=backend`, `label pod <p> tier-` (remove), `--overwrite` |
| `annotate` | `annotate deploy/d kubernetes.io/change-cause="bump to v2"` |
| `completion` | `source <(kubectl completion bash)` (also `zsh`, `fish`, `powershell`) |

## Cluster management & nodes

| Command | Examples |
|---|---|
| `cluster-info` | `cluster-info`, `cluster-info dump` (verbose) |
| `cordon`/`uncordon` | `cordon <node>` / `uncordon <node>` (toggle schedulable) |
| `drain` | `drain <node> --ignore-daemonsets --delete-emptydir-data` (evict for maintenance) |
| `taint` | `taint nodes <node> key=value:NoSchedule`, remove with trailing `-` |
| `certificate` | `certificate approve/deny <csr>` |
| `top node` | node CPU/memory |

## Cluster discovery & client

| Command | Examples |
|---|---|
| `api-resources` | `api-resources` (kinds, shortnames, apiGroup, namespaced?), `--namespaced=true` |
| `api-versions` | list served `group/version`s |
| `version` | `version` (client+server), `version -o yaml` |
| `cluster-info` | API endpoint + core addons |
| `plugin list` | installed kubectl plugins (krew & PATH) |
| `kuberc` | manage `kuberc` preferences files (default aliases/flags; newer, rarely needed) |

## `kubectl config` (kubeconfig / contexts)

```bash
kubectl config get-contexts                          # list contexts (* = current)
kubectl config current-context                       # the active one
kubectl config use-context <ctx>                     # switch cluster/user/ns bundle
kubectl config set-context --current --namespace=<ns>   # change default namespace
kubectl config view --minify                         # the effective config for current context
kubectl config view --minify -o jsonpath='{..namespace}'   # current default namespace
kubectl config rename-context <old> <new>
kubectl config delete-context <ctx>
```

See `context-namespace-rbac.md` for kubeconfig structure and safe multi-cluster habits.

## Resource shortnames (save typing)

`po` Pods · `deploy` Deployments · `rs` ReplicaSets · `svc` Services · `ns` Namespaces · `cm`
ConfigMaps · `ing` Ingresses · `sa` ServiceAccounts · `pvc` PersistentVolumeClaims · `pv`
PersistentVolumes · `sts` StatefulSets · `ds` DaemonSets · `cj` CronJobs · `hpa`
HorizontalPodAutoscalers · `no` Nodes · `ep` Endpoints · `netpol` NetworkPolicies. Full list:
`kubectl api-resources`.

## Targeting forms

Most commands accept either `<type> <name>` or `<type>/<name>`, and a controller stands in for its pods
where it makes sense:

```bash
kubectl logs deploy/my-service          # logs from a pod of the Deployment
kubectl exec -it deploy/my-service -- sh
kubectl get rs,po -l app=my-service     # multiple kinds at once
kubectl delete deploy my-service        # delete the controller (and its pods)
```
