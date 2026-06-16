---
name: review-scope
description: Use to review an existing scope document from a product / user-value perspective before the work is planned or built. Scores whether success criteria are user-testable, walks each user journey for missing states, flags internal-only language, re-checks priorities against user impact, and surfaces reversibility risk. Read-only — critiques and reports, never edits.
---

# Review Scope (product lens)

A read-only, product-side critique of a scope document — does it describe something that delivers
real, verifiable user value, with complete journeys and sane priorities? This is the product
counterpart to the engineering spec review (`em-reviewer`, `technical-architect`); it runs on the
output of the `scope` skill, before sprint planning.

**Risk tier:** low — read-only review, no changes. See `.claude/rules/risk-classification.md`.

## When to use
A scope doc exists (from `/scope` or written by hand) and you want a product gate on it before it
goes into a sprint plan. Drive it through the `pm-copilot` (or `staff-pm-reviewer`) persona.

## Required inputs
The scope document, and (helpful) the originating idea/ticket and the codebase for cross-checking.

## What to check
1. **User-testable success criteria.** Each criterion has a user-observable outcome — not a purely
   technical task. Score user-meaningful vs internal-only and flag the latter.
2. **Journey completeness.** For each user flow in scope, are the empty, loading, error, partial, and
   success states addressed? Missing states are product gaps.
3. **Internal-language leakage.** Flag internal system/field/service names and jargon that have leaked
   into user-facing descriptions — they signal the scope is written from the implementation, not the
   user.
4. **Priority vs user impact.** Re-check the ordering against how many users each item helps and how
   much; flag convenience-ordered or impact-inverted priorities.
5. **Reversibility.** Is there a user-facing way to recover if a change is wrong? Flag one-way doors.
6. **Verify against reality.** Cross-check coverage claims against the codebase; quote sources on
   conflicts.

## Quality gates
Every finding cites the scope section (and code, when verifying); must-fix and nice-to-have are kept
separate; no vague feedback; nothing is edited.

## Expected output
A review with a one-line verdict (Approve / Approve with fixes / Needs revision), **Issues to Fix**
and **Improvements Worth Considering** (separated), a user-journey coverage table, and the single
**main gap**. Rate findings **Critical / High / Medium / Low / Cosmetic** (`.claude/rules/quality-gates.md`);
not clear with any Critical/High/Medium open.

## Stop conditions
Stop and escalate (`.claude/rules/human-in-the-loop.md`) if user intent is genuinely ambiguous, if the
scope has no user-observable value at all, or if the request is to *rewrite* the scope (that's the
`scope` skill / a human's call, not this review).

## Example
```
/review-scope docs/planning/<slug>/scope.md
→ scores success criteria (user-testable?), walks journeys for missing states,
  flags internal jargon, re-checks priorities vs impact, checks reversibility
→ verdict + Issues to Fix / Improvements + journey-coverage table + main gap
```
