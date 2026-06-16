---
name: review-sprint-plan
description: Use to review a finished sprint plan from a product / user-value perspective before execution starts. Checks that tasks are ordered by user impact, that nothing in the scope was dropped, that acceptance criteria are user-testable, and that sequencing and rollback are sound. Read-only — critiques and reports, never edits.
---

# Review Sprint Plan (product lens)

A read-only product gate over a completed sprint plan, *before* agents start executing. The
engineering reviewers check the plan is buildable; this checks it builds the right things in the right
order for users. Runs on the output of the `sprint` skill; pairs with the engineering plan review in
`em-reviewer`.

**Risk tier:** low — read-only review, no changes. See `.claude/rules/risk-classification.md`.

## When to use
A sprint plan exists and you want a product sign-off on priority, completeness, and sequencing before
kickoff. Drive it through `pm-copilot` (or `staff-pm-reviewer`).

## Required inputs
The sprint plan, the scope document it derives from, and the codebase for cross-checking.

## What to check
1. **Priority order = user impact.** The plan's task/deliverable order should front-load the highest
   user-impact work; flag sequencing that front-loads low-impact or convenience work.
2. **Nothing dropped from scope.** Cross-reference every scope item against the plan — flag scope
   items with no corresponding task (a silent drop) and tasks that map to nothing in scope (creep).
3. **User-testable acceptance criteria.** Each deliverable's acceptance criteria are verifiable by a
   user, not just "code merged."
4. **Sequencing & dependencies for the user.** Does each checkpoint leave the product in a
   user-coherent state, or does it ship a half-flow (e.g. create without the ability to view)?
5. **Rollback readiness.** Is there a user-facing recovery path if a deliverable ships wrong?
6. **Verify against reality.** Check the plan's claims against the scope and codebase; quote both on
   conflict.

## Quality gates
Every finding cites the plan/scope section; must-fix vs nice-to-have separated; no vague feedback;
nothing edited.

## Expected output
A verdict (Approve / Approve with fixes / Needs revision), separated **Issues to Fix** and
**Improvements**, a **scope → plan coverage table** (each scope item: covered? / gap), and the main
gap. Severities **Critical / High / Medium / Low / Cosmetic** (`.claude/rules/quality-gates.md`);
not clear with any Critical/High/Medium open.

## Stop conditions
Stop and escalate if the plan and scope fundamentally disagree (route back to scoping), or if asked to
*rewrite* the plan (that's the `sprint` skill).

## Example
```
/review-sprint-plan docs/planning/<slug>/sprint.md
→ checks priority vs impact, scope→plan coverage, user-testable criteria,
  sequencing leaves coherent states, rollback readiness
→ verdict + Issues to Fix / Improvements + coverage table + main gap
```
