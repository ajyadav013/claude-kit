# Contexts, namespaces & RBAC (reference)

The most expensive kubectl mistakes are *targeting* mistakes — right command, wrong cluster or
namespace. This is the hygiene that prevents them, plus how to check what you (or a ServiceAccount) are
allowed to do.

## kubeconfig structure

kubectl reads `~/.kube/config` (override with `$KUBECONFIG`, which can be a `:`-joined list that gets
merged). A kubeconfig has three lists tied together by **contexts**:

- **clusters** — API server URL + CA.
- **users** — credentials (client cert, token, exec plugin like `gke-gcloud-auth-plugin` / `aws eks
  get-token`).
- **contexts** — a named `(cluster, user, namespace)` triple. The **current-context** is what every
  command uses unless you pass `--context`.

```bash
kubectl config view                       # full (merged) config
kubectl config view --minify              # just the current context's slice
kubectl config get-clusters
kubectl config get-users
kubectl config get-contexts               # the triples; * marks current
```

## Switching cluster and namespace safely

```bash
kubectl config current-context                                   # confirm BEFORE any write
kubectl config use-context <ctx>                                 # switch the (cluster,user,ns) bundle
kubectl config set-context --current --namespace=<ns>           # change default ns for current context
kubectl -n <ns> <cmd>                                            # or scope a single command
kubectl --context=<ctx> -n <ns> get pods                        # fully explicit, no state change
```

Habits that prevent accidents:
- **Confirm `current-context` before every `apply`/`scale`/`rollout`/`drain`.**
- Prefer **explicit `--context`/`-n`** in scripts and runbooks over relying on the active context.
- Give prod a **visually distinct shell** (`kube-ps1`, a red prompt) so it's obvious.
- Keep prod and non-prod in **separate kubeconfig files** and switch via `$KUBECONFIG` when you want hard
  isolation.

## kubectx / kubens / krew

Quality-of-life tooling (install deliberately; not required):

```bash
kubectx                 # list/switch contexts interactively
kubectx my-cluster      # switch
kubens                  # list/switch namespaces
kubens my-namespace     # set default namespace for current context

# krew = the kubectl plugin manager
kubectl krew install ctx ns ns-tree neat
kubectl plugin list     # everything kubectl found on PATH as kubectl-*
```

## RBAC: what am I (or a SA) allowed to do?

```bash
kubectl auth whoami                                          # who the API thinks I am (1.26+)
kubectl auth can-i create deployments -n my-namespace        # yes / no
kubectl auth can-i '*' '*'                                   # am I effectively admin?
kubectl auth can-i --list -n my-namespace                    # full matrix of my permissions here
kubectl auth can-i update deployments --as=jane@example.com   # impersonate a user
kubectl auth can-i get secrets \
  --as=system:serviceaccount:my-namespace:my-sa              # impersonate a ServiceAccount
```

`--as` / `--as-group` impersonation is the right way to **test** a Role/RoleBinding before a workload
relies on it (requires impersonate permission yourself). Pair with `kubernetes-workload-hardening` for
designing least-privilege Roles/ServiceAccounts.

## Inspecting RBAC objects

```bash
kubectl get roles,rolebindings -n my-namespace
kubectl get clusterroles,clusterrolebindings
kubectl describe rolebinding <rb> -n my-namespace            # who is bound to what
kubectl get sa -n my-namespace                               # ServiceAccounts
```

## Read-only / least-blast-radius habits

- Default to read commands (`get`/`describe`/`logs`); they can't change state.
- For exploration on an unfamiliar cluster, a **view-only context** (a user bound only to `view`) makes
  destructive commands impossible.
- `--dry-run=server` lets you validate a write against the API **without** performing it.
- Scope every **write** to a set you've verified — run `get -l ...` first and eyeball the list before any
  mutating command (`label`, `annotate`, `rollout restart`). `kubectl delete` is disabled by the
  `guard-kubectl-delete` guardrail; remove resources via the Git/Helm source instead.
