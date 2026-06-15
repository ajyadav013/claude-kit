# Coverage audit — GATED vs RULE vs SKILL/DOC

claude-kit's reuse-first reviews often defer adding something because a skill or rule "touches" the
topic. But the three are **not** equivalent in enforcement strength:

| Class | What it means | Enforced? |
|-------|---------------|-----------|
| **GATED** | A gate token in `catalog/profiles.yaml` / `catalog/org.yaml`, owned by an agent, blocking at ≥ Medium severity (`rules/quality-gates.md` §1) | **Yes** — blocks delivery |
| **RULE** | An always-on file in `.claude/rules/` (installed in every profile) | Partly — an instruction the agents must follow; not a blocking checkpoint by itself |
| **SKILL / DOC** | A profile-gated skill (advisory, invoked on demand) or repo documentation | **No** — guidance, runs only when invoked |

This document is the **justification record** for what the kit enforces versus documents. Each P0/P1
item in the improvement briefs cites a row here. It reflects the state **as of 0.13.0**.

## The named capabilities (verified against the files)

| Capability | Class | Evidence | Enforced where |
|------------|-------|----------|----------------|
| **Rollback (verified)** | **GATED — enterprise only**; RULE elsewhere | `pipeline-green` gate is listed **only** in the enterprise profile (`catalog/profiles.yaml`); owned by `devops-engineer`, which requires a *verified* rollback + runbook (`rules/devops-observability.md`, `agents/devops-engineer.md`). In lean/standard, rollback is **RULE-level** advice via `rules/risk-classification.md` (high-risk changes need rollback notes), not a gate. | enterprise (blocking); lean/standard (advisory) |
| **Cost expectations** | **DOC — by design** | `rules/model-tiers.md` "Profile cost expectations" (added 0.12.0). A `cost-estimate` skill + per-run cost hook were **deliberately rejected** (CHANGELOG 0.12.0) — the kit cannot reliably meter tokens at scaffold time. | documented only (accepted) |
| **Migration safety** | **RULE + OVERLAY-AGENT (advisory) + enterprise rollback** | Always-on RULE: `rules/risk-classification.md` (DB migrations = sensitive, ≥ High). Overlay RULES (when a DB is selected): `postgres-patterns.md` / `mongodb-patterns.md` now state expand/contract + "no destructive drop in the same release" with **severity** (0.13.0, brief #2 P0-2). Overlay AGENT: `migration-specialist` (postgres + mongodb) reviews each change (expand/contract, reversible down-path, idempotent backfill; irreversible/table-locking ≥ High). **No dedicated migration gate token** — it is reviewed, not gated, and the enterprise rollback verification (`pipeline-green`) is the nearest enforced backstop. | overlay-advisory + enterprise rollback |
| **Accessibility** | **SKILL/DOC** in lean/standard/team; **GATED** at org `regulated` strictness (0.13.0) | RULE (standards): `rules/responsive-and-accessibility.md` (always-on, advisory). SKILL (review procedure): `skills/accessibility-review`. As of 0.13.0 there **is** a gate — `accessibility-clear` — but **only** under organization scope at `regulated` strictness (`catalog/org.yaml`), owned by `acceptance-reviewer`, self-skipping when no UI surface (brief #2 P1-2). Outside `regulated`, a11y is advisory and blocks nothing. | regulated-org (blocking); otherwise advisory |
| **API breaking changes** | **GATED — standard+ (API stacks)** as of 0.13.0 | `contract-clear` gate, owned by `merge-reviewer`, now in the **standard** and enterprise profiles (`catalog/profiles.yaml`); self-skips when the stack exposes no API contract surface (brief #2 P0-1). The manual counterpart is `rules/mandatory-workflow.md` §2d. | standard+ (blocking, API stacks) |

### The one "looks enforced but isn't" trap

`skills/accessibility-review/SKILL.md` contains an internal **"Quality gates"** heading — that is the
*skill's own checklist wording*, **not** a kit gate token. Before 0.13.0 nothing in
`catalog/*.yaml` enforced accessibility in any profile, so that heading could be misread as an enforced
gate. The 0.13.0 `accessibility-clear` gate (regulated-org only) is the *actual* enforcing token;
elsewhere the skill remains advisory. Do not cite a skill's internal "gate" wording as evidence of
enforcement — only a token in `catalog/{profiles,org}.yaml` enforces.

## Why the posture is internally consistent

- Gates come **only** from `prof["gates"] + org.extra_gates` (`src/claude_kit/catalog.py`); stacks
  contribute overlay rules/agents/skills, never gates. So "gated" always traces to a profile or org
  strictness level, and `resolve()` stays branch-free.
- Heavyweight, situational gates default to **enterprise** or to **org strictness** (golden rule #6).
  `contract-clear` is the deliberate exception promoted to `standard` (brief #2 P0-1) because
  breaking-change detection is table-stakes for the headline FastAPI backend — and it self-skips for
  non-API stacks, so it adds no burden where it doesn't apply.
- Where a capability is *advisory by design* (cost, lean/standard rollback, non-regulated a11y), this
  audit says so plainly rather than implying enforcement the kit doesn't provide.

## How to extend enforcement (the lever)

To move a capability from RULE/SKILL to GATED: add a gate token to a profile (`catalog/profiles.yaml`)
or to an org strictness level (`catalog/org.yaml` `extra_gates`), give it an **owner agent**, a
**self-skip** condition when irrelevant, a **severity mapping**, and a row in `rules/quality-gates.md`
§4. That is exactly how `contract-clear` (standard+) and `accessibility-clear` (regulated) were wired.
