# 01 — Request

The raw human ask that started the run (what a user typed into `/sdlc`):

> Let users mark a to-do task as complete. There should be a checkbox next to each task in the list;
> clicking it should toggle the task's done state and persist it. Completed tasks should show as
> struck-through. Don't let it break the existing task list.

That's it — an informal request. Everything downstream (spec, stories, gates) is derived from this by
the pipeline; the human did not write a spec. The orchestrator classified this as a **two-lane**
change (backend: persist + endpoint; frontend: checkbox + state) on the **`standard`** profile.
