# kubectl Operations

A stack-derived skill for **operating Kubernetes workloads with `kubectl`** — the day-2 command surface
for the Deployments, `MODE`-dispatched pods, Temporal-worker Deployments, CronJobs/Jobs, and
Helm-rendered resources that the other skills define.

It is deliberately **operations-first**: the right context and namespace before anything, read before
write, dry-run before apply, events before guessing — then the full command surface for inspecting,
changing, debugging, rolling out, and rolling back.

## What this skill covers

- **The full command surface**, grouped by task: `get`/`describe`/`explain`/`api-resources`;
  `apply`/`create`/`edit`/`patch`/`set`/`replace`/`delete`; `logs`/`exec`/`port-forward`/`cp`/`debug`/
  `attach`/`proxy`; `rollout`/`scale`/`autoscale`; `events`/`top`; `label`/`annotate`; `config` (contexts
  & namespaces); `auth can-i`; `wait`/`diff`/`kustomize`; node `cordon`/`drain`/`uncordon`/`taint`.
- **Output formatting & filtering** — `-o wide/yaml/json/name/jsonpath/custom-columns/go-template`,
  `--sort-by`, label selectors (`-l`), field selectors, `--watch`, with copy-ready JSONPath recipes.
- **Day-2 debugging playbooks** — symptom → commands for CrashLoopBackOff, ImagePullBackOff,
  Pending/unschedulable, OOMKilled, a cron that didn't fire, and a Service with no endpoints.
- **Context/namespace/RBAC safety** — kubeconfig structure, switching clusters/namespaces safely,
  `auth can-i`, impersonation, and the `kubectx`/`kubens`/krew ecosystem.

## Relationship to other skills

- `cron-and-scheduled-jobs` — the CronJobs/Jobs you run, suspend, and trigger manually here.
- `kubernetes-workload-hardening` — the securityContext/NetworkPolicy/RBAC you *inspect* with kubectl.
- `containerization-and-deployment` — the images and `MODE` pods you operate.
- `temporal-config-driven` — operating the worker Deployments + the schedule-registration Job.
- `observability-and-logging` — `logs`/`events`/`top` complement the metrics and traces.

## How to use

Read `SKILL.md` for the safety model, the command map by task, and a triage skeleton. See `references/`
for the exhaustive command reference, output-formatting/JSONPath recipes, debugging playbooks, and
context/namespace/RBAC hygiene.

> Operations-focused and stack-agnostic in syntax (kubectl is universal); examples use generic
> placeholders (`my-service`, `my-namespace`, `registry.example.com`). **Not** wired into `claude-kit
> init`; install it deliberately. No internal cluster names, contexts, namespaces, or hosts.
