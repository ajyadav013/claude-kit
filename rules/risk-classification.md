# Risk Classification

Classify every task **before** acting so the right amount of caution, review, and human approval is
applied. Skills record a risk tier; the `risk-classifier` agent can decide ambiguous cases. The tier
sets the minimum bar — never *lower* it because a level grants more autonomy
(`.claude/rules/autonomy-levels.md`).

## Tiers

| Tier | Meaning | Bar |
|------|---------|-----|
| **low** | local, reversible, well-understood (a small UI tweak, a docstring, a unit test) | proceed within the active autonomy level |
| **medium** | non-trivial logic or cross-module impact, but not in a sensitive area | plan first; run validation before completion |
| **high** | touches a sensitive area (below) or generated code spans many files | **the high-risk protocol** (next section) |
| **restricted** | destructive, irreversible, or compliance-gated; or beyond the active autonomy level | **stop and get explicit human authorization before any change** |

## Sensitive areas → at least **high**

authentication · authorization · payments / billing · secrets & credentials · production data · database
migrations · infrastructure / IaC / CI-CD · security controls · compliance-sensitive code (PII, audited
flows) · destructive operations · dependency upgrades · changes that touch many files at once.

## High-risk protocol (high or restricted)

1. **Plan** — write the change down before editing; list affected files and blast radius.
2. **Get explicit approval** — present the plan and wait. Do not proceed on an ambiguous "ok".
3. **Security review** — run the `security-reviewer` (and sub-scanners) on the change.
4. **Test review** — confirm tests cover the new/changed behavior and its failure modes.
5. **Rollback notes** — state exactly how to undo it (revert, down-migration, feature flag, config).
6. **Residual risk** — summarize what remains uncertain and what to watch after release.

Restricted work additionally must not start until a human has authorized it in writing.

> Part of claude-kit's organization capability layer. Cross-refs `.claude/rules/autonomy-levels.md`,
> `.claude/rules/human-in-the-loop.md`, `.claude/rules/quality-gates.md`,
> `.claude/rules/goal-setting-and-monitoring.md`. The `risk-classifier` agent applies this rule.
