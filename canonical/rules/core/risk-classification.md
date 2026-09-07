# Risk Classification

Classify every task **before** acting so the right amount of caution, review, and human approval is
applied. Skills record a risk tier; the `risk-classifier` agent can decide ambiguous cases. The tier
sets the minimum bar — never *lower* it because a level grants more autonomy
(`rule://autonomy-levels`).

## Tiers

| Tier | Meaning | Bar |
|------|---------|-----|
| **low** | local, reversible, well-understood (a small UI tweak, a docstring, a unit test) | proceed within the active autonomy level |
| **medium** | non-trivial logic or cross-module impact, but not in a sensitive area | plan first; run validation before completion |
| **high** | touches a sensitive area (below) or generated code spans many files | **the high-risk protocol** (next section) |
| **restricted** | destructive, irreversible, or compliance-gated; or beyond the active autonomy level | **stop and get explicit human authorization before any change** |

> Classification sets the *bar*. *How* to carry out (or refuse) a destructive or outward-facing
> action once you reach it — the block / confirm / allow posture and the verify-the-target step —
> lives in `rule://agent-guardrails` §3.

## Sensitive areas → at least **high**

authentication · authorization · payments / billing · secrets & credentials · production data · database
migrations · infrastructure / IaC / CI-CD · security controls · compliance-sensitive code (PII, audited
flows) · destructive operations · dependency upgrades · changes that touch many files at once.

## Story-level routing (inside a feature run)

Once a spec is broken into stories, the tier also allocates **ceremony per story**: a **low**-risk
story (tagged by the story planner) routes through the reduced chain — developer → code reviewer →
tester — while its siblings keep the full chain. Three things never move with the tier: run-level
gates still apply to the merged output (zero Critical/High/Medium — `rule://quality-gates`);
specialist routing in `rule://mandatory-workflow` still triggers on the **surface
touched, never story size** (a "low-risk" story that edits a query, auth, or secrets is at least
**high** — see the sensitive areas above); and code review itself is never skipped. This is not a
lowered bar: the tier decides **which agents spawn for the story**, never what passes a gate.

## Fastest-safe SDLC mode

Classification also sets the **minimum** workflow shape. Select Mode D automatically when the work
is low risk, reversible, confined to one local boundary, its behavior is already unambiguous, and it
touches no sensitive area or public contract. File count is a planning hint, not the decision: a
small migration is still high risk, while a localized rename may legitimately touch a source file,
tests, and generated documentation. Mode D still requires Developer → Code Reviewer → focused
verification → closeout.

Any authentication/authorization, tenant isolation, secret, payment, schema/migration, dependency,
infrastructure, security-policy, public API/event/data contract, cross-boundary, production-data, or
irreversible surface floors the run at the applicable full SDLC mode (A/B/C/E). If classification is
uncertain, choose the fuller mode. Once the predicates are recorded, do not add personas merely for
comfort and do not downgrade the deterministic gate that owns the touched surface.

## High-risk protocol (high or restricted)

1. **Plan** — write the change down before editing; list affected files and blast radius.
2. **Get explicit approval** — present the plan and wait. Do not proceed on an ambiguous "ok".
3. **Security review** — run the `security-reviewer` (and sub-scanners) on the change.
4. **Test review** — confirm tests cover the new/changed behavior and its failure modes.
5. **Rollback notes** — state exactly how to undo it (revert, down-migration, feature flag, config).
6. **Residual risk** — summarize what remains uncertain and what to watch after release.

Restricted work additionally must not start until a human has authorized it in writing.

> Part of {{ provider.executable.cli }}'s organization capability layer. Cross-refs `rule://autonomy-levels`,
> `rule://human-in-the-loop`, `rule://quality-gates`,
> `rule://goal-setting-and-monitoring`. The `risk-classifier` agent applies this rule.
