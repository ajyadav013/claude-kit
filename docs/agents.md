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
adds spec/EM/coverage/security; **enterprise** adds pipeline-green · observability-ready ·
acceptance. A **fast-track** path (bug fixes / < 5 files) skips planning: Developer → Code Reviewer →
Tester → PR.

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
| **Build** | `developer`, `sdlc-code-reviewer` (+ DB overlays: `postgres-specialist` / `mongodb-specialist`, `migration-specialist`) |
| **Test** | `unit-tester`, `e2e-tester`, `tester`, `senior-tester`, `auditor` |
| **Rigor** | `devils-advocate`, `acceptance-reviewer` |
| **Secure** | `security-reviewer` + `secret-scanner`, `dependency-scanner`, `owasp-reviewer`, `policy-validator` |
| **Ship** | `devops-engineer`, `observability-engineer`, `pr-raiser` |

In a scaffolded project with both a frontend and a backend stack, the two review/build lanes are
concrete: **backend** (`senior-backend-dev`, following the backend overlay rule such as
`.claude/rules/fastapi-patterns.md`) and **frontend** (`senior-frontend-dev`, following the frontend
overlay rule such as `.claude/rules/react-patterns.md`). They run in parallel and reconcile at the
API contract; the DB specialist + migration specialist support the backend lane.

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
