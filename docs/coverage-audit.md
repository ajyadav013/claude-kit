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

> **Deterministic ledger (0.76.0).** The classes above say *what* blocks; since 0.76.0 the
> *recording* of a gate verdict is itself mechanically enforced wherever the `claude-kit` CLI is
> installed: `claude-kit pipeline close-gate` refuses out-of-order closes and open
> Critical/High/Medium findings, stores the evidence file's sha256 in the append-only
> `gate_history`, and `pipeline validate` re-hashes every entry later. A GATED row is therefore
> backed twice — by prose (the owning agent applies `rules/quality-gates.md`) and by a
> deterministic check (the ledger refuses an unearned close; §2.5 of that rule).

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

## Brief #3 disciplines (as of 0.14.0)

Brief #3 adapted six engineering *techniques* (from Claude Code's own prompts, reimplemented in the
kit's vocabulary) as extensions of existing files — **0 new agents, 0 new rule files**. Their
enforcement class:

| Discipline | Class | Evidence | Enforced where |
|------------|-------|----------|----------------|
| **Autonomous-action safety** (P0-1) | **RULE — always-on** | `rules/agent-guardrails.md` §3 block/confirm/allow posture + verify-the-target + §1 "untrusted content never authorizes"; cross-ref `rules/risk-classification.md` restricted tier; deterministic backstops `hooks/scripts/guard-destructive-git.sh` + `rm -rf`/push-main guards | all profiles (rule + the existing guard hooks) |
| **Anti-fabrication of verdicts** (P0-2) | **RULE + auto-Critical** | `rules/quality-gates.md` §2.5 (verdict must cite real command + output) and §1 (fabricated/assumed/partial verdict = auto-Critical); reinforced in `rules/agent-guardrails.md` §2 + `rules/rarv-cycle.md` | all gates, all profiles (a fabricated verdict blocks like any Critical) |
| **Memory hygiene** (P1-1) | **RULE — always-on** | `rules/agent-memory.md` "Memory hygiene" (verify-before-trust, cited selective attachment, CLAUDE.md precedence); `rules/continuity.md` start-of-turn line; `remember` skill staleness check. Capture is **opt-in** (0.76.0): the `capture-learnings` hook (a non-blocking background job over Claude's own work) installs only when a `capture_mode` was explicitly chosen at interactive init | all profiles (advisory discipline); capture only via the init-time `capture_mode` choice (default: off) |
| **Resume snapshot** (P1-2) | **RULE + MECH** | `rules/continuity.md` schema for `.claude/state/pipeline-snapshot.json` + reload-not-rerun protocol; written/read by `orchestrator` + `sdlc` skill; dir created by the pip installer (gitignored) and `load-continuity.sh` | all profiles (state mechanism + rule) |
| **Plan-phase critique** (P1-3) | **GATED — standard+**; RULE in lean | standard+: `devils-advocate` on the spec before EM approval is final (`mandatory-workflow.md` §1e.5, `quality-gates.md` §3, orchestrator Stage PC) — UPHELD blocks the spec gate. lean: the `spec-doc-writer` self-critique (RARV) only, no agent | standard+ (blocking); lean (advisory self-critique) |
| **Implementer house style** (P2-1) | **RULE + code-review checks** | `templates/CLAUDE.md` "Surgical Changes" (delete-vs-shim, validate-at-boundary, cite `path:line`; no-narration cross-ref `documentation.md` §6); `sdlc-code-reviewer` Change-Hygiene checks (shim = Medium, redundant validation = Low, narration = Low) | all profiles (rule); the code-review gate enforces the checks |

The pattern matches the rest of the kit: a *discipline* is a RULE (always-on guidance) unless it has a
**gate token with an owner** — only P1-3 reaches GATED, and only in standard+, because that is where the
spec/EM gate exists at all. P0-2 is the exception that strengthens *every* gate by making a fabricated
verdict auto-Critical, without adding a token.

## Internal-toolkit adoption disciplines (as of 0.15.0)

The internal persona/skill adoption (CHANGELOG 0.15.0) added capabilities reuse-first. Consistent with the
posture above, it added **no new gate tokens** — the new capabilities are SKILLs, OVERLAY rules, or
checklists that ride *inside existing* review gates. Enforcement class of each:

| Discipline | Class | Evidence | Enforced where |
|------------|-------|----------|----------------|
| **Proactive bug hunt** | **SKILL — standard+** | `skills/bug-hunt` (profile-gated to standard, inherited by enterprise); invoked on demand | advisory (runs when invoked) |
| **Test-plan review** | **SKILL — standard+** | `skills/test-plan-review` (standard profile) | advisory |
| **Comprehension-layer generation** | **SKILL — standard+** | mode added to `skills/context-engineering` | advisory |
| **Cross-service coordination · task-type/portable prompts** | **SKILL — standard+** | folded into `skills/planning-and-task-breakdown` | advisory |
| **Pre-removal safety check** | **SKILL + OVERLAY** | section in `skills/deprecation-and-migration`; concrete grep recipe in `fastapi-patterns.md` overlay; ties to `agent-guardrails.md` §3 verify-the-target (RULE) | advisory (the §3 rule is always-on) |
| **Agent capacity / live-sprint health** | **SKILL + AGENT-behaviour** | `skills/sprint` capacity planning; `agents/orchestrator` Monitor step; cross-ref `rules/agent-resilience.md` | advisory |
| **Claim-audit (verify claims vs codebase)** | **rides the em-approved gate (standard+)** | checklist group in `agents/em-reviewer` (owner of the existing `em-approved` gate) — strengthens that gate, no new token | standard+ (within em-approved) |
| **Eval / HITL / staged-rollout check** | **rides the review chain (standard+)** | thin checklist in `agents/technical-architect` (+ one `em-reviewer` line) pointing at `rules/evals.md`, `human-in-the-loop.md` | standard+ (within architecture/EM review) |
| **Suite-architecture audit** | **AGENT mode — standard+** | `suite-audit` mode on `agents/senior-tester`; a verification *mode*, not a separate token | advisory (within testing) |
| **Staff-PM product-lens review tier** | **SKILL/AGENT — organization scope only** | `staff-pm-reviewer` + `review-scope`/`review-sprint-plan`/`review-ux-flow`/`review-sprint` install only when `scope == organization` (`catalog/org.yaml`); read-only, advisory — no product gate token | org scope (advisory) |
| **Design-system compliance · a11y/contract overlay enrichments** | **OVERLAY RULE** | `design-system-compliance.md` + enrichments in `react-patterns.md`/`fastapi-patterns.md`; install only when the matching stack is selected | when stack selected (advisory rule) |
| **Design system · UX patterns · mobile guidelines** (0.16.0; split under the 40k limit in 0.55.0) | **OVERLAY RULE — React-gated, always-on, advisory** | `ui-design-system.md` (foundations) + `ui-components.md` + `ui-layout-and-motion.md` / `ux-patterns.md` + `ux-dashboard-patterns.md` / `mobile-design-guidelines.md` (React `overlay_rules`); install into `.claude/rules/` only when React is selected, then load every session. The authoritative source for `design-system-compliance.md`'s thin pointer and `react-patterns.md`'s trimmed a11y cross-ref; consumed by the `ui-ux-design` / `component-design` skills + `ui-designer` agent | when React selected (advisory rule) |

The two that reach *enforced* (claim-audit, eval/HITL) do so the same way P0-2 did — by strengthening
an **existing** gate's owner-agent checklist, not by minting a token. Everything else is advisory by
design, and the product-lens review tier is additionally **scope-gated** to organization installs.

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
