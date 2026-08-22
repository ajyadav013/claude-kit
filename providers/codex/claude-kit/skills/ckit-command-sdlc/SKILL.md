---
name: ckit-command-sdlc
description: Run the full evidence-gated SDLC pipeline on a task
---

Run the ckit autonomous SDLC pipeline for:

> the invocation request

Invoke the **`sdlc` skill provided by this plugin** with that request — it is the single source of the pipeline logic
(profile-aware gate selection, orchestrator delegation, and the phase sequence). Pass `the invocation request`
through as the task.

If the `sdlc` skill is not available in this session, fall back to driving the pipeline yourself per
`mandatory-workflow`: delegate to the project's `orchestrator` persona when one is installed; otherwise orchestrate in the current session, read the active gate set
from `.ckit/config/stack-catalog.snapshot.yaml` (default to the standard pipeline if absent), and
enforce every active gate with the severity model in `quality-gates`.
