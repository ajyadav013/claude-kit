---
name: sprint
description: Turn a scoped backlog item into a sprint plan, broken into parallelisable tasks for agent teams. Use when asked to plan a sprint, break work down into tasks, or work out what can run in parallel.
argument-hint: [backlog item number]
disable-model-invocation: true
---

Generate a sprint plan for backlog item #$ARGUMENTS.

## Steps

1. **Find the scope doc**: Look for the scope document in `docs/planning/*/scope.md` that corresponds to backlog item #$ARGUMENTS. If no scope doc exists, tell the user to run `/scope $ARGUMENTS` first.

2. **Read the scope doc**: Understand all the component changes, data changes, route changes, and state changes.

3. **Read the sprint template**: Read the [sprint template](sprint-template.md) for the output structure.

4. **Break into tasks**: Create a detailed task breakdown:
   - Each task should be small enough for one agent to complete in a focused session
   - Tasks should have clear inputs and outputs
   - Include the specific files to modify/create
   - Order tasks by dependency (data models before business logic, business logic before interfaces, etc.)

5. **Read post-sprint learnings**: Read `docs/reference/post-sprint-learnings.md` for execution heuristics from previous sprints. Apply relevant learnings to the plan.

6. **Design parallelization**: Identify which tasks can run concurrently:
   - Data/schema changes and scaffolding can usually run in parallel
   - Module implementation can overlap if they don't share state
   - Tasks modifying shared files (routing configuration, shared state stores, dependency injection configuration) should be sequential on one agent
   - For multi-module features: build one module first to establish patterns, then parallelize the rest

7. **Write the sprint plan**: Save to `docs/planning/{slug}/sprint.md` next to the scope doc. Include:
   - Numbered deliverables with acceptance criteria
   - Task tables organized by work stream (e.g., backend, frontend, integration, infrastructure)
   - Parallelization diagram showing agent assignments
   - Verification checklist

8. **Suggest team composition**: Based on the tasks, recommend:
   - How many agents to spawn and what type (e.g., backend-dev, frontend-dev, full-stack-dev)
   - Task assignment per agent
   - Plan extra tasks for faster-finishing agents (investigation, docs, design validation)

9. **Output the plan**: Show the user the sprint plan summary and ask for approval before they kick off execution.

## Guidelines

- Tasks should be atomic — one clear objective per task
- Always include a "verify integration" task at the end
- Don't create tasks for things that are already done
- Identify which work streams are independent (backend API, frontend UI, data migrations, infrastructure) and can run in parallel
- Agent type for implementation: match to the stack (backend-dev for API work, frontend-dev for UI work, full-stack-dev for cross-cutting features)
- For design-sensitive changes, suggest running a design-review agent after implementation
- For coordinated changes (e.g., new data model + new API endpoint + new UI component + new route), ensure all changes are in the same sprint

## Agent Capacity & Replacement Planning

Plan agent capacity *proactively*, not only reactively when one hits its context limit. An agent's
output quality decays as its context fills (see the `context-engineering` skill and the
context-budget guidance in `.claude/rules/agent-resilience.md`):

- **Budget work per agent.** Estimate the tasks (and the test/verification load) each agent will
  carry, and plan to **rotate in a fresh agent after a bounded number of tasks** rather than running
  one agent until it degrades. Calibrate the number to your task sizes — don't hardcode a magic count.
- **Reserve a fresh agent for final verification.** The end-of-sprint integration/verification pass
  should run on an agent that has *not* been saturated by implementation, so its judgment is sharp.
- **Hand off cleanly on replacement.** Before retiring an agent, capture its state to working memory
  (`.claude/CONTINUITY.md`) and check `git status` so nothing in-flight is lost; the replacement
  resumes from that snapshot (reload, don't re-run — see `.claude/rules/continuity.md`).
- **Shut down once, don't block.** When an agent's work is done, retire it cleanly; don't leave idle
  agents holding the lane or block the sprint waiting on one that has nothing left to do.

## Post-Sprint Report

**When to write**: After the verification checklist passes and all tasks are complete (or explicitly descoped), the team lead must fill in the Sprint Report section of the sprint plan before archiving.

**Run the checks — don't assume them.** "Verification passes" must mean the project's tests, linter,
and build were **actually executed for this sprint** and their real results recorded — not inferred
from the fact that tasks were marked done. Run them, capture the real pass/fail (and counts), and if
anything failed, the sprint is not done. A reported verdict must cite the command and its output —
see `.claude/rules/quality-gates.md` §2.5.

**What to capture**:
1. **Results table** — each deliverable with target vs actual vs status (actual = observed, not planned)
2. **Metrics** — tasks planned/completed, regressions found, and the real test/lint/build outcome
3. **What went well** — patterns that worked, velocity wins, risk catches
4. **What went wrong** — regressions, scope errors, agent issues, blockers
5. **Learnings** — actionable lessons for future sprints (check existing learnings in `docs/reference/post-sprint-learnings.md` to avoid duplicates)
6. **Unresolved / carry-over** — issues discovered but not fixed, with enough detail to act on immediately in the next sprint

**After writing the report**: Add any new learnings to `docs/reference/post-sprint-learnings.md`. Then run `/archive-sprint` to move docs to archive and update the backlog.
