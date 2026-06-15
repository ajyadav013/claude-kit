# Feature spec: <name>

> Produced before implementation (see `.claude/rules/mandatory-workflow.md`). Keep it explicit
> enough to review. Give each requirement a stable id: the **Story Planner** (workflow stage 1f)
> maps every acceptance criterion below to an implementation story, so coverage gaps and scope
> creep are caught on paper, not mid-build.

## Problem / motivation
What user need or problem does this address? Why now?

## Goals / non-goals
- Goals:
- Non-goals:

## Requirements & acceptance criteria
Each requirement gets a stable id (R1, R2, …) so stories and tests can trace back to it. Every
requirement needs at least one acceptance criterion phrased as a checkable Given/When/Then.

- **R1** — <requirement>
  - [ ] Given … when … then …
- **R2** — <requirement>
  - [ ] Given … when … then …

## Assumptions
Defaults chosen where the request was silent — state them so they can be corrected *before* coding,
not discovered after. (Open, still-undecided questions belong under "Rollout / open questions", not
here; an assumption is a decision you are proceeding on unless told otherwise.)

- …

## Scope
Affected modules / files / surfaces. Independent work streams (e.g. backend lane, frontend lane).

## Design
Approach, data model / API contract changes, key decisions (link ADRs for significant ones).

## Risks & constraints
Deadline, compatibility, security, performance, compliance.

## Test plan (summary)
What unit / integration / e2e coverage proves each requirement's acceptance criteria (reference the
R-ids). Detail lives in test-plan.md.

## Rollout / open questions
