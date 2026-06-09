# Mandatory Workflow

This document defines **two development workflows**: one for bug fixes and one for features.
Identify which workflow to follow FIRST, then execute it step by step.

The pipeline is **stack-agnostic**. Wherever it says "run the project's lint / type-check /
test / build commands," substitute the actual commands for your stack (define them in
`.claude/rules/linting-and-formatting.md` and `.claude/rules/testing.md`). The canonical
example of parallel work uses a **backend lane** and a **frontend lane**, but the same
fork/join logic applies to any set of independent work streams.

## Which Workflow?

| Task type | Workflow |
|-----------|----------|
| Bug fix, defect, regression, crash, broken behavior | **Bug Fix Workflow** |
| New feature, enhancement, new page/component, refactor | **Feature Workflow — SDLC Agent Pipeline** |

If unclear whether a task is a bug fix or feature, ask the user.

---
---

## Working Memory & Self-Check (both workflows)

- **CONTINUITY.md** — read `.claude/CONTINUITY.md` at the start of every turn and write it
  back at the end and at each stage transition. It carries phase, active work, decisions,
  mistakes, and next steps across context compaction and new sessions. Durable learnings go
  to `.claude/agent-memory/` via the `remember` skill. See `.claude/rules/continuity.md`.
- **RARV** — every step runs Reason → Act → Reflect → Verify; never hand off before Verify is
  green. See `.claude/rules/rarv-cycle.md`.
- **Severity** — classify findings Critical/High/Medium/Low/Cosmetic; a gate passes only with
  zero Critical/High/Medium open. See `.claude/rules/quality-gates.md`.
- **Agent operating disciplines** — every agent also follows, throughout both workflows: how to
  reason (`.claude/rules/reasoning-techniques.md`); measurable goals, monitoring, and prioritization
  (`.claude/rules/goal-setting-and-monitoring.md`); safe handling of untrusted inputs/outputs and
  least-privilege tools (`.claude/rules/agent-guardrails.md`); recovery from tool/agent failures
  (`.claude/rules/agent-resilience.md`); and when to stop for a human
  (`.claude/rules/human-in-the-loop.md`).

---
---

# Bug Fix Workflow

A streamlined, 6-step process: **reproduce → understand → fix → verify**. No test plans, no
review docs, no feature planning. Find the bug, prove it with a test, fix it, confirm nothing
else broke.

```
B1 (understand) → B2 (reproduce + failing test) → B3 (root cause) → B4 (fix) → B5 (quality gate) → B6 (commit)
```

## B1 — Understand the Bug
- Read the bug report completely. What is the expected behavior? What is the actual behavior?
- Identify which module and file(s) are affected.
- Read the affected code BEFORE changing anything.
- If the report is vague, ask: which component, repro steps, expected vs. actual.

**Gate:** Can you describe the bug, the expected behavior, and where it likely lives?

## B2 — Reproduce with a Failing Test
Write a test that captures the buggy behavior BEFORE writing any fix.
- The test must FAIL with the bug present — proving the bug exists.
- Assert the EXPECTED (correct) behavior, not the current broken behavior.
- Keep it minimal. Cover edge cases (null, empty, zero, boundary) where relevant.

**Gate:** Does your test fail for the right reason? If it passes, it isn't testing the bug.

## B3 — Find the Root Cause
Do NOT start fixing until you understand WHY the bug happens.
- Trace the data flow: where does the bad value come from?
- Is it in the component, the state, the data, or a shared utility?
- Is it a type issue, logic error, missing guard, or a wrong assumption?

**Rules:** Fix the ROOT CAUSE, not the symptom. Don't modify a test to make it pass. Don't
suppress type/lint errors to hide a mismatch. **Gate:** Can you explain the root cause in one sentence?

## B4 — Fix the Bug
Apply the minimal fix that addresses the root cause.
- ONLY change what is necessary. Do NOT refactor or "improve" surrounding code.
- If the fix touches a shared component/utility, find all consumers and verify they still work.
- If the fix needs project-wide file changes, ask the user first.
- No error suppression, no temporary code, follow existing conventions.
- For UI: verify at mobile/tablet/desktop widths and keep it accessible.

**Verify:** Your B2 test now passes; ALL existing tests still pass; the fix is minimal.

## B5 — Quality Gate
Run, in order, your project's: **linter → type-check (if any) → tests → build.** All must pass.
Review the diff: only bug-related files changed, no suppressed errors, no temporary code.
**If it fails:** fix it — do NOT suppress errors. If you can't resolve it, ask the user.

## B6 — Commit + Report
Use your project's commit convention (see the commit format note below). Then report:
1. **Bug** (one sentence) 2. **Root cause** (one sentence) 3. **Fix** (files changed)
4. **Test** added to prevent regression 5. **Ask** whether to deploy and to which environment.

---
---

# Feature Workflow — SDLC Agent Pipeline

A 3-phase, 7-stage pipeline for new features, enhancements, and refactors. Each stage is
handled by a dedicated agent in `.claude/agents/`.

```
Phase 1 — Planning (Stages 0-3)   ║  Phase 2 — Development (4-5)   ║  Phase 3 — Testing & Delivery (6-7)
[0] Orchestrator receives request ║  [4] Developer writes code      ║  [6a] Unit Tester ─┐
1a→1b→1c→1d→1e ───────────────────╬──► 2a→2b→2c→2d ────────────────╬──► [6b] E2E Tester ─┤ (parallel)
Understand→Clarify→Spec→Dev docs  ║  Read→Implement→Quality gate    ║  3a→3b→3c→3d
→ EM review                       ║  → Code review                  ║  → Security → DevOps/Obs → PR → Human
```

**Pipeline rules:**
- No code is written until Phase 1 is complete (EM approval required).
- No testing starts until Phase 2 code review passes.
- No PR is created until all tests pass (unit + E2E).
- No task is marked done until the user has reviewed and accepted.

---

# Phase 1 — Planning (Stages 0-3)

## 1a — Understand the Requirement `[Orchestrator]`
Read the task twice. Find the spec/reference for this feature (check `docs/specs/`,
`docs/planning/`). Identify which module/package it belongs in.
**Gate:** Can you explain in one sentence what the task asks for and where it lives?

## 1b — Clarify Ambiguities `[Orchestrator]`
If ANYTHING is vague, STOP and ask before proceeding. Never infer missing requirements. State
assumptions explicitly and ask for confirmation.
**Gate:** Are all requirements clear and confirmed?

## 1c — Create Feature Spec `[Spec Writer]`
**Output:** `docs/specs/{feature-name}_spec.md` with: overview; numbered requirements (R1,
R2, …) each with a user story, acceptance criteria, and edge cases; dependencies; out of
scope; assumptions; open questions.
**Rules:** every requirement has acceptance criteria; flag conflicts; mark assumptions; the
spec is the contract. **Gate:** spec exists with acceptance criteria for every requirement and
the user has confirmed it.

## 1d — Create Developer Documentation `[Dev Doc Writer]`
Append a Developer Documentation section to the same spec file: architecture overview, file
structure, data models, component/interface contracts, state management, implementation
steps, error handling, edge-case mapping, non-functional requirements, and a spec-traceability
table (each requirement → implementation approach → files).
**Gate:** the spec file now covers all requirements with an implementation approach.

## 1e — EM Review & Approval `[EM Reviewer]`
A skeptical Engineering Manager reviews the dev docs for completeness, quality (simplest
approach, no over/under-engineering), non-functional concerns, and architecture fit.
Feedback loops with the Dev Doc Writer, **max 3 iterations**, then escalate.
**Gate:** EM signals `APPROVED`. Development CANNOT start without it.

---

# Phase 2 — Development (Stages 4-5)

## 2a — Read Existing Code & Confirm Scope `[Developer]`
Work in an **isolated git worktree**. Before writing code, read the approved spec + dev docs,
the relevant `.claude/rules/*` for your stack, and EVERY file you plan to modify — in full.
Understand a function's callers/returns before changing it. Reuse existing utilities and
components — search before creating.

**Scope check** for every planned edit: is this file in the task? does the task depend on it?
can the task be done WITHOUT this edit? If yes to the last, drop it.

Changes to **project-wide files** (build config, dependency manifests, lockfiles, CI config,
app entry points, shared barrels) require telling the user what and why, the impact, and
getting approval first. NEVER add/remove/upgrade dependencies without confirmation.
**Gate:** you understand every file/function you'll touch; the file list is task-scoped only.

## 2b — Write Implementation Code `[Developer]`
Follow the approved spec + dev docs and your stack's rules.
- Put files in the correct module/package; don't put module-specific code in shared dirs.
- Reuse the design system / shared components; follow existing patterns and naming.
- **Every data-driven UI component handles all states:** loading, empty, error, success.
- **Accessibility (UI):** keyboard access, alt text, ARIA labels, focus management, color is
  never the only indicator, sufficient contrast. See `.claude/rules/responsive-and-accessibility.md`.
- **Responsiveness (UI):** works at mobile/tablet/desktop widths; mobile-first.
- **Edge cases:** handle null/undefined/empty/zero/boundary inputs.
- **No error suppression** (no `@ts-ignore`, `as any`, blanket lint-disable, bare excepts to
  hide failures). If you can't resolve an error properly, STOP and ask.
- **Root-cause fixes only** — understand WHY before fixing; never paper over with a fallback.

After implementation, run the quality gate: the project's **linter → type-check → build**;
all must pass before committing to the worktree.
**Gate:** implementation matches the spec; lint/type-check/build pass; code is committed.

## 2c — Code Review `[Code Reviewer]`
The reviewer is read-only — suggests changes, does NOT write code. It reads the spec and the
relevant rules, then checks: correctness vs. spec & acceptance criteria; code quality
(no suppressed errors, explicit types, null handling, no dead code, naming, function/file
size); performance; security; linting; design-system/responsive/accessibility compliance;
conventions. Feedback loops with the Developer, **max 5 iterations**, then escalate.
**Gate:** Code Reviewer signals `APPROVED`. Testing CANNOT start without it.

## 2d — Breaking Changes + Impact Check `[Developer]`
If you renamed an export, changed a signature, or modified a shared module/utility — find
every consumer and verify it still works. Run the full test suite (not just your tests).
Review the diff for changes outside your scope.
**Gate:** zero regressions verified across the codebase.

---

# Phase 3 — Testing & Delivery (Stages 6-7)

## 3a — Unit Tests `[Unit Tester]` (parallel with 3b)
Cover every public function/module: happy paths, edge cases, error scenarios, all branches,
all UI states, and accessibility attributes. Tests mirror source structure; test behavior,
not implementation; query by role/label/text over test ids. **Target: 90% coverage** on
statements/branches/functions/lines (adjust to your project's standard).
**Gate:** all tests pass; coverage meets the threshold.

## 3b — E2E Tests `[E2E Tester]` (parallel with 3a)
Cover critical user journeys, navigation, forms (input→validation→submit→success/error), data
display, interactive components, and error/empty states. For UI, test at **mobile (≈375px),
tablet (≈768px), desktop (≈1024px+)** — check overflow, touch targets, layout adaptation. Use
accessible selectors; each test is independent.
**Gate:** all E2E tests pass at all viewports.

## 3b.5 — Test-Coverage Gate: Blind Review + Devil's Advocate
Parallel reviewers/testers assess **independently** (no shared findings) and each returns
PASS/FAIL with severity-classified findings. Any Critical/High/Medium → gate FAILs.
**Anti-sycophancy:** a **unanimous PASS** triggers the `devils-advocate` agent, which assumes
the work is guilty. The gate is not PASS until it returns **CONFIRMED**; an **UPHELD** verdict
re-opens the defect loop. See `.claude/rules/quality-gates.md`.

## 3b.6 — Security (gate: Security Clear)
The `security-reviewer` dispatches four sub-scanners in parallel — `secret-scanner`,
`dependency-scanner`, `owasp-reviewer`, `policy-validator` — and aggregates by severity.
**Security Clear** passes with zero Critical/High/Medium. Failures route to the dev lane via
the defect loop; only the affected scanner re-runs.

## 3b.7 — DevOps + Observability (conditional, before PR)
For changes touching a **deployable or observable surface**, run two gated phases (skip with a
noted reason otherwise — see `.claude/rules/devops-observability.md`):
- **DevOps** `[devops-engineer]` — **Pipeline Green**: CI valid, build/containers healthy, env
  vars + migrations + runbook complete.
- **Observability** `[observability-engineer]` — **Observability Ready**: SLOs/SLIs, health/
  readiness checks cover new deps, structured logs + alerts, request-id propagation.

## 3c — PR Creation `[PR Raiser]`
Triggered only after BOTH test agents report success.
1. **Final quality gate:** the project's lint → type-check → unit tests → E2E tests → build.
2. **Commit hygiene:** follow the project's commit convention; stage files by name (never
   `git add -A`); never commit secrets; never `--no-verify`; never force-push to main.
3. **Create the PR** with a structured description: summary, changes, spec traceability, test
   evidence (counts, coverage, viewports), breaking changes.
4. Report the PR URL + status.

## 3d — Human Review + Deploy `[Human-in-the-Loop]`
Present: what was built (plain language), pipeline status, files changed, test coverage, known
limitations, PR URL. **The task is NOT complete until the user reviews and accepts.**
**Deploy is user-directed:** ask whether to deploy and to which environment. Do NOT deploy
without explicit confirmation. Run the project's deploy command only after the user confirms;
report the output; on failure, share the error and do NOT retry without asking.

---

# Quick Reference

## Bug fix flow
```
B1 understand → B2 failing test → B3 root cause → B4 fix → B5 quality gate → B6 commit + report
```

## Feature flow — SDLC Agent Pipeline
```
Phase 1: 1a Understand [Orchestrator] → 1b Clarify → 1c Spec [Spec Writer]
  → 1d Dev docs [Dev Doc Writer] → 1e EM review [EM Reviewer, max 3]
Phase 2: 2a Read code [Developer] → 2b Implement → 2c Code review [Code Reviewer, max 5] → 2d Impact check
Phase 3: 3a Unit tests ─┐ 3b E2E tests ─┘ (parallel)
  → 3b.5 Test-coverage gate (blind review + Devil's Advocate)
  → 3b.6 Security (Security Clear) → 3b.7 DevOps + Observability (if applicable)
  → 3c PR creation [PR Raiser] → 3d Human review + deploy
```

## Pipeline gating
| Gate | Required before |
|------|-----------------|
| Requirements clarified (1b) | Spec Writer starts |
| Spec approved by user (1c) | Dev Doc Writer starts |
| EM `APPROVED` (1e) | Developer starts coding |
| Code Reviewer `APPROVED` (2c) | Testing starts |
| Both testers pass (3a+3b) | Test-coverage gate |
| Test-coverage PASS/CONFIRMED (3b.5) | Security review |
| Security Clear (3b.6) | DevOps + Observability (if applicable) |
| Pipeline Green + Observability Ready (3b.7) | PR Raiser starts |
| All checks pass (3c) | PR is created |
| User accepts (3d) | Task is complete |

## When to STOP and ask the user
Vague/ambiguous requirements; existing code looks wrong but works; task needs changes outside
scope or to project-wide files; task needs dependency changes; a type/lint error can't be
resolved properly; a review loop is exhausted; the quality gate fails and can't be fixed; the
commit ticket ID is needed; the deploy environment is needed. See
`.claude/rules/human-in-the-loop.md` for the full set of decision points and the escalation protocol.

## Commit & ticket format (customize per project)
The default is **Conventional Commits**: `type(scope): summary` where `type` ∈
`feat|fix|refactor|test|docs|chore`. If your team uses ticket-prefixed commits, define that
format here (e.g. `ID:<TICKET>; <summary>`) and the PR Raiser will follow it. Always ask the
user for the ticket ID — never guess.

## Files that require user approval before editing
Build config, dependency manifests + lockfiles, CI config, app entry points, shared component
barrels/index files, `CLAUDE.md`, and `.claude/rules/*`. Define the exact list for your project.
