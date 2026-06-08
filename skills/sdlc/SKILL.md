---
name: sdlc
description: Run the autonomous SDLC pipeline on a task — the single entrypoint that drives spec → review → build → code review → test → security → delivery through the profile's quality gates. Use when asked to "run the SDLC", build/ship a feature end to end, or take a task through the full pipeline with gates.
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
| **standard** | spec-complete · em-approved · code-review · build-green · test-coverage · security-clear |
| **enterprise** | standard + pipeline-green · observability-ready · acceptance |

Never run a gate (or spawn its agent) that isn't in the active set — that's what makes lean fast and
enterprise thorough. Conversely, never skip a gate that *is* in the set.

## 3. Drive the pipeline

Spawn the `orchestrator` agent via the Agent tool with: the task ($ARGUMENTS), the active gate list,
and the stack selection. Instruct it to:

1. **Classify** the work — bug fix vs. feature; single-stream vs. parallel lanes (backend/frontend);
   fast-track (< 5 files) vs. full pipeline. Fast-track collapses to the lean gate set regardless of
   profile.
2. **Record** the plan and initial state in `.claude/CONTINUITY.md` (working memory survives
   compaction — update it at every phase transition).
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
