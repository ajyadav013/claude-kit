# Using the claude-kit agents

claude-kit installs a team of focused agents plus an **orchestrator** that runs them through a
software-delivery pipeline with a quality gate between phases. Canonical agent definitions are
provider-neutral; the compiler emits Claude project-agent Markdown or Codex project-agent TOML.

> Prerequisite: scaffold the project with `ckit init --runtime claude|codex|both`. Which agents are
> present depends on the selected **profile** (`lean ⊊ standard ⊊ enterprise`). Restart Claude Code
> after scaffolding; reopen and trust a Codex project before relying on its hooks.
>
> **Permission models are not equivalent.** Claude projection maps semantic permission classes to
> supported `permissionMode` values. Codex projection preserves permission and write-scope intent in
> `developer_instructions`, while Codex sandbox/approval policy remains authoritative. Protected
> live-host proof of equivalent per-agent confinement is still a Preview gap. Static plugins are
> narrower than project scaffolds and should not be used as evidence of that confinement.

## Two ways to invoke

### 1. Run the whole pipeline (recommended)

Claude Code:

```text
/sdlc <describe the feature or bug>
```

Codex Preview:

```text
$sdlc <describe the feature or bug>
```

The `sdlc` skill is the entrypoint; it reads your profile's active gate set and either invokes the
Preview managed executor or, with explicit acknowledgement, uses the manual orchestrator
path. Both route the named roles through review → implementation → testing → security → delivery,
enforce gate checkpoints, and pause at genuine decision points. (From the plugin,
`/claude-kit:sdlc` does the same.) Use this for anything non-trivial.

Examples below use Claude syntax; replace `/sdlc` with `$sdlc` in Codex:

```text
/sdlc Add a "completed" flag to items: API field + a checkbox in the UI
/sdlc Fix the 500 when creating an item with an empty title
/sdlc Add pagination to the items list endpoint and the table
```

Check progress any time with `/claude-kit:status` in the Claude plugin or `ckit status` on either
scaffold (reads the shared working memory).

For an explicit managed invocation, first start the ledger, then run
`CKIT_EXPERIMENTAL=1 ckit pipeline run --provider claude|codex` with the task's surface conditions.
It freezes the workflow and gate-owner contract, checkpoints at each gate, and can resume through
the other installed host without rerunning completed stages. The integration worktree is preserved
for a human-reviewed merge; it is never merged automatically. The portable subprocess adapters do
not attest containment of a deliberately detached descendant. A shell-capable Claude role
therefore human-stops before it starts. The bundled Codex adapter can run only a passive read-only,
nondelegating role after an exact pinned-host lockdown probe disables all local command and
extension surfaces; the role receives a bounded, filtered tracked-text projection. Any Codex role
requiring shell, write, delegation, browser, MCP, or external effects still stops before spawn. Use
the explicitly acknowledged manual path or an independently contained backend for those roles.
Mode E requires an explicit frozen `--program-manifest` and binds its waves, units, budgets,
evidence, program gates, attempts, and checkpoints into the same `.ckit` ledger. Pure read/search
audit units can run on the bundled adapters. Shell/write/gate units require an independently
attested physical-boundary backend, and irreversible units stop before claim because no external
approval broker is integrated. Managed approval cannot resume either stop; only rejection for
replan/abort is recorded.

### 2. Invoke a single agent

For a focused task, ask the host to use one agent by name — no full pipeline:

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
observability-ready · acceptance (contract-clear uses evidenced `not-applicable` on stacks with no API contract surface, so
it is inert for non-API projects). A **fast-track** path (bug fixes / < 5 files) skips planning:
Developer → Code Reviewer → Tester → PR.

Every gate uses the same severity model — a gate passes only with **zero Critical/High/Medium**
findings open — and a *unanimous* PASS triggers the `devils-advocate` agent before the gate counts
(anti-sycophancy). Read `.claude/rules/quality-gates.md` in a Claude scaffold or the complete Codex
projection at `.ckit/rules/quality-gates.md`. The Python ledger under `.ckit/state/` is the
enforcement authority; instructions and hooks are guardrails.

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
| **Rigor** | `risk-classifier` (all profiles), `devils-advocate`, `acceptance-reviewer` |
| **Secure** | `security-reviewer` + `secret-scanner`, `dependency-scanner`, `owasp-reviewer`, `policy-validator` (static) + `pentest-scanner` (optional dynamic pentest — Strix / Shannon / PentesterFlow / ZAP) |
| **Ship** | `devops-engineer`, `observability-engineer`, `pr-raiser`, `incident-responder` (enterprise) |
| **Org personas** | `pm-copilot`, `founder-prototype-agent`, `support-ticket-engineer`, `data-workflow-agent`, `internal-tools-builder` (organization scope only) |

In a scaffolded project with both a frontend and a backend stack, the two review/build lanes are
concrete: **backend** (`senior-backend-dev`, following the selected backend overlay rule) and
**frontend** (`senior-frontend-dev`, following the selected frontend overlay rule). Claude keeps
those rules under `.claude/rules/`; Codex keeps their complete projections under `.ckit/rules/` and
loads a bounded managed layer through `AGENTS.md`. The lanes run in parallel and reconcile at the
API contract; the DB specialist + migration specialist support the backend lane.

In **organization scope**, persona agents let non-engineers drive work safely: each plans and
clarifies in `plan` mode, then routes the actual implementation to the engineering agents — they never
write code themselves and require human approval before any change. They pair with the org skills
(`/feature-from-idea`, `/prototype-to-production`, `/customer-issue-to-fix`, `/prompt-to-safe-task`,
`/repo-onboarding`) and are governed by the autonomy and risk-classification rules. See
[`org-capabilities.md`](org-capabilities.md).

## The full roster

**29 specialized roles**, each tagged with a `tier` and installed per profile — plus per-database
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
| `risk-classifier` | Read-only — classifies work low/medium/high/restricted and names the required gates (all profiles) |
| `security-reviewer` | Security stage coordinator — owns the Security Clear gate |
| `secret-scanner` · `dependency-scanner` · `owasp-reviewer` · `policy-validator` | The four parallel **static** security sub-scanners |
| `pentest-scanner` | Optional **dynamic** sub-scanner — runs a real, PoC-validated penetration test via Strix / Shannon / PentesterFlow / ZAP; conditional + authorization-gated, non-blocking when skipped |
| `devops-engineer` | CI/build/release, env, migrations, runbook — container-optional; owns Pipeline Green |
| `observability-engineer` | SLOs, health/readiness, structured logging, alerts — owns Observability Ready |
| `incident-responder` | Production-incident triage, mitigation, and postmortem (enterprise scope) |
| `pr-raiser` | Final checks, commit hygiene, and PR creation |
| **DB overlays** | installed for the selected database — PostgreSQL → `postgres-specialist` · `migration-specialist` · `db-performance-reviewer`; MongoDB → `mongodb-specialist` · `migration-specialist` |
| **Org personas** | `pm-copilot` · `founder-prototype-agent` · `support-ticket-engineer` · `data-workflow-agent` · `internal-tools-builder` · `staff-pm-reviewer` (organization scope only) |

## Model tiers and cost

Canonical agents declare a semantic tier — `fast`, `balanced`, or `deep` — rather than a provider
model name. The current roster assigns four deep roles (`orchestrator`, `developer`,
`devils-advocate`, and `owasp-reviewer`), balanced to the remaining roles, and no fast role.

| Projection | Mapping |
|---|---|
| Claude Code | The renderer maps semantic tiers to the native `haiku` / `sonnet` / `opus` aliases. |
| Codex Preview | Generated agent TOML deliberately contains no hard-coded model. The active Codex runtime selects the model; tier intent remains in the role instructions. |

Therefore the profile and fan-out are the reliable cross-provider cost controls; a provider-to-
provider price comparison is not. The orchestrator announces lane/agent counts and tier intent before
forking a parallel phase and records it in `.ckit/CONTINUITY.md`, so you can veto the scale. Tier
escalation follows the investigation-first policy in the installed `model-tiers` rule.

## What keeps long runs reliable

- **Working memory — `.ckit/CONTINUITY.md`.** The current phase, active tasks, and next steps are
  written and re-read so work survives context compaction and new sessions. Inspect it with
  `ckit status`, or `/claude-kit:status` from the Claude plugin.
- **Learnings — `.ckit/agent-memory/`.** Durable lessons (gotchas, conventions, decisions) are
  captured via the `remember` skill and re-injected at the start of future sessions, so the same
  mistake is not repeated. Capture is opt-in and differs by host; see [Security](../SECURITY.md).
- **One ledger for both hosts.** A dual-runtime project has one `.ckit/state` gate history. Claude
  and Codex do not maintain competing progress files.

## Tips

- **Be specific.** A one-line spec ("add X to the API and show it in the UI") gives the orchestrator
  strong success criteria and fewer clarifying questions.
- **Answer the gate questions.** The pipeline stops at ambiguous requirements, project-wide changes,
  and deploy choices — that's by design.
- **Customize through supported project surfaces.** Claude project instructions live in
  `CLAUDE.md`; Codex project instructions live in managed sections of `AGENTS.md`. Generated
  canonical rule projections are upgrade-owned, so use the edit-preserving workflow and review
  `ckit diff` rather than creating provider-specific source forks.
- **Trust the gates.** If a gate fails, the orchestrator loops only the affected lane — let it.
