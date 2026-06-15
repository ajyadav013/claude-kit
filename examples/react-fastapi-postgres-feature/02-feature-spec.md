# 02 — Feature spec  *(synthetic instance of `templates/artifacts/feature-spec.md`)*

> Produced by `spec-doc-writer`; reviewed by the senior devs, `technical-architect`, and `em-reviewer`.
> Gate: **spec-complete** (numbered requirements + acceptance criteria) → **em-approved**.

## Feature: Mark a task complete

### Summary
Add a persisted "done" state to a task, a `PATCH /tasks/{id}` endpoint to toggle it, and a checkbox in
the task list that reflects and updates it.

### Requirements
- **R1** — A task has a boolean `done` state, defaulting to `false`, persisted in Postgres.
- **R2** — `PATCH /tasks/{id}` accepts `{ "done": <bool> }` and returns the updated task.
- **R3** — The task list renders a checkbox per task bound to `done`; toggling it calls the endpoint.
- **R4** — A completed task renders struck-through.
- **R5** — The existing list/create/delete behavior is unchanged (no regression).

### Acceptance criteria  *(Given / When / Then)*
- **AC1 (R1,R2)** — Given a task with `done=false`, when `PATCH /tasks/{id}` is called with
  `{"done": true}`, then it returns `200` with the task `done=true` and the row is updated.
- **AC2 (R2)** — Given a non-existent id, when `PATCH /tasks/{id}` is called, then it returns `404`.
- **AC3 (R2)** — Given an invalid body (`done` missing or non-boolean), then it returns `422`.
- **AC4 (R3,R4)** — Given the list, when the user clicks a task's checkbox, then the checkbox toggles,
  the task persists, and a completed task shows struck-through.
- **AC5 (R5)** — Given the existing list/create/delete flows, all prior tests still pass.

### Assumptions
- The `tasks` table already exists; this adds one nullable-then-defaulted column (see the migration).
- No auth/permission change — toggling is allowed for any caller the list already serves.

### Out of scope
Bulk complete, undo history, per-user filtering.
