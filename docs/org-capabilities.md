# Organization vibe-coding capabilities — coverage map

This document describes the **Organization Vibe-Coding Capability Layer** (introduced in claude-kit
0.6.0) and maps
the requested org capabilities onto what the kit actually ships. It exists to prove the layer was built
by **reuse, not duplication**: roughly 70% of the requested components already existed and were *mapped*
to capability packs; only genuinely-new content (the vibe-coding / non-engineer layer, safety &
compliance policies, risk classification, and a few deterministic hooks) was created.

The goal: let a whole organization — engineers, PMs, designers, QA, DevOps, security, data, support, and
founders — drive work in natural language **safely and consistently**, through one shared set of
skills · agents · rules · hooks · workflows · MCP.

## How it's wired (extend via data, not code)

A third install dimension joins `profile` (a subset) and `stack` (an overlay): **org** (scope-gated).

- **`catalog/org.yaml`** — the only place org behavior is decided: `scopes`, `teams`, the `autonomy`
  model, `strictness`, and the 7 `packs`. Read the same branch-free way as `profiles.yaml` / `mcp.yaml`.
- **`templates/org/`** — the scope-gated payload, installed **only when `scope == organization`**:
  - `org/skills/<skill>/SKILL.md` → `.claude/skills/` (auto-discovered)
  - `org/agents/<agent>.md` → `.claude/agents/` (auto-discovered)
  - `org/rules/<rule>.md` → `.claude/rules/` (auto-discovered)
  - `org/packs/<pack>/{pack.yaml,README.md}` → `.claude/org-packs/<pack>/`
  - `org/README.md` → `.claude/org-packs/README.md` (the registry & governance index)

`scope` defaults to **team**, so existing individual/team installs are unchanged except for two new
always-on **core** rules (`autonomy-levels`, `risk-classification`). Autonomy and strictness are only
prompted in organization scope.

Why packs reference standard locations: Claude Code auto-discovers `.claude/{skills,agents,rules}` but
**not** `.claude/org-packs/`. So runnable components install into the standard dirs; `org-packs/` is the
governance/manifest layer — `pack.yaml` files name the components a role bundles and mark each
`existing: true` (already in the kit, reused) or `existing: false` (added by the org layer).

## Autonomy model

How much Claude may do before a human acts. Set per repo; default **assisted**. Each level lists (in
`catalog/org.yaml`) the hooks it enables. Full text: `.claude/rules/autonomy-levels.md`.

| Level | May do | Must not, without a human | Hooks added |
|-------|--------|----------------------------|-------------|
| `advisory` | inspect · explain · plan · review | edit files unless asked | — |
| `assisted` *(default)* | edit after explaining the plan | broad/cross-cutting changes unasked | — |
| `autonomous-local` | implement locally + run validation | push, open PRs, leave the repo | `warn-large-edits`, `warn-missing-tests` |
| `autonomous-pr` | branches + PR-ready changes | **merge** (human review required) | + `guard-push-main` |
| `enterprise-controlled` | work through strict gates + audit | edit sensitive files / finish without security + review | `warn-sensitive-files`, `warn-large-edits`, `warn-missing-tests`, `validate-frontmatter`, `validate-settings`, `audit-log`, `guard-push-main`, `guard-commit-secrets` |

Review **strictness** (`light` / `standard` / `regulated`) is an independent axis; `regulated` adds the
`validate-frontmatter` + `validate-settings` hooks and the `security-clear` + `acceptance` gates.

## Risk classification

Every task is classified before work starts (`.claude/rules/risk-classification.md`).

| Tier | Examples | Required |
|------|----------|----------|
| low | docs, copy, comments, isolated non-prod scripts | normal flow |
| medium | typical feature/refactor in non-sensitive areas | plan + tests + review |
| high | auth, authz, payments, secrets, prod data, DB migrations, infra, security controls, compliance, destructive ops, dependency upgrades, many-file changes | plan · explicit approval · security review · test review · rollback notes · residual-risk summary |
| restricted | actions disallowed without written authorization | do not start without human sign-off |

The `risk-classifier` agent (read-only, `plan` mode) produces the classification and names the gates.

## Coverage map — requested → shipped

`existing` = already in the kit, mapped (not duplicated). `NEW (core)` = added everywhere.
`NEW (org)` = added under `templates/org/`, organization scope only.

### Agents

| Requested role | Shipped as | Status |
|----------------|-----------|--------|
| code-reviewer | `sdlc-code-reviewer` | existing |
| security-engineer | `security-reviewer` (+ sub-scanners) | existing |
| secrets-auditor | `secret-scanner` | existing |
| system-architect | `technical-architect` | existing |
| incident-commander | `incident-responder` | existing |
| migration-specialist | `migration-specialist` (DB overlay) | existing (overlay) |
| designer-to-ui-agent | `ui-designer` | existing |
| repo-context-analyst | built-in `Explore` + `/repo-onboarding` | existing (mapped) |
| task-complexity-classifier | `orchestrator` (routing) | existing |
| scope-controller | `/scope` skill | existing |
| risk-classifier | `risk-classifier` | **NEW (core)** |
| pm-copilot | `pm-copilot` | **NEW (org)** |
| founder-prototype-agent | `founder-prototype-agent` | **NEW (org)** |
| support-ticket-engineer | `support-ticket-engineer` | **NEW (org)** |
| data-workflow-agent | `data-workflow-agent` | **NEW (org)** |
| internal-tools-builder | `internal-tools-builder` | **NEW (org)** |

### Skills

| Requested | Shipped as | Status |
|-----------|-----------|--------|
| /bug-triage | `/triage` | existing |
| /write-tests | `/unit-test`, `/test-driven-development` | existing |
| /review-pr | `/code-review-and-quality` | existing |
| /security-review | `/security-and-hardening`, `/security-verification` | existing |
| /performance-review | `/performance-optimization`, `/load-testing` | existing |
| /release-plan, /rollback-plan | `/shipping-and-launch` | existing |
| /docs-update | `/refresh-docs`, `/documentation-and-adrs` | existing |
| /design-to-frontend | `/frontend-ui-engineering`, `/component-design` | existing |
| /api-contract | `/api-and-interface-design` | existing |
| /refactor-safely | `/code-simplification` | existing |
| /incident-runbook | `/incident-postmortem` | existing |
| /threat-model | `/threat-model` | **NEW (core)** |
| /accessibility-review | `/accessibility-review` | **NEW (core)** |
| /feature-from-idea | `/feature-from-idea` | **NEW (org)** |
| /prototype-to-production | `/prototype-to-production` | **NEW (org)** |
| /customer-issue-to-fix | `/customer-issue-to-fix` | **NEW (org)** |
| /prompt-to-safe-task | `/prompt-to-safe-task` | **NEW (org)** |
| /repo-onboarding | `/repo-onboarding` | **NEW (org)** |

### Rules

| Requested policy | Shipped as | Status |
|------------------|-----------|--------|
| human-approval-policy | `human-in-the-loop.md` | existing |
| definition-of-done | `quality-gates.md` + `goal-setting-and-monitoring.md` | existing |
| code-quality | `code-organization.md` + `design-patterns.md` + `linting-and-formatting.md` | existing |
| testing-policy | `testing.md` | existing |
| documentation-policy | `documentation.md` | existing |
| git-workflow | `git-workflow-and-versioning.md` | existing |
| destructive-command-policy | `guard-rm-rf` hook + `agent-guardrails.md` | existing |
| auth-and-permissions-policy | `warn-sensitive-files` hook + security agents | existing + new hook |
| dependency-policy | `dependency-scanner` agent | existing |
| autonomy-levels | `autonomy-levels.md` | **NEW (core)** |
| risk-classification | `risk-classification.md` | **NEW (core)** |
| ai-working-agreement | `ai-working-agreement.md` (org umbrella) | **NEW (org)** |
| prompt-to-task-conversion | `prompt-to-task-conversion.md` | **NEW (org)** |
| non-engineer-safe-coding | `non-engineer-safe-coding.md` | **NEW (org)** |
| prototype-boundaries | `prototype-boundaries.md` | **NEW (org)** |
| ambiguity-resolution | `ambiguity-resolution.md` | **NEW (org)** |
| secrets-policy | `secrets-policy.md` | **NEW (org)** |
| production-data-policy | `production-data-policy.md` | **NEW (org)** |
| pii-policy | `pii-policy.md` | **NEW (org)** |
| branch-and-pr-policy | `branch-and-pr-policy.md` | **NEW (org)** |
| compliance-policy | `compliance-policy.md` | **NEW (org)** |

### Hooks

| Requested guard | Shipped as | Status |
|-----------------|-----------|--------|
| dangerous shell | `guard-rm-rf` | existing |
| read secrets | `protect-secrets` | existing |
| commit secrets | `guard-commit-secrets` | existing |
| push to main | `guard-push-main` | existing |
| lint after edit | `lint-fix` | existing |
| type check | `type-check` | existing |
| sensitive-file warning | `warn-sensitive-files` | **NEW** |
| large-edit warning | `warn-large-edits` | **NEW** |
| missing-test warning | `warn-missing-tests` | **NEW** |
| frontmatter validation | `validate-frontmatter` | **NEW** |
| settings validation | `validate-settings` | **NEW** |
| local audit log | `audit-log` (local only — never external) | **NEW** |

## Capability packs

Seven role-oriented bundles (`templates/org/packs/`, installed in organization scope). Each `pack.yaml`
lists the skills/agents/rules/hooks it bundles; each `README.md` documents purpose, who uses it, and the
role→component mapping.

| Pack | For | Bundles (highlights) |
|------|-----|----------------------|
| `engineering-core` | engineering | `/sdlc`, `developer`, `sdlc-code-reviewer`, `risk-classifier`, mandatory-workflow + quality-gates |
| `product-to-code` | product, founders | `/feature-from-idea`, `/prompt-to-safe-task`, `pm-copilot`, `story-planner`, ambiguity-resolution |
| `quality-and-review` | QA, reviewers | `/test-driven-development`, `/code-review-and-quality`, testers, `devils-advocate`, testing |
| `security-and-compliance` | security, compliance | `/threat-model`, `/security-and-hardening`, security agents, secrets/pii/compliance policies, secret guards |
| `devops-and-release` | DevOps, SRE | `/shipping-and-launch`, `/incident-postmortem`, `devops-engineer`, `observability-engineer`, branch-and-pr-policy |
| `onboarding-and-docs` | new hires, all | `/repo-onboarding`, `/refresh-docs`, `Explore`, documentation |
| `non-engineer-builder` | founders, support, ops | `/prototype-to-production`, `/customer-issue-to-fix`, founder/support/data/internal-tools agents, non-engineer-safe-coding, prototype-boundaries |

## Distribution & governance

| Layer | Lives in | Use for |
|-------|----------|---------|
| **Project** | `.claude/`, `CLAUDE.md`, `.mcp.json` (committed) | what this repo needs |
| **User** | `~/.claude/` (per developer, not committed) | personal preferences and overrides |
| **Organization** | versioned, changelogged packs in an approved registry | shared, governed capabilities |

**Never commit:** local secrets, `.env`, personal tokens, personal `settings.local.json`.

Governance (see `.claude/org-packs/README.md`): add a skill/agent in `templates/org/…` and list it in
the pack's `pack.yaml`; **reuse before creating** (never add a competing duplicate); retire duplicates
via `/deprecation-and-migration`; have security/DevOps approve hooks and sensitive rules; version packs
and roll out repo-by-repo with `claude-kit diff` → `claude-kit upgrade`; run different autonomy levels
per repo; capture recurring prompts (→ skills) and mistakes (→ rules) via the `remember` skill.

### Planned

`claude-sdlc package-org-pack` / `install-org-pack` are registered as **planned** stubs — they will
package an approved pack (manifest + version + changelog + compatibility) and install it into a project.

## What was deliberately mapped, not created

To honor "one source of truth" and the description-based auto-selection of agents, the following were
**not** recreated (creating near-duplicates would dilute selection and violate golden rule #1): the
requested stack rules (`react`/`fastapi`/`postgres`/`mongodb`) already ship as overlays under
`templates/stacks/`; the renamed agents above already exist under their canonical names; and the mapped
policies are folded into existing rules. The packs reference all of these by their canonical names.
