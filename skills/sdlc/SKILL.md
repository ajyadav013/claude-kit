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
- `.claude/rules/quality-gates.md` — the severity model (zero Critical/High/Medium to pass a gate)
  and the blind-review + Devil's Advocate protocol.
- `.claude/rules/rarv-cycle.md` — the Reason → Act → Reflect → Verify self-check every agent runs.

Then read `.claude/CONTINUITY.md` (the `load-continuity` SessionStart hook has already printed it into
context). **Detect an in-progress run:** if **Current Phase** is not idle and **Active Tasks** names a
run matching `$ARGUMENTS`, an earlier pipeline is in flight. Prefer the **structured resume snapshot**
at `.claude/state/pipeline-snapshot.json` when present — its `last_gate_passed`, `lanes`, and `next`
are the precise resume index (schema in `.claude/rules/continuity.md`); the freeform CONTINUITY state
(the mirrored `PIPELINE:` line) is the back-compatible fallback. Tell the user the **last PASSed gate**
and the active lane(s), then ask whether to:

- **RESUME** — re-enter the orchestrator at the first gate *after* the last passed one, re-running only
  un-passed or defect-affected lanes; or
- **RESTART** — reset **Current Phase** / **Next Steps** and begin again from spec.

If **Current Phase** is idle (or CONTINUITY was freshly seeded), proceed as a fresh run.

## 2. Discover the active profile (this decides which gates run)

Read `.claude/config/stack-catalog.snapshot.yaml`. Its `gates:` and `agents:` lists are the
**authoritative set** of what the installed profile activated. Also read
`.claude/config/init-options.json` for the stack `selection` (frontend / backend / database) so you
point each lane at the right overlay rule.

- If those files are absent (a minimal/no-pip install), fall back to the **standard** pipeline.

Run **only** the gates present in the snapshot's `gates:` list. The three profiles resolve to:

| Profile | Gates that run |
|---|---|
| **lean** | code-review · build-green |
| **standard** | spec-complete · em-approved · code-review · build-green · test-coverage · security-clear · contract-clear |
| **enterprise** | standard + pipeline-green · observability-ready · acceptance |

Never run a gate (or spawn its agent) that isn't in the active set — that's what makes lean fast and
enterprise thorough. Conversely, never skip a gate that *is* in the set.

## 3. Drive the pipeline

Spawn the `orchestrator` agent via the Agent tool with: the task ($ARGUMENTS), the active gate list,
and the stack selection. Instruct it to:

1. **Classify** the work — bug fix vs. feature; single-stream vs. parallel lanes (backend/frontend);
   fast-track (< 5 files) vs. full pipeline. Fast-track collapses to the lean gate set regardless of
   profile.
2. **Record** (or, **on resume**, update) the plan and state in `.claude/CONTINUITY.md` (working memory
   survives compaction — update it at every phase transition), and mirror the gate-precise state into
   the structured snapshot `.claude/state/pipeline-snapshot.json`. On resume, reload the snapshot as
   *context* and re-enter at the first gate *after* `last_gate_passed` — re-running only un-passed or
   defect-affected lanes, never re-running setup or re-applying committed edits.
3. **Run each active phase with its gate**, in order, using only the profile's agents:
   spec & dev-docs → story planning → (design, if UI) → senior/architect/EM review →
   implementation (one worktree per lane) → code review → unit + e2e tests → test-coverage merge →
   security clear → pipeline-green + observability-ready (enterprise) → acceptance (enterprise) → PR.
4. **Enforce gates** with the `quality-gates.md` severity model and a green RARV Verify before each
   handoff. On a unanimous PASS, run the `devils-advocate` agent before the gate counts.
5. **Run the defect loop** when a gate fails: document, re-run only the affected lane(s), re-merge,
   re-test — never patch informally around the process.

If the `orchestrator` agent is unavailable in this session, act as the orchestrator yourself,
following the same steps.

## 4. Stop for the human where required

Pause and ask the user at the points the workflow requires: ambiguous requirements, spec
confirmation, destructive or project-wide changes, and choice of deploy/release target. In the
enterprise profile, the **acceptance** gate hands off to a human before the PR is finalized.

## 5. Close the loop

When the active gates are green: summarize what shipped, list any open issues by severity, ensure
`.claude/CONTINUITY.md` reflects the final state, and promote any durable lessons with the
`remember` skill (into `.claude/agent-memory/`).

Begin by confirming your classification, the active profile + gate set, and the stage plan — then
proceed.
