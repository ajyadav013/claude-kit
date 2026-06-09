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
added by the org layer. It does not introduce competing agents — codebase discovery uses the built-in
**Explore** research agent.

| Need | Use |
|------|-----|
| Get a guided tour of an unfamiliar repo | `/repo-onboarding` → `Explore` (discovery) → `technical-architect` |
| Discover where things live | `Explore` agent (read-only codebase search) |
| Explain how a module works / fits together | `technical-architect` (analysis only, see `code-organization.md`) |
| Generate or update architecture docs / ADRs | `/documentation-and-adrs` |
| Bring docs back in sync with the code | `/refresh-docs` (the `/docs-update` flow) |
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
/repo-onboarding   # → Explore maps the repo, technical-architect explains the architecture + an onboarding path
/docs-update Sync the docs after the checkout refactor   # → refresh-docs + documentation-and-adrs
/repo-onboarding the data-store layer   # → focused tour of one module
```

## Autonomy & risk
Default **low** risk: discovery, explanation, and documentation are read-mostly. These personas
**plan and explain only** — any actual code change (including a doc fix that touches source) is handed to
engineering and runs under the repo's autonomy level. Anything touching a sensitive area (auth, payments,
secrets, production data, migrations, infrastructure) is at least **high** risk and goes through the
engineering review chain with human approval (`risk-classification.md`).
