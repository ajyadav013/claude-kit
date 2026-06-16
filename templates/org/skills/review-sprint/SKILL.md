---
name: review-sprint
description: Use after a sprint completes to review the whole deliverable inventory from an engineering-management perspective — cross-reference every planned deliverable against the sprint plan AND the scope doc for existence, non-triviality, and correctness; verify acceptance criteria are actually met; and sweep for introduced tech debt and CI gaps. Read-only — audits and reports, never edits.
---

# Review Sprint (engineering-management retrospective)

A read-only, end-of-sprint audit of **everything the sprint claims to have delivered**, at
deliverable-inventory granularity. Unlike `acceptance-reviewer` (which gates a single change's
acceptance) this looks across the *whole* sprint: did every planned deliverable actually land, is it
real (not a stub), is it correct, and does the set still match the original scope? Driven by the
`em-reviewer` persona.

**Risk tier:** low — read-only review, no changes. See `.claude/rules/risk-classification.md`.

## When to use
A sprint is marked complete (or about to be archived) and you want an EM-level verification before it
counts as done — typically before `/archive-sprint`.

## Required inputs
The sprint plan (with its deliverable list), the scope document it derives from, and the codebase +
test/CI results for verification.

## What to check
1. **Deliverable inventory — for each planned deliverable:**
   - **Exists** — the file/endpoint/component is actually present (verify with Glob/Grep, don't trust
     the report).
   - **Non-trivial** — it does the thing, not a placeholder/stub/`TODO`.
   - **Correct** — it behaves as the deliverable describes (read it).
2. **Acceptance criteria.** Check each acceptance criterion explicitly — met, not just claimed. A
   "green" claim must cite the real check + output (`.claude/rules/quality-gates.md` §2.5).
3. **Scope conflicts.** Cross-reference plan vs scope: deliverables that drifted from scope, scope
   items silently dropped, counts/classifications that disagree between documents (quote both).
4. **Introduced tech debt.** What shortcuts were taken? Are they documented? Flag undocumented debt.
5. **CI / checks sweep.** Did the test/lint/build actually run and pass for this sprint? Flag
   `continue-on-error`-style masking, skipped suites, or unrun checks reported as passing.

## Quality gates
Every finding cites a file/section + concrete action; must-fix (Issues to Fix) vs nice-to-have
(Improvements) kept separate; no vague feedback; nothing edited.

## Expected output
A verdict (Approve / Approve with fixes / Needs revision), separated **Issues to Fix** /
**Improvements**, a **deliverable-inventory table** (deliverable · exists? · non-trivial? · correct? ·
acceptance met?), and the main gap. Severities **Critical / High / Medium / Low / Cosmetic**
(`.claude/rules/quality-gates.md`); not clear with any Critical/High/Medium open.

## Stop conditions
Stop and escalate (`.claude/rules/human-in-the-loop.md`) if the sprint plan or scope doc is missing
(there's nothing to audit against), or if asked to *fix* the gaps (route to the engineering lane /
Defect Loop — this skill only reports).

## Example
```
/review-sprint docs/planning/<slug>/sprint.md
→ enumerates planned deliverables, verifies each exists/non-trivial/correct in the code
→ checks each acceptance criterion, cross-references plan vs scope, sweeps tech debt + CI
→ verdict + Issues to Fix / Improvements + deliverable-inventory table + main gap
```
