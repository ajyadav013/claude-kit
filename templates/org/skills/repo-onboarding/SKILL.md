---
name: repo-onboarding
description: Use when someone new to the repo — a new engineer, support, or any newcomer — asks "how does this fit together and where do I start?" Maps the architecture, explains key modules and entry points, surfaces conventions, and produces an ordered onboarding path plus a "where things live" guide. Read-only: explores and explains, never changes code.
---

# Repo Onboarding

Give a newcomer a fast, accurate mental model of the repo: the architecture, the key modules and
entry points, the conventions that matter, and a step-by-step path to first productivity.

**Risk tier:** low — read-only discovery and explanation, no code changes. See
`.claude/rules/risk-classification.md`.

## When to use
A new hire (or support agent, or anyone new) asks "how does this service fit together and where do I
start?" and needs orientation before touching anything.

## Who should use it
New engineers, support, onboarding buddies — anyone unfamiliar with the codebase. Existing engineers
can use it to refresh on an unfamiliar area.

## Required inputs
The repo (this checkout). Helpful: the person's role, what they'll work on first, and how deep they
want to go (overview vs. full map).

## Ordered questions to ask
1. **Who** is onboarding and what's their **role** (engineer, support, other)?
2. What will they **work on or own first** — which area should the map go deepest on?
3. **Overview or deep dive** — a quick orientation, or a full module-by-module map?
4. Any **specific question** to answer first (e.g. "where does a request enter?")?
5. Should findings be **captured as docs** (run `/documentation-and-adrs`) or just explained?

## Agents to delegate to
`Explore` (read-only discovery: map structure, entry points, modules, conventions, the project's
linter / test runner / build commands). Then, if capturing: `/documentation-and-adrs` to write an
onboarding/architecture doc and `/refresh-docs` to keep it in sync. No implementation agents — this
skill never changes code.

## Quality gates
The map matches what's actually in the repo (no invented modules); entry points and the project's
build/test commands are verified by inspection; conventions cite real files; the onboarding path is
ordered and actionable; nothing is changed.

## Expected outputs
Architecture overview · key modules + entry points · conventions (style, layout, naming, test/build
commands) · a "where things live" guide · an ordered onboarding path (read → run → first small task).
Optionally a captured onboarding doc via `/documentation-and-adrs`.

## Stop conditions
Stop and ask if the requester wants code changes (out of scope — route to the engineering pipeline),
if the area is ambiguous, or if the repo is too large to map fully — narrow to the area they own first.

## Example
```
/repo-onboarding I'm a new engineer — how does this service fit together and where do I start?
→ asks: what will you work on first? overview or deep dive? capture as docs?
→ Explore maps structure, entry points, modules, conventions, build/test commands
→ produces "where things live" + an ordered onboarding path (read → run → first small task)
→ optionally captures it via /documentation-and-adrs, kept in sync with /refresh-docs
```
