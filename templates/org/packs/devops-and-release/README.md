# DevOps & Release

Standardise the path from a green build to a safe release: CI/CD, deploy and rollback planning,
release notes, observability, incident runbooks, and operational readiness.

**Primary teams:** DevOps · Engineering · **Default risk:** high · **Manifest:** `pack.yaml`

## Who uses it
DevOps and platform engineers, and any engineer shipping a deployable or observable change — the pack
for the release and operate end of the loop.

## Role → component mapping
This pack bundles components that already ship with claude-kit (reused, not duplicated) plus one rule
added by the org layer. It does not introduce competing agents.

| Need | Use |
|------|-----|
| Plan a release / launch | `/shipping-and-launch` → `devops-engineer` |
| Plan a rollback | `/shipping-and-launch` → `devops-engineer` |
| Set up / review the pipeline | `/ci-cd-and-automation` → `devops-engineer` |
| Make a change observable | `/shipping-and-launch` → `observability-engineer` |
| Run a load / capacity check | `/load-testing` → `observability-engineer` |
| Plan a deprecation or migration | `/deprecation-and-migration` → `migration-specialist` |
| Write an incident runbook / postmortem | `/incident-postmortem` → `incident-responder` |
| Branch, open the release PR | `pr-raiser` agent (see `branch-and-pr-policy.md`) |

## Rules it leans on
`.claude/rules/devops-observability.md`, `.claude/rules/branch-and-pr-policy.md`,
`.claude/rules/risk-classification.md`.

## Hooks it expects
`guard-push-main` (no direct pushes to the protected branch), `lint-fix`, and `type-check` — the
project's linter, formatter, and type/build checks gate every release path.

## Examples
```
/release-plan Cut the next release: changelog, deploy steps, rollout + monitoring   # → shipping-and-launch
/rollback-plan Document how to revert the latest deploy and verify recovery          # → shipping-and-launch
/incident-runbook Draft a runbook for elevated error rates on the data store         # → incident-postmortem + incident-responder
```

## Autonomy & risk
High by default. Deploys, rollbacks, migrations, infrastructure, and incident response are at least
**high** risk — plan first, get explicit human approval, run security + test review, and write
rollback notes before any release proceeds (`.claude/rules/risk-classification.md`,
`.claude/rules/autonomy-levels.md`).
