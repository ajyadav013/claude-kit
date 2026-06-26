---
name: temporal-developer
description: Temporal fundamentals for durable execution across languages (Python, Go, TypeScript, Java, .NET, Ruby, Rust)—the workflow/activity/worker split, why workflows must be deterministic (history replay), signals/queries/updates, child workflows, saga/compensation, continue-as-new, timers, retry policies, cancellation/heartbeating, safe versioning of running workflows (patching, worker versioning), testing (time-skipping, replay tests, activity mocking), and the temporal CLI dev loop. Use when building or debugging Temporal workflows/activities/workers, fixing non-determinism errors, or deciding how to change running workflows safely. Do NOT use for this kit's config-driven worker-map / DAG-as-data orchestration engine (WORKER_MODE_CONFIG_MAP, _execute_dag, NODE_TYPE_MAP, schedule registration)—use temporal-config-driven for that.
---

# temporal-developer

Temporal **fundamentals**: how durable execution actually works, and the rules you must follow to
build correct workflows in any Temporal SDK. This is the conceptual layer underneath any
Temporal codebase — read it before writing workflow code, and reach for it when a workflow throws a
non-determinism error or you need to change code that running workflows depend on.

> **Sibling boundary.** `temporal-config-driven` covers *this kit's* specific config-driven
> architecture (mode→worker maps, the DAG-as-data interpreter, idempotency-via-`activity_id`,
> cron schedule registration). It **assumes** the fundamentals below. If you are wiring
> `WORKER_MODE_CONFIG_MAP`, `_execute_dag`, or `register_schedules`, use that skill. If you are
> learning *why workflows replay*, fixing determinism, versioning a live workflow, or working in a
> non-Python SDK, use **this** one. They are complementary, not duplicates.

## When to use

- Building your first workflow / activity / worker, or onboarding a new SDK language
- A workflow raised a **non-determinism / command-mismatch error** (see `references/determinism.md`)
- You need to change a workflow that has **in-flight executions** without breaking them (`references/versioning.md`)
- Writing tests for workflows — time-skipping, replay tests, activity mocking (`references/testing.md`)
- Choosing between **Signal, Query, and Update**, or adding child workflows / saga / continue-as-new
- Setting retry policies, timeouts, cancellation + heartbeating correctly
- Driving workflows from the `temporal` CLI during the dev loop (`references/cli.md`)

## The durable-execution model (the one idea everything rests on)

A Temporal **Workflow** is ordinary code whose execution is made *durable*: it survives process
crashes, deploys, and machine loss, and can sleep for months. It achieves this not by checkpointing
memory but by **replaying code against an Event History**.

```
Workflow code runs ──> emits Commands ──> Server records them as Events (the History)
Worker dies / cache evicts / long timer fires
Worker re-runs the SAME code from the top ──> for each Command, the SDK matches it to the
  recorded Event and feeds back the stored result ──> state is reconstructed, execution continues
```

Three consequences fall directly out of replay — internalize these:

1. **Workflow code must be deterministic.** Same inputs + same history ⇒ identical sequence of
   Commands, every replay. Wall-clock time, `random`, UUIDs, env vars, file/network I/O, and
   unordered map iteration all break this. → `references/determinism.md`.
2. **All non-determinism and all side effects belong in Activities.** An **Activity** is a plain
   function that runs *once*, outside replay, with at-least-once execution, automatic retries, and
   timeouts. Workflows *orchestrate*; Activities *do the I/O*. Because activities can run more than
   once, they must be **idempotent** (use an idempotency key).
3. **Changing workflow code can break replay.** New code that emits a different Command sequence than
   the recorded history fails open executions. Use **patching** or **worker versioning** to change
   live workflows safely. → `references/versioning.md`.

### Workflow vs Activity vs Worker

| Piece | What it is | Rules |
|-------|-----------|-------|
| **Workflow** | Orchestration logic; deterministic; replayed | No I/O, no clock/random/UUID except SDK-safe variants; only orchestrate |
| **Activity** | A unit of real work (I/O, compute); runs once per attempt | Must be idempotent; gets retries + timeouts; heartbeat if long-running |
| **Worker** | Process that polls a **task queue** and runs your workflow + activity code | All workers on a queue must run *identical* code (else replay mismatch) |

### Talking to a running workflow — Query vs Signal vs Update

| Operation | Modifies state? | Returns a result? | May block? | Use for |
|-----------|-----------------|-------------------|-----------|---------|
| **Query** | No | Yes | No | Read current state (read-only — never mutate) |
| **Signal** | Yes | No | Yes | Fire-and-forget input/mutation |
| **Update** | Yes | Yes | Yes | A mutation that must return a result |

> Mnemonic: **Query to peek, Signal to push, Update to pop.** Queries and update *validators* are
> strictly read-only — mutating in them is non-deterministic on replay.

## References

- [determinism.md](references/determinism.md) — replay mechanics, what workflow code may/may not do, SDK protection levels, recovery
- [versioning.md](references/versioning.md) — patching API, workflow-type versioning, worker (Build ID) versioning; when *not* to patch
- [testing.md](references/testing.md) — local/time-skipping environment, activity mocking, signal/query/update tests, replay tests
- [gotchas.md](references/gotchas.md) — the highest-leverage cross-language anti-patterns and their fixes
- [cli.md](references/cli.md) — `temporal server start-dev` + `workflow start/execute/signal/query/update` dev loop
- [languages.md](references/languages.md) — compact Python/Go/TypeScript starters + pointer to upstream per-language depth (Java/.NET/Ruby/Rust + AI integrations)

## Upstream (authoritative, full 7-language depth)

These references are **re-derived concisely** in this kit's idiom from the official, MIT-licensed
**`temporalio/skill-temporal-developer`**. For exhaustive per-language guides (Python · TypeScript ·
Go · Java · .NET · Ruby · Rust), integrations (OpenAI Agents SDK, Google ADK, …), and ops-grade
material, go to the source — it is the authority and is kept current by Temporal:

- Repo: https://github.com/temporalio/skill-temporal-developer
- Docs: https://docs.temporal.io

When upstream and these notes disagree, trust upstream and update this skill.
