---
name: feature-from-idea
description: Use when a PM, founder, or non-engineer describes a feature in plain language and wants it turned into acceptance criteria, user stories, and an implementation plan routed to the engineering agents — with a human approval gate before any code is written. Clarify → scope → plan → approve → build.
---

# Feature from Idea

Turn a rough product idea into a reviewable, safely-scoped plan and route it into the engineering
pipeline — without the requester needing to write code.

**Risk tier:** medium by default; **high/restricted** if it touches a sensitive area (auth, payments,
secrets, production data, migrations, infrastructure). See `.claude/rules/risk-classification.md`.

## When to use
A non-engineer (or anyone) has an idea — "add team invites to the admin dashboard" — and wants it
specced and built through the normal pipeline rather than hacked in.

## Who should use it
PMs, founders, operators, designers. Engineers can use it too, but may prefer `/spec-driven-development`
directly.

## Required inputs
A one-line description of the idea. Helpful: who it's for, why now, and any constraints.

## Ordered questions to ask
1. **Who** is this for and **what problem** does it solve?
2. What does **success** look like (a measurable outcome)?
3. What's **in scope** vs explicitly **out of scope** for v1?
4. Any **constraints** (deadline, data sensitivity, must-reuse, must-not-touch)?
5. Does it touch a **sensitive area** (auth, payments, PII, production data)? → raise the risk tier.

## Agents to delegate to
`pm-copilot` (shape the product side) → `risk-classifier` (tier it) → `spec-doc-writer` (formal spec) →
`orchestrator` (run the build lane: `developer`, `sdlc-code-reviewer`, `tester`; frontend/backend split
as needed). Use `/spec-driven-development` and `/planning-and-task-breakdown` under the hood.

## Quality gates
Acceptance criteria are testable; scope + out-of-scope are explicit; risk tier assigned; **human
approval recorded before implementation**; the engineering pipeline's own gates then apply.

## Expected outputs
Problem + goal · acceptance criteria (Given/When/Then) · prioritized user stories · risk tier · routing
plan · the explicit approval checkpoint. Then (after approval) a spec and implementation via the pipeline.

## Stop conditions
Stop and ask if requirements conflict or are missing, scope balloons, the work is high/restricted risk,
or it exceeds the active autonomy level (`.claude/rules/autonomy-levels.md`).

## Example
```
/feature-from-idea Add team invites to the admin dashboard
→ asks: who can invite? roles? email vs link? seat limits?
→ acceptance criteria + P0/P1 stories; risk: medium (touches authz → confirm) 
→ routes to spec-doc-writer → frontend + backend lanes
→ STOPS for approval before any code is written
```
