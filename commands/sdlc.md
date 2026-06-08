---
description: Run the full autonomous SDLC pipeline on a task via the orchestrator
argument-hint: "<feature or task description>"
allowed-tools: Agent, Read, Glob, Grep, TaskCreate, TaskGet, TaskList, TaskUpdate
---

Run the claude-kit autonomous SDLC pipeline for the following request:

> $ARGUMENTS

Delegate to the **`orchestrator`** agent (spawn it via the Agent tool). If that agent is not
available in this session, act as the Orchestrator yourself.

Drive the pipeline strictly per `.claude/rules/mandatory-workflow.md`:

1. **Classify** the work — bug fix vs. feature; single stream vs. parallel streams; fast-track
   (< 5 files) vs. full pipeline.
2. **Plan the stages** and write the initial state to `.claude/CONTINUITY.md`.
3. **Run the phases with their gates** — Spec & Dev docs → EM approval → Developer → Code Review →
   Unit + E2E tests → Test-coverage gate (blind review + Devil's Advocate) → Security Clear →
   DevOps/Observability (if applicable) → PR.
4. **Enforce every gate** using the severity model in `.claude/rules/quality-gates.md`
   (zero Critical/High/Medium to pass) and the RARV cycle in `.claude/rules/rarv-cycle.md`.
5. **Stop and ask the user** at the points the workflow requires (ambiguous requirements, spec
   confirmation, project-wide changes, deploy environment).

Begin by confirming your classification and the stage plan, then proceed.
