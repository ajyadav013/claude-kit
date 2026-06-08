---
description: Run the full autonomous SDLC pipeline on a task via the orchestrator
argument-hint: "<feature or task description>"
allowed-tools: Skill, Agent, Read, Glob, Grep, TaskCreate, TaskGet, TaskList, TaskUpdate
---

Run the claude-kit autonomous SDLC pipeline for:

> $ARGUMENTS

Invoke the **`sdlc`** skill with that request — it is the single source of the pipeline logic
(profile-aware gate selection, orchestrator delegation, and the phase sequence). Pass `$ARGUMENTS`
through as the task.

If the `sdlc` skill is not available in this session, fall back to driving the pipeline yourself per
`.claude/rules/mandatory-workflow.md`: delegate to the `orchestrator` agent, read the active gate set
from `.claude/config/stack-catalog.snapshot.yaml` (default to the standard pipeline if absent), and
enforce every active gate with the severity model in `.claude/rules/quality-gates.md`.
