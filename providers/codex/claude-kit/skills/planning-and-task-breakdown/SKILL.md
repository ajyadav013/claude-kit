---
name: planning-and-task-breakdown
description: Breaks work into ordered tasks. Use when you have a spec and need implementable tasks, when a task feels too large to start, when you need to estimate scope, or when parallel work is possible.
---

# Planning and Task Breakdown

## Overview

Decompose work into small, verifiable tasks with explicit acceptance criteria. Good task breakdown is the difference between an agent that completes work reliably and one that produces a tangled mess. Every task should be small enough to implement, test, and verify in a single focused session.

## When to Use

- You have a spec and need to break it into implementable units
- A task feels too large or vague to start
- Work needs to be parallelized across multiple agents or sessions
- You need to communicate scope to a human
- The implementation order isn't obvious

**When NOT to use:** Single-file changes with obvious scope, or when the spec already contains well-defined tasks.

## The Planning Process

### Step 1: Enter Plan Mode

Before writing any code, operate in read-only mode:

- Read the spec and relevant codebase sections
- Identify existing patterns and conventions
- Map dependencies between components
- Note risks and unknowns

**Do NOT write code during planning.** The output is a plan document, not implementation.

### Step 2: Identify the Dependency Graph

Map what depends on what:

```
Database schema
    │
    ├── API models/types
    │       │
    │       ├── API endpoints
    │       │       │
    │       │       └── Frontend API client
    │       │               │
    │       │               └── UI components
    │       │
    │       └── Validation logic
    │
    └── Seed data / migrations
```

Implementation order follows the dependency graph bottom-up: build foundations first.

### Step 3: Slice Vertically

Instead of building all the database, then all the API, then all the UI — build one complete feature path at a time:

**Bad (horizontal slicing):**
```
Task 1: Build entire database schema
Task 2: Build all API endpoints
Task 3: Build all UI components
Task 4: Connect everything
```

**Good (vertical slicing):**
```
Task 1: User can create an account (schema + API + UI for registration)
Task 2: User can log in (auth schema + API + UI for login)
Task 3: User can create a task (task schema + API + UI for creation)
Task 4: User can view task list (query + API + UI for list view)
```

Each vertical slice delivers working, testable functionality.

### Step 4: Write Tasks

Each task follows this structure:

```markdown
## Task [N]: [Short descriptive title]

**Description:** One paragraph explaining what this task accomplishes.

**Acceptance criteria:**
- [ ] [Specific, testable condition]
- [ ] [Specific, testable condition]

**Verification:**
- [ ] Tests pass: run the project's test suite for this feature
- [ ] Build succeeds: run the project's build
- [ ] Manual check: [description of what to verify]

**Dependencies:** [Task numbers this depends on, or "None"]

**Files likely touched:**
- `path/to/file`
- `path/to/test`

**Estimated scope:** [Small: 1-2 files | Medium: 3-5 files | Large: 5+ files]
```

### Step 5: Order and Checkpoint

Arrange tasks so that:

1. Dependencies are satisfied (build foundation first)
2. Each task leaves the system in a working state
3. Verification checkpoints occur after every 2-3 tasks
4. High-risk tasks are early (fail fast)

Add explicit checkpoints:

```markdown
## Checkpoint: After Tasks 1-3
- [ ] All tests pass
- [ ] Application builds without errors
- [ ] Core user flow works end-to-end
- [ ] Review with human before proceeding
```

## Task Sizing Guidelines

| Size | Files | Scope | Example |
|------|-------|-------|---------|
| **XS** | 1 | Single function or config change | Add a validation rule |
| **S** | 1-2 | One component or endpoint | Add a new API endpoint |
| **M** | 3-5 | One feature slice | User registration flow |
| **L** | 5-8 | Multi-component feature | Search with filtering and pagination |
| **XL** | 8+ | **Too large — break it down further** | — |

If a task is L or larger, it should be broken into smaller tasks. An agent performs best on S and M tasks.

**When to break a task down further:**
- It would take more than one focused session (roughly 2+ hours of agent work)
- You cannot describe the acceptance criteria in 3 or fewer bullet points
- It touches two or more independent subsystems (e.g., auth and billing)
- You find yourself writing "and" in the task title (a sign it is two tasks)

## Plan Document Template

```markdown
# Implementation Plan: [Feature/Project Name]

## Overview
[One paragraph summary of what we're building]

## Architecture Decisions
- [Key decision 1 and rationale]
- [Key decision 2 and rationale]

## Task List

### Phase 1: Foundation
- [ ] Task 1: ...
- [ ] Task 2: ...

### Checkpoint: Foundation
- [ ] Tests pass, builds clean

### Phase 2: Core Features
- [ ] Task 3: ...
- [ ] Task 4: ...

### Checkpoint: Core Features
- [ ] End-to-end flow works

### Phase 3: Polish
- [ ] Task 5: ...
- [ ] Task 6: ...

### Checkpoint: Complete
- [ ] All acceptance criteria met
- [ ] Ready for review

## Risks and Mitigations
| Risk | Impact | Mitigation |
|------|--------|------------|
| [Risk] | [High/Med/Low] | [Strategy] |

## Open Questions
- [Question needing human input]
```

## Parallelization Opportunities

When multiple agents or sessions are available:

- **Safe to parallelize:** Independent feature slices, tests for already-implemented features, documentation
- **Must be sequential:** Database migrations, shared state changes, dependency chains
- **Needs coordination:** Features that share an API contract (define the contract first, then parallelize)

### Cross-service / multi-repo coordination

When a change spans two or more services or repositories, dependency-ordering inside one codebase is
not enough — the failure modes live *between* the services. Plan these explicitly:

- **Shared-resource ownership map.** List every resource touched across the service boundary (data
  stores, events/topics, shared APIs, caches) and name the **one** service that owns each. Changes to
  a shared resource are planned by its owner; everyone else is a consumer.
- **Distributed-systems hazard checklist.** For each cross-service interaction, check:
  - *Transaction safety* — there is no single transaction across services; what happens if step 2
    fails after step 1 committed? Define the compensation / cleanup.
  - *Cross-service TOCTOU* — a value checked in service A can change before service B acts on it.
  - *Event ordering & duplication* — consumers must tolerate out-of-order and at-least-once delivery
    (idempotency keys, not "it'll arrive once").
  - *Partial failure* — one service up, another down; degrade, retry, or fail cleanly — never corrupt.
- **Deployment / migration ordering.** Roll out in an order that is safe at every intermediate state:
  consumers that tolerate both old and new first, then producers; **additive before required**
  (add the new field/endpoint, deploy readers, *then* start writing it, *then* remove the old).
  See `deprecation-and-migration` for the expand/contract sequence.
- **Verification on both sides.** Each service gets its own acceptance checks *and* there is a
  cross-service check that exercises the end-to-end path through the boundary.

For mapping the services themselves before planning, see the comprehension-layer / cross-service
section in `context-engineering`; the integration gate at the join point is the `merge-reviewer`'s,
and the rollout sequencing is owned by `technical-architect` + `deprecation-and-migration`.

## Pushing the plan to a tracker

Once the breakdown is approved and you want it tracked, the `task-tracker-sync` skill mirrors it into
the project's configured issue tracker (GitHub / Linear / Jira) — one issue per task, dependencies
preserved, idempotent. It syncs an existing breakdown; it does not create one.

## Task-Type Prompt Templates

Not every task is a feature. The deliverables and the checks differ by *type* — tailor the task
write-up accordingly instead of using one generic shape:

| Type | Lead with | Type-specific deliverables |
|---|---|---|
| **Feature** | the user-facing outcome + acceptance criteria | spec slice, tests for the new behavior, docs |
| **Bug fix** | the reproduction + root cause (see `debugging-and-error-recovery`) | a regression test that fails without the fix, the minimal fix |
| **Refactor** | the invariant that must NOT change | characterization tests green before *and* after, no behavior delta |
| **Investigation** | the question to answer + what evidence settles it | a written finding with evidence, a recommendation, follow-up tasks |

Pick the matching template when writing each task so reviewers know what "done" means for it.

### Portable prompt (hand a task to another agent or LLM)

When a task will be executed by a *different* agent, session, or tool, emit a **self-contained,
copy-pasteable** prompt — assume the reader shares none of this conversation's context:

```
TASK: [one-line outcome]
CONTEXT: [the 3-5 facts needed — repo area, relevant files with paths, the convention to follow]
CONSTRAINTS: [what must hold — existing patterns, what not to touch, the boundary]
ACCEPTANCE: [the testable conditions that mean it's done]
VERIFY: [the exact commands to run + what a pass looks like]
```

A portable prompt that names its files, constraints, and verification turns a vague handoff into a
task the receiver can finish without a round-trip.

## Common Rationalizations

| Rationalization | Reality |
|---|---|
| "I'll figure it out as I go" | That's how you end up with a tangled mess and rework. 10 minutes of planning saves hours. |
| "The tasks are obvious" | Write them down anyway. Explicit tasks surface hidden dependencies and forgotten edge cases. |
| "Planning is overhead" | Planning is the task. Implementation without a plan is just typing. |
| "I can hold it all in my head" | Context windows are finite. Written plans survive session boundaries and compaction. |

## Red Flags

- Starting implementation without a written task list
- Tasks that say "implement the feature" without acceptance criteria
- No verification steps in the plan
- All tasks are XL-sized
- No checkpoints between tasks
- Dependency order isn't considered

## Verification

Before starting implementation, confirm:

- [ ] Every task has acceptance criteria
- [ ] Every task has a verification step
- [ ] Task dependencies are identified and ordered correctly
- [ ] No task touches more than ~5 files
- [ ] Checkpoints exist between major phases
- [ ] The human has reviewed and approved the plan
