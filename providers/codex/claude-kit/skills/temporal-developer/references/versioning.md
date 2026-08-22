# Versioning (changing workflows that have in-flight executions)

When workers restart after a deploy, they resume open workflows by **replaying** them. If the new
code emits a different Command sequence than history recorded, replay fails:

```
Recorded history:   activity_a → activity_b
New code on replay: activity_a → activity_c   ← mismatch → NondeterminismError
```

Three approaches, pick by blast radius.

## 1. Patching API — branch code by patch state

Branch on whether a workflow was started before or after a change:

```
if patched("add-fraud-check"):
    # new path — new workflows + new replays
else:
    # old path — replays of pre-patch workflows
```

Three-phase lifecycle: **patch in** (both paths) → **deprecate** (mark deprecated once old
executions drain; keep marker for history compat) → **remove** (delete the patch when no deprecated
executions remain).

**Use it for** anything that changes the Command sequence: adding/removing/reordering activities or
child workflows, or changing *which* activity is called.

**Do NOT patch for** (these are already replay-safe; patching just adds noise):
- changing an activity's *implementation* (activities aren't replayed),
- changing arguments passed to an activity/child,
- changing a retry policy or a timer duration,
- adding new signal/query/update handlers (additive is safe),
- bug fixes that don't alter the Command sequence.

Use descriptive patch IDs (`add-fraud-check`, not `patch-1`).

## 2. Workflow-type versioning — a new type for incompatible change

Create `OrderWorkflowV2` alongside `OrderWorkflow`; register both; start new executions on V2; let
old ones drain; then remove the old type. Best for **major rewrites** or when patching would get
unmanageable, and when you want clean separation.

## 3. Worker versioning — deployment-level control via Build IDs

Pin code versions at the deployment level. Multiple worker versions run side by side; each workflow
is associated with a Build ID. Two behaviors:

- **PINNED** — a workflow stays on its original worker version. Best for short workflows, when
  consistency matters, and for the simplest dev experience.
- **AUTO_UPGRADE** — workflows may move to newer versions. Best for long-running (weeks/months)
  workflows that need fixes mid-flight — but it **still requires patching** for version transitions.

**Upgrade on Continue-as-New** (Public Preview — tell the user if you use it): a long-running PINNED
workflow that uses Continue-as-New can adopt a newer worker version at the CaN boundary *without*
patching. Each run stays pinned; when the server signals a new Target Version (detected via a
per-workflow `WorkflowInfo` flag, checked inside a Workflow Task), the next CaN run starts on it.
Caveats: sleeping workflows don't auto-upgrade (signal them to wake and check); the old run's input
must be compatible with the new definition; PINNED-only.

## Choosing

| Scenario | Approach |
|----------|----------|
| Small change, few running workflows | Patching API |
| Major rewrite | Workflow-type versioning |
| Many short workflows, frequent deploys | Worker versioning (PINNED) |
| Long-running + uses Continue-as-New | Worker versioning (PINNED) + upgrade-on-CaN |
| Long-running, no Continue-as-New | Worker versioning (AUTO_UPGRADE) + patching |
| Quick fix, can wait | Let workflows complete, then deploy |

## Best practices

1. Check for **open executions** before removing old code paths.
2. Deploy incrementally: **patch → deprecate → remove**.
3. **Test replay compatibility** (`testing.md`) before deploying any workflow change.
4. During *development* (never prod) you can terminate stale executions:
   `temporal workflow terminate --workflow-id <id>`.

See `references/{language}/versioning.md` upstream for SDK-specific `patched()` / Build ID calls.
