---
name: sdlc
description: Run the autonomous SDLC pipeline on a task — the single entrypoint driving spec → review → build → test → security → delivery through the profile's quality gates. Use to run the SDLC or ship a feature.
argument-hint: <feature or task description>
---

# Autonomous SDLC

You are the **entrypoint** to claude-kit's autonomous software development lifecycle. The request to
handle is:

> $ARGUMENTS

Your job is to **delegate to the `orchestrator` agent** and let it drive the pipeline — you do not
implement the work yourself here. The orchestrator never writes code; it classifies the work,
sequences the phases, spawns the specialist agents, and enforces the gates.

## 1. Load the contract

Before doing anything, read:

- `CLAUDE.md` — the project's rules and the exact build/test/lint commands.
- `.claude/rules/mandatory-workflow.md` — the full phase pipeline and the defect loop.
- `.claude/rules/quality-gates.md` — ordinary PASS requires zero Critical/High/Medium; Medium can
  only use the distinct structured accepted-risk resolution; plus blind review/Devil's Advocate.
- `.claude/rules/rarv-cycle.md` — the Reason → Act → Reflect → Verify self-check every agent runs.
- `.claude/rules/wave-orchestration.md` — the program-mode contract (audit manifest, risk-ordered
  waves, disjoint boundaries, inventory approval) — required whenever the work classifies as
  program-scale.

Then read `.claude/CONTINUITY.md` (the `load-continuity` SessionStart hook has already printed it into
context). **Detect an in-progress run:** if **Current Phase** is not idle and **Active Tasks** names a
run matching `$ARGUMENTS`, an earlier pipeline is in flight. Prefer the **schema-v2 structured
snapshot** at `.claude/state/pipeline-snapshot.json`: run `claude-kit pipeline resume` and use its
ordered ledger/status as the precise resume index (schema in `.claude/rules/continuity.md`). The
freeform CONTINUITY state is context, not authority to forge a missing/invalid ledger. Tell the user
the last resolved gate, its resolution type, and the active lane(s), then ask whether to:

- **RESUME** — re-enter at the first unresolved gate, re-running only unresolved or defect-affected
  lanes; or
- **RESTART** — abort the active run explicitly, then create a fresh run from its first gate.

If **Current Phase** is idle (or CONTINUITY was freshly seeded), proceed as a fresh run.

## 2. Discover the active profile (this decides which gates run)

Read `.claude/config/stack-catalog.snapshot.yaml`. Its `gates:` and `agents:` lists are the
**authoritative set** of what the installed profile activated. Also read
`.claude/config/init-options.json` for the stack `selection` (frontend / backend / database) so you
point each lane at the right overlay rule.

- If either authoritative file is absent or unreadable, stop and require a supported
  `claude-kit` CLI install/upgrade. Do not guess a profile, gate set, or stack selection.

Run **only** the gates present in the snapshot's `gates:` list. The three profiles resolve to:

| Profile | Gates that run |
|---|---|
| **lean** | code-review · build-green |
| **standard** | spec-complete · em-approved · code-review · build-green · contract-clear · test-coverage · security-clear |
| **enterprise** | standard + pipeline-green · observability-ready · acceptance |

Never run a gate (or spawn its agent) that isn't in the active set — that's what makes lean fast and
enterprise thorough. Conversely, never skip a gate that *is* in the set.

## 3. Drive the pipeline

Spawn the `orchestrator` agent via the Agent tool with: the task ($ARGUMENTS), the active gate list,
and the stack selection. Instruct it to:

1. **Classify** the work — bug fix vs. feature; single-stream vs. parallel lanes (backend/frontend);
   fast-track (< 5 files) vs. full pipeline vs. **program-scale** (> ~20 files / multiple subsystems,
   or any irreversible step: production data, schema migration, deletion sweep). Fast-track collapses
   to the lean gate set regardless of profile. Program-scale work runs **Mode E — wave
   orchestration** per `.claude/rules/wave-orchestration.md`: parallel read-only audits → one frozen
   scope manifest (UNKNOWN = stop and ask) → risk-ordered waves with disjoint file boundaries →
   gate-runner agents between waves → inventory approval before irreversible steps → a knowledge
   closeout wave. (Where the session has Claude Code's native dynamic-workflows engine
   (≥ 2.1.154), a wave's fan-out may execute as one workflow run — the wave contract, gates, and
   human approvals are unchanged; see that rule's "Native dynamic workflows as the wave
   substrate".) Have the story planner tag each story (risk / batchable); low-risk stories inside
   a full run route through the reduced chain per `.claude/rules/risk-classification.md` →
   Story-level routing.
2. **Record** the plan/context in `.claude/CONTINUITY.md`, but create and mutate gate-precise state
   only through the schema-v2 lifecycle. Use `pipeline start --task ...` for fresh work or `adopt`
   with starting gate/reason/adopter for genuine pre-ledger work; use `resume` after interruption.
   Before resolving a gate, use `record-findings` with exact Critical/High/Medium/Low/Cosmetic
   counts plus a project-contained evidence report; start/adopt zeros are unrecorded placeholders.
   Record PASS with `close-gate <gate> --evidence <file>`, a catalog-authorized conditional result
   with `not-applicable <gate> --condition <id> --reason '<why>' --evidence <file>`, and each Medium
   exception with structured `accept-risk` fields. Critical/High have no waiver; accepted-risk is
   never PASS. Finish with `complete` (which persists the accepted risks in `final_summary`) or
   `abort`; a later start/adopt validates and hash-archives the terminal run automatically. Never
   hand-write `gate_history` or snapshot JSON. If the installed CLI lacks a required
   lifecycle command or a safe-path/lock write fails, report its version/error and block for repair
   or upgrade. On resume, re-enter at the first unresolved gate and never re-apply committed work.
3. **Route skills and models explicitly — and announce fan-out before spawning it.** Every agent
   the orchestrator spawns is told which skill(s) to load for its stage (the orchestrator's Skill
   Routing table; only skills actually installed under `.claude/skills/`) and runs on the model
   tier its work deserves (`.claude/rules/model-tiers.md`) — cheap for audits/scans, standard for
   build/review, top tier only for orchestration and hard reasoning. Before forking any parallel
   phase (review lanes, test lanes, security scanners, Mode E waves), it states the planned
   lane/agent count and model tiers in chat and records them in `.claude/CONTINUITY.md`, so the
   human can veto the scale before tokens are spent. Before the run's **first** fan-out, probe each
   planned model tier with one trivial spawn and fall back per `.claude/rules/model-tiers.md` →
   "Probe before fan-out".
4. **Run each active phase with its gate**, in order, using only the profile's agents:
   spec & dev-docs → story planning → **ticket creation + open the board** → (design, if UI) →
   senior/architect/EM review → implementation (one worktree per lane) → code review →
   unit + e2e tests → test-coverage merge → security clear → pipeline-green +
   observability-ready (enterprise) → acceptance (enterprise) → PR.
   At ticket creation the orchestrator runs `claude-kit tickets --open` **once** and reports the
   `file://` path, so the human can watch the run in a browser instead of reading chat for status.
   The `capture-ticket-telemetry` Stop hook keeps that page current for the rest of the run —
   creating the file is what switches the hook on.
5. **Enforce gates** with the `quality-gates.md` severity model and a green RARV Verify before each
   handoff. On a unanimous PASS, run the `devils-advocate` agent before the gate counts.
6. **Run the defect loop** when a gate fails: document, re-run only the affected lane(s), re-merge,
   re-test — never patch informally around the process.

If the `orchestrator` agent is unavailable in this session, act as the orchestrator yourself,
following the same steps.

### Story-group fan-out (optional, feature scale)

When the story breakdown yields **two or more immediately-startable story groups** (maximal
dependency-connected story sets with mutually disjoint file boundaries —
`.claude/rules/mandatory-workflow.md` §1f) and the run is not program-scale (Mode E), parallelize
across context windows instead of inside one: spawn **one orchestrator per group**, each in its
**own git worktree** per `.claude/rules/continuity.md` → Concurrency — each worktree carries its own
CONTINUITY.md, snapshot, and gate ledger, authoritative for that group's per-story gates. Announce
the scale first (N orchestrators × model tiers) so the human can veto it. Merge in dependency
order, one group at a time, with **human approval per mainline merge** (workers propose; humans
approve), then run the run-level gates — test-coverage across groups, security-clear on the merged
output — in the primary checkout, recorded in its ledger. A group that fails escalates per the
normal retry protocol; healthy groups still merge; a failed group's stories return to the backlog —
never merge a group whose gates didn't pass.

## 4. Stop for the human where required

Pause and ask the user at the points the workflow requires: ambiguous requirements, spec
confirmation, destructive or project-wide changes, and choice of deploy/release target. In the
enterprise profile, the **acceptance** gate hands off to a human before the PR is finalized.

## 5. Close the loop

When the active gates are green: summarize what shipped, list any open issues by severity, ensure
`.claude/CONTINUITY.md` reflects the final state, and promote any durable lessons with the
`remember` skill (into `.claude/agent-memory/`).

Re-print the board path (`.claude/state/ticket-board.html`) in that summary. By the end of a long
run the link from Stage TK is far up the scroll-back, and the finished board — every ticket DONE,
with its commits, files and per-agent token cost — is the artifact worth keeping.

Begin by confirming your classification, the active profile + gate set, and the stage plan — then
proceed.
