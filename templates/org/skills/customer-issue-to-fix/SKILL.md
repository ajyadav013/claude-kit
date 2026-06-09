---
name: customer-issue-to-fix
description: Use when a support engineer has a customer or support issue and wants it turned into a reproducible bug report, the likely code paths identified, a fix proposal, and a validation checklist — routed through triage, debugging, and the engineering pipeline with a human approval gate before any code is changed. Reproduce → locate → propose → validate.
---

# Customer Issue to Fix

Turn a customer or support ticket into a reproducible bug report, the suspected code paths, a fix
proposal, and a validation checklist — routed into the engineering pipeline without the requester
needing to write code.

**Risk tier:** medium by default; **high/restricted** if the issue or fix touches a sensitive area
(auth, payments, secrets, production data, migrations, PII). See `.claude/rules/risk-classification.md`.

## When to use
A support engineer has a customer complaint — "customer cannot export invoices over 10MB" — and wants
it reproduced, diagnosed, and fixed through the normal pipeline rather than hot-patched.

## Who should use it
Support engineers, customer success, operators. Engineers can use it too, but may prefer `/triage`
and `/debugging-and-error-recovery` directly.

## Required inputs
The reported symptom in the customer's words. Helpful: logs, repro steps, environment, affected accounts.

## Ordered questions to ask
1. What is the **exact symptom**, and what was the customer **expecting** instead?
2. What are the **repro steps** — and does it fail every time or intermittently?
3. What's the **environment** (which app/version, region, plan, browser/client)?
4. Which **accounts/scope** are affected — one, a segment, or everyone?
5. Do you have **logs, error IDs, or screenshots**, and is any data **sensitive** (PII, production)? → raise the tier.

## Agents to delegate to
`support-ticket-engineer` (shape the bug report and reproduction) → `risk-classifier` (tier it) →
`orchestrator` (run the fix lane: `developer`, `sdlc-code-reviewer`, `tester`). Use `/triage`,
`/debugging-and-error-recovery`, and `/test-driven-development` under the hood.

## Quality gates
Reproduction is deterministic (or marked intermittent with conditions); suspected code paths are
named; fix proposal is scoped with a rollback note; risk tier assigned; **human approval recorded
before code changes**; a failing test reproduces the bug first; the pipeline's own gates then apply.

## Expected outputs
Reproducible bug report (symptom · steps · environment · scope) · suspected code paths · fix proposal ·
risk tier · validation checklist · the explicit approval checkpoint. Then (after approval) the fix and
its regression test via the pipeline.

## Stop conditions
Stop and ask if the issue can't be reproduced, repro steps conflict, scope balloons across systems,
the fix is high/restricted risk, it needs production data or PII, or it exceeds the active autonomy
level (`.claude/rules/autonomy-levels.md`).

## Example
```
/customer-issue-to-fix Customer cannot export invoices over 10MB
→ asks: exact error? every time? which plan/region? logs/error ID?
→ reproduces with a >10MB invoice; suspected paths: export handler + size limit
→ fix proposal: raise/stream the limit; risk: medium (touches export path → confirm)
→ writes a failing regression test, routes to developer → code reviewer → tester
→ STOPS for approval before any code is changed
```
