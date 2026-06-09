# Compliance Policy

When review strictness is set to **regulated**, ordinary delivery is not enough: the work must be
**auditable, signed-off, and change-controlled**. This rule adds the extra obligations that apply to
regulated work, on top of the normal pipeline. It is standard-neutral — it names *what* evidence and
control to keep, not which framework demands it.

## When this applies

Regulated mode is on when the org config sets review strictness to `regulated`, or when a task touches a
compliance-sensitive area (audited flows, financial records, regulated data, anything classified at least
**high** per `.claude/rules/risk-classification.md`). When in doubt, treat it as regulated.

## What regulated work requires

1. **Audit trail** — keep a local, append-only record of who/what/when for every gated action. The
   **audit-log** hook writes it; never disable or edit it. The trail must let a reviewer reconstruct the
   change after the fact.
2. **Human sign-offs at gates** — a named human must approve at each gate; an agent PASS is not a
   sign-off. Record the approver and time alongside the gate result.
3. **Evidence of passes** — retain proof that the review, security, and test gates passed: reviewer
   notes, the **security-clear** result (secret/dependency/OWASP/policy scans), and test/coverage
   reports. Link each to the change it covers.
4. **Change control** — no change reaches a protected branch without a tracked request: spec, approvals,
   evidence, and rollback notes attached. Follow `.claude/rules/branch-and-pr-policy.md`.

## Extra gates (beyond the normal pipeline)

| Gate | Owner | Passes when |
|------|-------|-------------|
| **security-clear** | `security-reviewer` (+ sub-scanners) | zero Critical/High/Medium open; secrets, dependency, and policy scans clean |
| **acceptance** | `acceptance-reviewer` | every acceptance criterion is met **and** signed off by a named human |

Both gates are mandatory in regulated mode and run before the PR. A failed gate blocks delivery and is
recorded in the audit trail — never waive a gate silently.

## Rules

- **Evidence before assertion.** Do not claim a gate passed without the artifact that proves it.
- **Sign-offs are scoped.** Approval covers one change in one context; re-confirm for each gated step
  (`.claude/rules/quality-gates.md`).
- **Secrets and PII stay protected.** Apply `.claude/rules/secrets-policy.md` and
  `.claude/rules/pii-policy.md`; a violation is an auto-Critical that blocks every gate.
- **Tamper-evidence.** Any attempt to disable the audit-log hook or remove evidence is a restricted
  action — stop and escalate to a human.

> Part of claude-kit's organization capability layer. Cross-refs
> `.claude/rules/risk-classification.md`, `.claude/rules/quality-gates.md`,
> `.claude/rules/secrets-policy.md`, `.claude/rules/pii-policy.md`. Enforced by the **audit-log** hook
> and the **security-clear** / **acceptance** gates.
