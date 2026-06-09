---
name: prompt-to-safe-task
description: Use when anyone — especially a non-engineer — types a free-form request in plain language and wants it turned into a scoped, risk-classified, approval-gated task before anything happens. The safe front door for vibe-coding: goal → scope + out-of-scope → risk tier → success criteria → plan → approval, then route to the right skill/agent.
---

# Prompt to Safe Task

Take any vague natural-language prompt and convert it into one scoped, measurable, risk-tiered task
with an explicit approval point — then hand it to the right place. Nothing runs until the task is clear.

**Risk tier:** varies — this skill's whole job is to **classify** it (low / medium / high / restricted).
Anything touching auth, secrets, production data, PII, or infrastructure is high/restricted. See
`.claude/rules/risk-classification.md`.

## When to use
Someone types something open-ended — "make the dashboard faster", "clean up the data", "add a login" —
and you want it scoped, tiered, and routed safely instead of acted on blindly.

## Who should use it
Everyone, especially non-engineers (PMs, founders, support, ops). It's the default entry point before
any other org skill. See `.claude/rules/ai-working-agreement.md`.

## Required inputs
The raw prompt, exactly as written. Helpful: who's asking, what they're really trying to achieve, and
any deadline or no-touch areas.

## Ordered questions to ask
1. What is the **goal** — the outcome you actually want?
2. What's **in scope** vs explicitly **out of scope**?
3. How will we know it **succeeded** (a measurable check)?
4. Does it touch a **sensitive area** (auth, secrets, production data, PII, infra)?
5. Any **constraints** (deadline, must-reuse, must-not-touch)?

## Agents to delegate to
`risk-classifier` (assign the tier per `.claude/rules/prompt-to-task-conversion.md`) → then route:
ideas to `/feature-from-idea`, prototypes to `/prototype-to-production`, bugs/issues to
`/customer-issue-to-fix`, unfamiliar repos to `/repo-onboarding`. Use `Explore` to read context first.

## Quality gates
Goal, scope, and out-of-scope are explicit; success is measurable; a risk tier is assigned; the plan
names a single next step; **human approval recorded before anything is executed**.

## Expected outputs
Restated goal · scope + out-of-scope · risk tier (with reason) · success criteria · one-step plan ·
the approval checkpoint · the chosen route (skill/agent). See `.claude/rules/ambiguity-resolution.md`.

## Stop conditions
Stop and ask if the prompt is too ambiguous to scope, if scope keeps growing, if the tier is
high/restricted, or if it exceeds the active autonomy level (`.claude/rules/autonomy-levels.md`).

## Example
```
"make the dashboard faster"
→ goal: cut dashboard load time; success: p95 load < 2s on the main view
→ scope: the main dashboard view; out-of-scope: redesign, new metrics
→ risk: low–medium (read paths only; confirm if it touches the data store)
→ plan: measure baseline, then propose one change
→ STOPS for approval → routes to /performance-optimization
```
