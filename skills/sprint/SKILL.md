---
name: sprint
description: Generate a sprint plan from a scoped backlog item, breaking it into parallelizable tasks for agent teams.
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

## Post-Sprint Report

**When to write**: After the verification checklist passes and all tasks are complete (or explicitly descoped), the team lead must fill in the Sprint Report section of the sprint plan before archiving.

**What to capture**:
1. **Results table** — each deliverable with target vs actual vs status
2. **Metrics** — tasks planned/completed, regressions found
3. **What went well** — patterns that worked, velocity wins, risk catches
4. **What went wrong** — regressions, scope errors, agent issues, blockers
5. **Learnings** — actionable lessons for future sprints (check existing learnings in `docs/reference/post-sprint-learnings.md` to avoid duplicates)
6. **Unresolved / carry-over** — issues discovered but not fixed, with enough detail to act on immediately in the next sprint

**After writing the report**: Add any new learnings to `docs/reference/post-sprint-learnings.md`. Then run `/archive-sprint` to move docs to archive and update the backlog.
