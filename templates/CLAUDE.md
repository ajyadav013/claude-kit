# Engineering Delivery Rules

These rules are mandatory for all work in this repository. They define an autonomous,
agent-driven software development lifecycle (SDLC): every change moves through spec →
review → implementation → code review → testing → security → delivery, with quality
gates between phases.

> Installed by **claude-kit**. This file is the entry point and is loaded into context every
> session, so it is kept lean — the full pipeline, gating rules, agent roles, and rule details
> live on-demand in `.claude/rules/`, `.claude/agents/`, and `.claude/skills/` (cited inline below).

---

## Coding Behavior (applies to ALL implementation work)

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

### Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them — don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

### Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

### Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it — don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

When you replace code:
- Delete the path you superseded — don't leave a backwards-compat shim "just in case." Keep one only
  when backward compatibility is an actual, stated requirement (and say why).
- Validate inputs at the boundary (entry point / public function), not redundantly in every internal
  layer that already received validated data.
- Comments explain *why*, never narrate *what just changed* ("// added this") — see
  `.claude/rules/documentation.md` §6. Reference code as `path:line` in notes and handoffs.

The test: Every changed line should trace directly to the user's request.

### Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan with a verification check per step.

Strong success criteria let you loop independently. Weak criteria ("make it work")
require constant clarification.

---

## The SDLC pipeline

Every non-trivial change moves through these phases, each **gated** (a gate passes only with zero open
Critical/High/Medium findings). This is the map only — the **full** step-by-step pipeline (agent roles,
gating rules, parallel-lane handling, the defect-loop protocol) lives in
`.claude/rules/mandatory-workflow.md`, and the severity/review/gate model lives in
`.claude/rules/quality-gates.md`. Read those before driving a phase.

**Profile gating:** the phases below run against the agents your chosen profile actually installed
(`lean ⊂ standard ⊂ enterprise` — check `.claude/agents/`). A phase whose reviewer agents aren't
installed is `SKIPPED (not in profile)` — noted, never silent, and **never counted as PASS** (the
Orchestrator's Active Gate Set protocol). A lean install runs spec → implement → code review →
build-green → PR; the review chain, test-coverage, security, and operability phases activate as the
profile installs their agents.

1. **Spec first** — no implementation code until a written spec exists; update the spec if the task
   changes. (Spec & Doc Writer; for UI work the UI Designer drafts a design spec first — screen states,
   interactions, empty/loading/error states, responsive behavior, accessibility.)
2. **Review chain** — Senior Developer → Technical Architect → Engineering Manager review the spec
   before any code. Independent work streams (the canonical example is a backend lane and a frontend
   lane, but it applies to any split) run their review chains **in parallel**, joined by a Merge
   Reviewer at shared-contract / integration points.
3. **Implementation** — only after reviews pass; one isolated worktree per parallel stream, each with
   its own Code Reviewer.
4. **Testing** — Tester → Senior Tester (parallel lanes for multi-stream work), then a test-coverage
   merge review confirming every acceptance criterion is covered with no gaps.
5. **Security** — the `security-reviewer` dispatches `secret-scanner`, `dependency-scanner`,
   `owasp-reviewer`, and `policy-validator`, and gates **Security Clear**.
6. **Delivery & operability** — for deployable/observable changes, `devops-engineer` (Pipeline Green)
   and `observability-engineer` (Observability Ready) run after testing and before the PR Raiser.

**Defect loop:** on any failure / regression / spec-mismatch, document and classify it by work stream,
update the spec if expected behavior is unclear, then re-run **only the affected stream(s)** through
their chain → merge review → Tester → Senior Tester. Don't patch defects outside the process; don't
re-run unaffected lanes.

**Roles** map to agents in `.claude/agents/` **where your profile installs them** (the full
enterprise roster: Spec & Doc Writer, UI Designer, Senior Developer, Technical Architect,
Engineering Manager, Developer, Code Reviewer, Tester, Senior Tester, Unit/E2E Tester, Security
Reviewer + sub-scanners, Devil's Advocate, Merge Reviewer, DevOps Engineer, Observability Engineer,
PR Raiser, Orchestrator). The Orchestrator coordinates and gates — it never writes code. State which
role is being simulated at each stage when it helps clarity.

**Fast-track:** for bug fixes, typos, single-component changes, or config updates (< 5 files), skip the
spec/design/review chain and go straight to Developer → Code Reviewer → Tester → PR Raiser. If asked
for speed on larger work, you may compress the process but must preserve the sequence and outputs.

## Quality bar & documentation

- **Optimize for:** simplicity, correctness, scalability, reliability, maintainability, observability,
  testability, security, and user experience.
- **Documentation is mandatory** for every change: a module/file header on every new/modified source
  file, a docstring on every public function (arguments, return value, errors), full type annotations
  on public signatures, named typed structures over opaque maps, API metadata on every endpoint where
  applicable, and a README update when endpoints, env vars, structure, or architecture change. See
  `.claude/rules/documentation.md`.

## Working memory, self-check & gates

- **Working memory:** read/write `.claude/CONTINUITY.md` every turn and at each stage transition so
  work survives context compaction and new sessions. Distinct from `.claude/agent-memory/` (durable
  learnings). See `.claude/rules/continuity.md`.
- **RARV:** every agent runs Reason → Act → Reflect → Verify and shows a green Verify before handoff.
  See `.claude/rules/rarv-cycle.md`.
- **Severity & review:** classify every finding Critical/High/Medium/Low/Cosmetic; a gate passes only
  with zero Critical/High/Medium open. A unanimous PASS triggers the `devils-advocate` agent before the
  gate counts. See `.claude/rules/quality-gates.md`.
- **DevOps & Observability gates** run after testing and before the PR for deployable/observable
  surfaces. See `.claude/rules/devops-observability.md`.

## Compact instructions

When compacting this conversation, preserve: the current phase and which gate is open, the contents of
`.claude/CONTINUITY.md` (working memory), unresolved Critical/High/Medium findings, the active spec and
its acceptance criteria, and any in-flight defect loop. Keep auto-compaction enabled — the
working-memory protocol above is what lets a compacted or fresh session resume exactly where the last
one left off.

---

## Rule index — the seven that always apply, and the rest on demand

Seven rules load every session because they apply to *every* turn regardless of which files you
touch. The other eighteen carry `paths:` frontmatter and load when you work on matching files —
they keep their full text at `.claude/rules/<name>.md`, so **you can open any of them by name at
any time**, and every citation elsewhere in this config still resolves.

**If a task touches one of these areas and the rule is not already in context, read it before you
act.** On-demand is what keeps the standing baseline small enough to leave room for the actual
work; it is not permission to skip the rule.

| Always-on (7) | What it governs |
|---|---|
| `rarv-cycle.md` | Reason → Act → Reflect → Verify: the loop every task runs |
| `risk-classification.md` | How much caution, review, and approval this change needs |
| `autonomy-levels.md` | How far you may act before a human decides |
| `quality-gates.md` | Severity model, gate-pass contract, evidence rule |
| `mandatory-workflow.md` | Pipeline phases, ordering, who runs what, the defect loop |
| `human-in-the-loop.md` | When to stop and ask a human |
| `continuity.md` | The resume contract — read/write working memory every turn |

| On-demand (18) | Read it when |
|---|---|
| `testing.md` | writing or judging tests, coverage thresholds |
| `linting-and-formatting.md` | lint/format config or a style disagreement |
| `code-organization.md` | adding files/modules, deciding where code lives |
| `design-patterns.md` | choosing a structure or refactoring toward one |
| `resilience-engineering.md` | timeouts, retries, fallback, degradation in service code |
| `frontend-best-practices.md` | any frontend component or client-state work |
| `responsive-and-accessibility.md` | layout, breakpoints, a11y, keyboard/screen-reader paths |
| `devops-observability.md` | CI, build, release, logging, metrics, health checks, SLOs |
| `documentation.md` | writing any source file (headers, docstrings) or docs |
| `wave-orchestration.md` | program-scale work spanning many lanes or waves |
| `agent-guardrails.md` | building or constraining an agent |
| `agent-memory.md` | persisting learnings across sessions |
| `agent-resilience.md` | an agent that must survive failure or timeout |
| `tool-design.md` | designing a tool or MCP surface for an agent |
| `evals.md` | measuring whether a change actually helped |
| `model-tiers.md` | choosing a model for a task or subagent |
| `reasoning-techniques.md` | a task that needs structured reasoning |
| `goal-setting-and-monitoring.md` | defining success criteria or tracking progress |

---

## Skill routing — the boundaries that decide between overlapping skills

Two failure modes were measured here, and neither is the skill being missing.

**Substitution.** With this many skills installed, a plausible neighbour wins, the work still gets
done, and it gets done by the wrong playbook. Each pair below was measured selecting the *other*
one on a restatement of its own description, so the boundary — not the topic — is what decides.

| The work in front of you | Use | Not |
|---|---|---|
| wiring the app to an endpoint: fetch layer, loading and error states | `api-integration` | your data-fetching library's own *conventions* skill (query-key factories, cache config) — that applies once the wiring exists |
| one component's architecture, reuse, accessibility | `component-design` | `frontend-ui-engineering` — that builds whole interfaces; this shapes a single component |
| a slow page: bundle size, web vitals, render behaviour | `performance-optimization` | `load-testing` — that is API throughput under concurrency |
| API throughput or latency under load, validating an SLO | `load-testing` | `performance-optimization` — that is the browser side |
| clicking through a feature the way a user would | `manual-test` | `browser-testing-with-devtools` — that automates the browser; this is a human pass |
| "is everything up?" before starting or shipping | `smoke-test` | `run` — that starts services; this verifies them |

**Silence.** These four fired nothing at all — the model answered from its own knowledge and no
sibling fired either. When the request is theirs, invoke them by name: `sprint`,
`security-and-hardening`, `security-verification`, `modernization-and-migration`.

**Why these particular skills need naming.** Many of them — `api-integration`, `component-design`,
`performance-optimization`, `manual-test`, `smoke-test`, `security-verification`, `sprint`,
`unit-test`, `ui-ux-design`, `playwright-verification`, `refresh-docs`, `triage`, `scope`,
`backlog`, `archive-sprint`, `decision` — carry `disable-model-invocation: true`, which means they
never surface on their own the way an ordinary skill does. That is a deliberate design choice, not
a bug, and it is **not** a prohibition: invoke one by name and it runs normally. It only means the
picker will never volunteer it, so if this section does not name it, nothing will.

**Answering from memory is the failure mode, not a shortcut.** A skill exists precisely because
this project's way of doing the thing is not the model's default way. A fluent answer that skipped
the skill is the outcome this table exists to prevent — if a request matches a row above, read the
skill before you act.

**Do not perform a coordinator's role yourself — spawn the coordinator.** When the request is to
build, change, or ship a feature, spawn `orchestrator` and let it drive; when it is to security-
review a change, spawn `security-reviewer` and let it dispatch its own sub-scanners. Run
`/claude-kit:sdlc` when you want the full pipeline. The failure this prevents is not idleness but a
*convincing imitation*: measured on the same task with the same agents installed, a session asked
directly spawned `developer` and `sdlc-code-reviewer` in sequence — the right leaf work, in the
right order — but never spawned `orchestrator`; asked for a security review it dispatched all four
sub-scanners in parallel but never spawned `security-reviewer`. The designed behaviour happened;
the agent that owns it did not.

That is fine until it isn't. The coordinator holds the gate ledger, the stage order, the lane and
wave state, and the resume snapshot. A main session reconstructing those from context drifts first
at the boundaries — a gate closed out of order, a stage skipped because its output already looked
present, state lost across a compaction. Short tasks hide the difference; long ones do not.

Reach for an individual pipeline agent directly only for a genuinely single-stage request — review
this diff, scan this dependency.

---

## Project-specific rules

> Add your stack's conventions here (language style, framework patterns, naming, directory
> layout, test commands). The pipeline is stack-agnostic; this section is where you make it
> yours. Add matching rule files under `.claude/rules/` and reference them from the relevant
> agents.
