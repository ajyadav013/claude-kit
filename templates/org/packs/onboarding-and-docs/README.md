# Onboarding & Docs

Understand a repo fast and keep its documentation honest: explain modules, generate architecture docs,
build onboarding paths, and keep docs synchronised with the code as it changes.

**Primary teams:** Engineering · Support · **Default risk:** low · **Manifest:** `pack.yaml`

## Who uses it
New engineers ramping on an unfamiliar codebase, support staff who need to understand how a module
behaves, and anyone keeping documentation in step with the code. The personas here **read and explain**;
they never write or run code.

## Role → component mapping
This pack bundles components that already ship with claude-kit (reused, not duplicated) plus one skill
added by the org layer. It does not introduce competing agents — codebase discovery uses a
host-native read-only research role when available.

| Need | Use |
|------|-----|
| Get a guided tour of an unfamiliar repo | `/repo-onboarding` → read-only research → `technical-architect` |
| Discover where things live | a read-only codebase-research role |
| Explain how a module works / fits together | `technical-architect` (analysis only, see `code-organization.md`) |
| Generate or update architecture docs / ADRs | `/documentation-and-adrs` |
| Bring docs back in sync with the code | `/refresh-docs` (the `.claude/skills/refresh-docs/SKILL.md` workflow) |
| Ground answers in the actual source | `/source-driven-development` |
| Curate the right context for a task | `/context-engineering` |
| Find / understand which skills apply | `/using-agent-skills` |
| Coordinate a multi-step onboarding | `orchestrator` agent |

## Rules it leans on
`documentation.md` (the documentation standard every change must maintain or improve) and
`code-organization.md` (so explanations and onboarding paths describe structure accurately).

## Hooks it expects
None special — this pack is read-and-explain only, so the standard repo hooks suffice.

## Examples
```
Use `/repo-onboarding` for a guided repo tour and onboarding path.
Use `/refresh-docs` to sync the docs after the checkout refactor.
Use `/repo-onboarding` for a focused tour of the data-store layer.
```

## Autonomy & risk
Default **low** risk: discovery, explanation, and documentation are read-mostly. These personas
**plan and explain only** — any actual code change (including a doc fix that touches source) is handed to
engineering and runs under the repo's autonomy level. Anything touching a sensitive area (auth, payments,
secrets, production data, migrations, infrastructure) is at least **high** risk and goes through the
engineering review chain with human approval (`risk-classification.md`).
