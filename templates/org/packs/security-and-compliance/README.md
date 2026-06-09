# Security & Compliance

The guardrail layer: prevent secrets exposure, insecure code, unsafe commands, dependency risks, auth
flaws, data leakage, and unreviewed sensitive changes.

**Primary teams:** Security · DevOps · **Default risk:** high · **Manifest:** `pack.yaml`

## Who uses it
Security engineers and DevOps owners who review changes, set policy, and gate sensitive work — plus any
engineer touching a restricted surface (auth, secrets, production data, infrastructure). It runs
alongside the everyday loop, not instead of it.

## Role → component mapping
This pack reuses the security components that already ship with claude-kit (no competing agents) and
adds four policy rules plus three hooks at the org layer.

| Need | Use |
|------|-----|
| Harden code / fix an insecure pattern | `/security-and-hardening` → `security-reviewer` |
| Verify a change is safe before merge | `/security-verification` → `security-reviewer` |
| Model threats for a feature | `/threat-model` → `security-reviewer` |
| Audit dependencies for known risk | `/security-verification` → `dependency-scanner` |
| Find leaked secrets / credentials | `secret-scanner` agent (`secrets-policy.md`) |
| Check OWASP-class flaws (auth, injection, access control) | `owasp-reviewer` agent |
| Confirm a change meets policy | `policy-validator` agent (`compliance-policy.md`) |
| Decide how risky / restricted a change is | `risk-classifier` agent (`risk-classification.md`) |

These agents **plan and delegate** — they review, classify, and flag; they do not write or run code.

## Rules it leans on
`secrets-policy.md`, `pii-policy.md`, `production-data-policy.md`, `compliance-policy.md`,
`agent-guardrails.md`, `risk-classification.md`.

## Hooks it expects
`protect-secrets`, `guard-commit-secrets`, and (added by the org layer) `warn-sensitive-files`,
`validate-settings`, `audit-log`. Security-relevant hooks change only through review by the owning team.

## Examples
```
/security-review Harden the session-handling path before launch       # → security-and-hardening
/threat-model Map the abuse cases for the new public upload endpoint   # → threat-model
/dependency-audit Flag risky/outdated packages in the data store layer # → security-verification + dependency-scanner
```

## Autonomy & risk
Default risk is **high** — this is the pack that enforces the line. Any work in a sensitive area (auth,
secrets, production data, PII, migrations, infrastructure) requires a plan, explicit human approval,
security + test review, and rollback notes before it proceeds, regardless of autonomy level
(`risk-classification.md`, `agent-guardrails.md`). Secrets and production data never enter the
repo, logs, or prompts (`secrets-policy.md`, `production-data-policy.md`, `pii-policy.md`).
