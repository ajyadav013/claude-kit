# Mandatory Workflow

**Identify the workflow first, then walk every gate in order — no phase starts until the one before it has passed.**

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
| Migration / repo-wide refactor / many subsystems / any irreversible step (production data, schema, deletion sweep) | **Wave Orchestration** — `.claude/rules/wave-orchestration.md` (each unit inside a wave still runs one of the two workflows above) |

If unclear whether a task is a bug fix or feature, ask the user.

---
---

## Working Memory & Self-Check (both workflows)

**Self-check before every handoff:** which stage am I at, which gate is next, and can I show the
captured evidence that the current one passed? If you can't, you are not done.

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
1a→1b→1c→1d→1e→1f ─────────────────╬──► 2a→2b→2c→2d ────────────────╬──► [6b] E2E Tester ─┤ (parallel)
Understand→Clarify→Spec→Dev docs  ║  Read→Implement→Quality gate    ║  3a→3b→3c→3d
→ EM review → Story breakdown      ║  → Code review                  ║  → Security → DevOps/Obs → PR → Human
```

**Pipeline rules:**
- No code is written until Phase 1 is complete (EM approval + story-coverage gate required).
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
**Gate:** EM signals `APPROVED`. The story breakdown CANNOT start without it.

## 1e.5 — Plan Critique `[Devil's Advocate]` *(standard+)*
Before EM approval is treated as final, the Orchestrator spawns the `devils-advocate` agent once on the
spec + developer documentation. It argues the plan is wrong: the weakest or most-volatile requirement,
an untestable acceptance criterion, a hidden dependency, a missing requirement, unjustified scope, the
step most likely to fail. An **UPHELD** verdict (any Critical/High/Medium) routes back to the Spec /
Dev Doc Writer and the gate stays open; **CONFIRMED** lets planning proceed. The **lean** fast track
skips this pass (it does not install the agent); there, the Spec Writer's own self-critique in its RARV
cycle is the safeguard.
**Gate:** in standard+, EM `APPROVED` is not final until the plan critique returns CONFIRMED.

## 1f — Story Breakdown & Coverage Gate `[Story Planner]`
With the EM-approved spec, the **Story Planner** decomposes it into the smallest set of
independently shippable stories, ordered by dependency, and identifies which can run in parallel
(per lane). It builds a **traceability map**: every acceptance criterion → at least one story.

This is the spec↔stories coverage check *before* any code is written — the gate that catches an
acceptance criterion no story covers (a **gap**) and a story that maps to no criterion (**scope
creep**), so both are fixed on paper rather than discovered mid-implementation. A gap or
scope-creep finding routes back to the Spec Writer (fix the spec), never silently into the code.

**Output:** a story breakdown (written where the spec lives, or to `.claude/state/`) with stable
story ids, the criteria each satisfies, an acyclic `blockedBy`/`blocks` dependency graph, and the
immediately-startable parallel set. When a task tracker is configured, the stories can be mirrored
to it — see `.claude/skills/task-tracker-sync/SKILL.md`.
**Gate:** every acceptance criterion is covered by ≥1 story (no gaps), no story lacks a criterion
(no scope creep), the graph is acyclic, and the parallel set is genuinely unblocked. Implementation
CANNOT start until coverage is complete.

---

# Phase 2 — Development (Stages 4-5)

## 2a — Read Existing Code & Confirm Scope `[Developer]`
Work in an **isolated git worktree** (lifecycle: create one per lane → merge after the gates pass →
**remove it after the PR is raised or the run is aborted** — only the worktrees this run created, never
the user's others; `git worktree remove`, see `.claude/skills/git-workflow-and-versioning/SKILL.md`).
Before writing code, read the approved spec + dev docs,
the relevant `.claude/rules/*` for your stack, and EVERY file you plan to modify — in full.
Understand a function's callers/returns before changing it. Reuse existing utilities and
components — search before creating.

**Scope check** for every planned edit: is this file in the task? does the task depend on it?
can the task be done WITHOUT this edit? If yes to the last, drop it.

Changes to **project-wide files** (build config, dependency manifests, lockfiles, CI config,
app entry points, shared barrels) require telling the user what and why, the impact, and
getting approval first. NEVER add/remove/upgrade dependencies without confirmation.
**Gate:** you understand every file/function you'll touch; the file list is task-scoped only.

## 2a.5 — Reuse & YAGNI Gate `[Developer]`
The cheapest code is the code you never write. Before adding a single new file, function, type, or
abstraction, walk this ladder and **stop at the first rung that satisfies the need** — only what
survives every rung gets written:

1. **Does it need to exist at all?** If the task is satisfiable without this code, don't write it.
2. **Already in the codebase?** Search first; reuse the existing utility, component, or pattern
   rather than adding a parallel one.
3. **Standard library?** Prefer the language's stdlib over a hand-rolled equivalent.
4. **Native platform feature?** A built-in input type, a CSS feature, a DB constraint, a framework
   primitive — use it before adding a dependency or custom code.
5. **An existing dependency?** Reuse something already installed before pulling in a new one (and
   adding a dependency needs user approval — see 2a).
6. **The minimum that works?** No abstraction with a single caller, no config nobody sets, no layer
   that only delegates, no flexibility no requirement asks for.

Record any deliberate shortcut where you take it — `# shortcut: <ceiling> — <upgrade path>` (see
`.claude/skills/simplification-debt/SKILL.md`) — so it is traceable, not silent debt.

This is the **proactive twin** of the reactive `over-engineering-review` skill: the same
delete/stdlib/native/yagni/shrink lenses, applied *before* the code exists rather than scanned out
after. **Gate:** every new unit of code traces to a rung you could not satisfy more cheaply, and the
implementation adds no abstraction the spec does not require.

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

> **Mechanical counterpart (standard+, API-exposing stacks):** the `merge-reviewer` runs the
> **contract-clear** gate — a base-branch API-surface diff (`git show <base>:<schema>`) that classifies
> each delta by severity and blocks backward-incompatible changes lacking an approved migration note +
> version bump. It self-skips when no API contract surface exists. This §2d is the manual consumer
> check; contract-clear is its automated, externally-exposed-contract complement. See
> `.claude/agents/merge-reviewer.md`.

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
  → 1e.5 Plan critique [Devil's Advocate, standard+] → 1f Story breakdown + coverage gate [Story Planner]
Phase 2: 2a Read code [Developer] → 2a.5 Reuse/YAGNI gate → 2b Implement → 2c Code review [Code Reviewer, max 5] → 2d Impact check
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
| EM `APPROVED` (1e) | Plan critique (standard+) / Story Planner starts |
| Plan critique CONFIRMED (1e.5, standard+) | Story breakdown is final |
| Story coverage complete — every criterion mapped, no scope creep (1f) | Developer starts coding |
| Reuse & YAGNI gate cleared (2a.5) | Writing implementation code (2b) |
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

---

**This workflow is working if** every change can name the gate it last cleared, no phase started
before its predecessor passed, and a reviewer could reconstruct the path from spec to PR from the
artifacts alone.
