# Using the claude-kit agents

claude-kit installs a team of focused agents plus an **orchestrator** that runs them through a
software-delivery pipeline with a quality gate between phases. This guide shows how to drive them.

> Prerequisite: the agents load when claude-kit is active in a project — installed as a plugin
> (`/plugin install claude-kit`) or scaffolded with `claude-kit init`. Which agents are present
> depends on the **profile** you chose at init (`lean ⊊ standard ⊊ enterprise`). After installing
> into a project, **restart Claude Code** so the agents, skills, and hooks load.

## Two ways to invoke

### 1. Run the whole pipeline (recommended)

```text
/sdlc <describe the feature or bug>
```

The `sdlc` skill is the entrypoint; it reads your profile's active gate set and hands off to the
**orchestrator**, which classifies the work, writes a spec, and moves it through review →
implementation → testing → security → delivery, enforcing a gate at each step and pausing to ask you
at genuine decision points. (From the plugin, `/claude-kit:sdlc` does the same.) Use this for
anything non-trivial.

Examples:

```text
/sdlc Add a "completed" flag to items: API field + a checkbox in the UI
/sdlc Fix the 500 when creating an item with an empty title
/sdlc Add pagination to the items list endpoint and the table
```

Check progress any time with `/claude-kit:status` or `claude-kit status` (reads working memory).

### 2. Invoke a single agent

For a focused task, ask Claude to use one agent by name — no full pipeline:

```text
Use the sdlc-code-reviewer to review my staged changes.
Use the unit-tester to add tests for app/services/item.py.
Use the security-reviewer on the auth changes.
```

## The pipeline at a glance

```
Request ─▶ classify ─▶ Spec & Dev Docs ─▶ [Gate: EM approved]
        ─▶ Review (Senior Dev → Architect → EM, per lane) ─▶ [Gate: Merge Reviewer]
        ─▶ Implement (Developer + Code Reviewer, per lane)
        ─▶ Test (unit · e2e · integration → Senior Tester) ─▶ [Gate: coverage + Devil's Advocate]
        ─▶ Security (4 sub-scanners) ─▶ [Gate: Security Clear]
        ─▶ DevOps + Observability + Acceptance (enterprise) ─▶ PR
```

Which gates actually run depends on the profile: **lean** = code-review · build-green; **standard**
adds spec/EM/coverage/security · contract-clear; **enterprise** adds pipeline-green ·
observability-ready · acceptance (contract-clear self-skips on stacks with no API contract surface, so
it is inert for non-API projects). A **fast-track** path (bug fixes / < 5 files) skips planning:
Developer → Code Reviewer → Tester → PR.

Every gate uses the same severity model — a gate passes only with **zero Critical/High/Medium**
findings open — and a *unanimous* PASS triggers the `devils-advocate` agent before the gate counts
(anti-sycophancy). See `.claude/rules/quality-gates.md`.

## The agents by phase

Each agent carries a `tier:` (orchestrator · stage-lead · specialist · review) — informational
metadata; Claude still auto-selects by description.

| Phase | Agents |
|-------|--------|
| **Coordinate** | `orchestrator` (delegates and gates; never writes code) |
| **Plan** | `spec-doc-writer`, `story-planner`, `ui-designer` |
| **Review** | `senior-backend-dev`, `senior-frontend-dev`, `technical-architect`, `em-reviewer`, `merge-reviewer` |
| **Build** | `developer`, `sdlc-code-reviewer` (+ DB overlays: `postgres-specialist` / `mongodb-specialist`, `migration-specialist`, and `db-performance-reviewer` for PostgreSQL) |
| **Test** | `unit-tester`, `e2e-tester`, `tester`, `senior-tester`, `auditor` |
| **Rigor** | `devils-advocate`, `acceptance-reviewer`, `risk-classifier` (enterprise + org) |
| **Secure** | `security-reviewer` + `secret-scanner`, `dependency-scanner`, `owasp-reviewer`, `policy-validator` |
| **Ship** | `devops-engineer`, `observability-engineer`, `pr-raiser`, `incident-responder` (enterprise) |
| **Org personas** | `pm-copilot`, `founder-prototype-agent`, `support-ticket-engineer`, `data-workflow-agent`, `internal-tools-builder` (organization scope only) |

In a scaffolded project with both a frontend and a backend stack, the two review/build lanes are
concrete: **backend** (`senior-backend-dev`, following the backend overlay rule such as
`.claude/rules/fastapi-patterns.md`) and **frontend** (`senior-frontend-dev`, following the frontend
overlay rule such as `.claude/rules/react-patterns.md`). They run in parallel and reconcile at the
API contract; the DB specialist + migration specialist support the backend lane.

In **organization scope**, persona agents let non-engineers drive work safely: each plans and
clarifies in `plan` mode, then routes the actual implementation to the engineering agents — they never
write code themselves and require human approval before any change. They pair with the org skills
(`/feature-from-idea`, `/prototype-to-production`, `/customer-issue-to-fix`, `/prompt-to-safe-task`,
`/repo-onboarding`) and are governed by the autonomy and risk-classification rules. See
[`org-capabilities.md`](org-capabilities.md).

## The full roster

**28 specialized roles**, each tagged with a `tier` and installed per profile — plus per-database
**overlay agents** and, in organization scope, **persona agents**:

| Agent | Role |
|-------|------|
| `orchestrator` | Pipeline controller — decomposes, delegates, runs lanes in parallel, gates progression (never writes code) |
| `spec-doc-writer` | Turns requirements into a spec + developer documentation in one pass |
| `story-planner` | Decomposes an approved spec into ordered, parallelizable stories; verifies every acceptance criterion maps to a story (workflow gate 1f) |
| `ui-designer` | Drafts and self-reviews UI/UX design specs |
| `senior-backend-dev` · `senior-frontend-dev` | Senior review of a work stream's spec (the two-lane example) |
| `technical-architect` | Cross-system architecture, scalability, integration review |
| `em-reviewer` | Engineering-manager strategic & completeness review |
| `merge-reviewer` | Verifies consistency between parallel lanes at join points |
| `developer` | Writes production code from an approved spec, in an isolated worktree |
| `sdlc-code-reviewer` | Reviews code for bugs, security, performance, spec compliance |
| `unit-tester` · `e2e-tester` | Author unit and end-to-end test suites |
| `tester` · `senior-tester` | Integration testing and independent verification of coverage |
| `auditor` | Read-only audit for accessibility, performance, responsiveness, console errors |
| `devils-advocate` | Anti-sycophancy adversarial reviewer (runs on a unanimous PASS) |
| `acceptance-reviewer` | Verifies delivery against acceptance criteria before the human gate |
| `risk-classifier` | Read-only — classifies work low/medium/high/restricted and names the required gates (enterprise + org) |
| `security-reviewer` | Security stage coordinator — owns the Security Clear gate |
| `secret-scanner` · `dependency-scanner` · `owasp-reviewer` · `policy-validator` | The four parallel security sub-scanners |
| `devops-engineer` | CI/build/release, env, migrations, runbook — container-optional; owns Pipeline Green |
| `observability-engineer` | SLOs, health/readiness, structured logging, alerts — owns Observability Ready |
| `incident-responder` | Production-incident triage, mitigation, and postmortem (enterprise scope) |
| `pr-raiser` | Final checks, commit hygiene, and PR creation |
| **DB overlays** | installed for the selected database — PostgreSQL → `postgres-specialist` · `migration-specialist` · `db-performance-reviewer`; MongoDB → `mongodb-specialist` · `migration-specialist` |
| **Org personas** | `pm-copilot` · `founder-prototype-agent` · `support-ticket-engineer` · `data-workflow-agent` · `internal-tools-builder` · `staff-pm-reviewer` (organization scope only) |

## What a run costs (models per agent)

Every agent declares an explicit `model:` in its frontmatter; `.claude/rules/model-tiers.md` is the
assignment policy (and the escalation discipline when a task outgrows its tier). Measured from the
shipped frontmatter:

| Model | Relative cost / token | Shipped agents | Who |
|-------|-----------------------|----------------|-----|
| `opus` | highest — several × `sonnet` | **4** | `orchestrator`, `developer`, `devils-advocate`, `owasp-reviewer` (a documented exception to its `sonnet` sibling scanners) |
| `sonnet` | standard | **every other agent** | all reviewers, testers, scanners, stage leads, the DB overlay specialists, and the org personas |
| `haiku` | cheapest | **0** | the Fast tier is deliberately unassigned — reserved for genuinely mechanical, single-pass work |

What this means in practice:

- **The profile is the biggest cost knob.** lean ≈ 5 agents on a single lane, with only
  `orchestrator` + `developer` on `opus`; standard adds the spec/review/test/security lanes (all
  `sonnet`); enterprise adds ops/audit/acceptance — still only the same four `opus` agents. See
  "Profile cost expectations" in `.claude/rules/model-tiers.md`.
- **Fan-out is announced before it happens.** The orchestrator states the planned lane/agent counts
  and model tiers before forking a parallel phase — in chat and in `.claude/CONTINUITY.md` — so you
  can veto the scale before tokens are spent; in wave mode the manifest's per-wave worker counts
  serve the same purpose.
- **Escalation is deliberate, never reflexive.** Bumping an agent to a higher tier mid-run follows
  the investigation-first gate in `.claude/rules/model-tiers.md` — "maybe a smarter model will
  figure it out" is a listed anti-rationalization there.

## What keeps long runs reliable

- **Working memory — `.claude/CONTINUITY.md`.** The current phase, active tasks, and next steps are
  written every turn and re-read at the start of the next, so work survives context compaction and
  new sessions. Inspect it with `/claude-kit:status`.
- **Learnings — `.claude/agent-memory/`.** Durable lessons (gotchas, conventions, decisions) are
  captured via the `remember` skill and re-injected at the start of future sessions, so the same
  mistake isn't repeated. See `.claude/rules/agent-memory.md`.

## Tips

- **Be specific.** A one-line spec ("add X to the API and show it in the UI") gives the orchestrator
  strong success criteria and fewer clarifying questions.
- **Answer the gate questions.** The pipeline stops at ambiguous requirements, project-wide changes,
  and deploy choices — that's by design.
- **Customize the rules.** Stack conventions live in `.claude/rules/` and the "Project-specific
  rules" section of `CLAUDE.md`. Edit them and every agent follows the change.
- **Trust the gates.** If a gate fails, the orchestrator loops only the affected lane — let it.
