# Goal Setting & Monitoring

An agent that can't say *what done looks like* and *whether it's getting there* drifts. Every task
runs against **measurable success criteria** that are recorded up front, **monitored** as work
proceeds, and used to **prioritize** what to do next. This rule turns "I produced output" into "I met
a defined, checkable goal" — and decides what to work on first.

> Adapted from *Agentic Design Patterns* (A. Gulli), Ch. 11 "Goal Setting and Monitoring" and Ch. 20
> "Prioritization." Concepts paraphrased for this kit.

The feature spec already *defines* acceptance criteria (`spec-doc-writer`, `.claude/rules/mandatory-workflow.md`
stage 1c) and `acceptance-reviewer` checks delivery against them. This rule makes those criteria
**measurable + actively monitored + prioritized** across the run, including for bug fixes and
fast-track work that never produce a full spec.

## 1. Set measurable success criteria

Before doing the work, state the goal so success is **verifiable, not vibes**. A good criterion is:

- **Specific** — names the observable behavior/output, not a feeling ("returns 404 with an error body
  for a missing id," not "handles errors well").
- **Measurable** — has a check that can pass or fail (a test, a command exit code, a metric threshold,
  a reviewable artifact).
- **Bounded** — clear scope and out-of-scope; what is explicitly *not* being done.

Record them in `.claude/CONTINUITY.md` (and for features, they live in the spec). If you cannot make a
criterion measurable, that ambiguity is a human decision point — see
`.claude/rules/human-in-the-loop.md`.

## 2. Monitor progress against them

- **Track, don't assume.** As stages complete, check actual results against the criteria — the RARV
  **Verify** step (`.claude/rules/rarv-cycle.md`) is where each criterion gets proven.
- **Watch the process signals** in `.claude/rules/quality-gates.md` (gate first-pass rate, fix
  iterations, defect-loop cycles). A degrading trend is an early warning, not a gate.
- **Detect drift.** If work is diverging from the criteria, the criteria turned out wrong, or scope is
  creeping, **stop and correct** — revise the plan, re-scope with the human, or escalate. Don't push a
  growing diff toward a goal that no longer fits.

## 3. Prioritize what to do next

When multiple tasks/stories/findings compete, rank by:

| Criterion | Ask |
|-----------|-----|
| **Urgency** | Is something blocked, broken, or time-sensitive right now? |
| **Importance** | How much does this move the actual goal / success criteria? |
| **Dependencies** | Does other work require this first? Do the unblockers before the blocked. |
| **Risk** | Tackle the riskiest/most-uncertain piece early, while there's room to change course. |

**Dynamic re-prioritization:** re-rank as conditions change — a new blocker, a failed gate, a human
answer that reshapes scope. The order chosen at the start is a hypothesis, not a contract. The
`story-planner` orders parallelizable stories up front; this rule keeps that order honest as the run
proceeds (and the `planning-and-task-breakdown`, `triage`, and `sprint` skills apply the same criteria
at backlog/sprint scope).

## Rules

1. **No work without a checkable goal.** Even a fast-track fix states what "fixed" means and how it's
   proven.
2. **Criteria live in working memory.** Keep them in `.claude/CONTINUITY.md` so they survive
   compaction and the next turn measures against the same bar.
3. **Re-prioritize on new information; don't sunk-cost a stale plan.**
4. **Goal met = every criterion verified**, not "the code is written." Hand off against the criteria.

## Relationship to other rules

- **`.claude/rules/rarv-cycle.md`** — Verify proves each criterion; this rule defines the criteria.
- **`.claude/rules/continuity.md`** — where criteria + progress are recorded and monitored.
- **`.claude/rules/quality-gates.md`** — process signals = the monitoring instrumentation.
- **`.claude/rules/human-in-the-loop.md`** — unmeasurable/ambiguous criteria and major re-scoping
  escalate here.
