# Organization capability packs

This directory is the **org capability layer** claude-kit installs when you scaffold with
`scope: organization`. Each subdirectory is a **capability pack** — a `pack.yaml` manifest plus a
`README.md` — that bundles a coherent set of skills, agents, rules, and hooks for a way of working.

> **Packs are manifests, not copies.** A pack *references* components by name; the runnable
> skills/agents/rules it lists are installed in the standard auto-discovered locations
> (`.claude/skills/`, `.claude/agents/`, `.claude/rules/`) so Claude Code picks them up normally. This
> directory is the **catalog + governance** layer: it documents which capabilities exist, who they're
> for, and how to adopt them — it is not itself executed.

## The packs

| Pack | For | Purpose |
|------|-----|---------|
| `engineering-core` | Engineering | Feature dev, refactoring, debugging, review, tests, release prep |
| `product-to-code` | Product · Founders | Ideas/tickets/PRDs/feedback → specs, stories, acceptance criteria, tasks |
| `quality-and-review` | QA · Engineering | Test planning, regression, PR/security/perf/acceptance review |
| `security-and-compliance` | Security · DevOps | Secrets, insecure code, unsafe commands, dependency/auth/data risk |
| `devops-and-release` | DevOps · Engineering | CI/CD, deploy/rollback planning, release notes, observability, runbooks |
| `onboarding-and-docs` | Engineering · Support | Understand the repo, generate/keep docs in sync, onboarding paths |
| `non-engineer-builder` | Product · Design · Founders · Support · Data | Safe vibe-coding for non-engineers (clarify, plan, limited scope, approval gates) |

## How capabilities reach this repo

| Layer | Lives in | Use for |
|-------|----------|---------|
| **Project** | `.claude/`, `CLAUDE.md`, `.mcp.json`, this README — committed | what this repo needs; the source of truth per repo |
| **User** | `~/.claude/` (per developer, not committed) | personal preferences, personal skills, local overrides |
| **Organization** | reusable packs/plugins distributed across repos | the shared, approved, versioned capabilities below |

**Never commit:** local secrets, `.env`, personal tokens, or personal `settings.local.json`.

## Autonomy & risk

Every pack operates under the project's **autonomy level** (`.claude/rules/autonomy-levels.md`) and
**risk classification** (`.claude/rules/risk-classification.md`). High-risk or restricted work (auth,
payments, secrets, production data, migrations, infrastructure) always requires a plan, explicit human
approval, security + test review, and rollback notes — regardless of pack or autonomy level.

## Governance (adopt · change · version)

- **Add a skill/agent/rule to a pack:** add the file to the kit's `templates/org/…`, list it in the
  pack's `pack.yaml`, and document it in the pack README. Reuse an existing component before creating a
  new one (avoid duplicate, competing components).
- **Approve hooks & sensitive rules:** security-relevant hooks and policy rules change through review by
  the owning team (security/DevOps) before rollout.
- **Version & roll out:** packs are versioned; record changes in a changelog and roll out repo-by-repo
  with `claude-kit diff` / `claude-kit upgrade` (your edits are backed up, never silently overwritten).
- **Different teams, different autonomy:** pick the autonomy level per repo; a regulated repo can run
  `enterprise-controlled` while an internal tool runs `assisted`.
- **Measure adoption & quality:** see the "Metrics" section in `README.claude-sdlc.md`.
