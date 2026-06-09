# Product to Code

The path from intent to buildable work: turn ideas, tickets, PRDs, and customer feedback into specs,
user stories, acceptance criteria, implementation plans, and reviewable tasks.

**Primary teams:** Product · Founders · **Default risk:** medium · **Manifest:** `pack.yaml`

## Who uses it
Product managers, founders, and anyone shaping work before it reaches engineering — clarifying a fuzzy
idea, splitting a PRD into stories, or converting a raw prompt into a scoped, safe task. The personas
here **plan and delegate**; they never write or run code.

## Role → component mapping
This pack bundles components that already ship with claude-kit (reused, not duplicated) plus a few added
by the org layer. It does not introduce competing agents.

| Need | Use |
|------|-----|
| Refine a rough idea into something concrete | `/idea-refine` → `pm-copilot` |
| Get interviewed to surface requirements | `/interview-me` (see `ambiguity-resolution.md`) |
| Turn an idea into a feature brief | `/feature-from-idea` → `pm-copilot` → `spec-doc-writer` |
| Write a spec from a PRD | `/spec-driven-development` → `spec-doc-writer` |
| Split a PRD into user stories | `/spec-driven-development` + `story-planner` (the `/prd-to-stories` flow) |
| Break stories into tasks | `/planning-and-task-breakdown` → `story-planner` |
| Bound what's in / out of scope | `/scope` |
| Sketch UI behavior for a story | `ui-designer` (design spec only) |
| Convert a raw prompt into a safe, scoped task | `/prompt-to-safe-task` (see `prompt-to-task-conversion.md`) |
| Coordinate the hand-off to engineering | `orchestrator` agent |
| Decide how risky a change is | `risk-classifier` agent (`risk-classification.md`) |

## Rules it leans on
`ambiguity-resolution.md`, `prompt-to-task-conversion.md`, `non-engineer-safe-coding.md`,
`goal-setting-and-monitoring.md` (plus `risk-classification.md` for tiering).

## Hooks it expects
`warn-large-edits` — flags oversized changes so a plan-only flow never silently balloons into a big edit.

## Examples
```
/feature-from-idea "Let users export their report as a shareable link"   # → spec + stories + tasks
/prd-to-stories Onboarding checklist PRD   # → spec-driven-development + story-planner (stories + acceptance criteria)
/prompt-to-safe-task "tidy up the settings copy"   # → scoped, approval-gated task
```

## Autonomy & risk
Operates under the repo's autonomy level. These personas **plan and delegate only** — actual building is
handed to engineering with explicit acceptance criteria. Anything touching a sensitive area (auth,
payments, secrets, production data, migrations, infrastructure) is at least **high** risk: get human
approval and route it through the engineering review chain before any code is written
(`risk-classification.md`).
