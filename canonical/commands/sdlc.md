---
schema_version: 1
id: sdlc
description: Run the full autonomous SDLC pipeline on a task via the orchestrator
aliases:
- sdlc
invocation: explicit
capabilities:
- filesystem.read
- filesystem.search
- shell
- delegation
- workflow.ledger
request_input:
  mode: required
  hint: <feature or task description>
pause_for_human: []
references:
- rule://mandatory-workflow
- rule://quality-gates
- state://stack-catalog
---

Run the {{kit:cli}} autonomous SDLC pipeline for:

> {{request}}

Invoke the **`sdlc`** skill with that request — it is the single source of the pipeline logic
(profile-aware gate selection, orchestrator delegation, and the phase sequence). Pass `{{request}}`
through as the task.

If the `sdlc` skill is not available in this session, fall back to driving the pipeline yourself per
`rule://mandatory-workflow`: delegate to the `orchestrator` agent, read the active gate set
from `state://stack-catalog` (default to the standard pipeline if absent), and
enforce every active gate with the severity model in `rule://quality-gates`.
