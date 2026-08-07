# Working Memory — CONTINUITY.md

Cross-session, cross-compaction working memory. The single source of truth for **"where am I right now."** Read at the start of every turn; written at the end. When a session hits its token limit or context is compacted, the next turn reads `CONTINUITY.md` and resumes exactly where work left off — no lost state.

## CONTINUITY vs. agent-memory

These are different systems. Do not conflate them.

| | `.claude/CONTINUITY.md` | `.claude/agent-memory/` |
|---|---|---|
| Holds | Current task state — phase, active work, next steps | Durable learnings — rules, gotchas, patterns |
| Lifespan | Ephemeral — overwritten as work progresses | Permanent — accumulates across all work |
| Scope | This feature / this pipeline run | The whole project, forever |
| Diff churn | High (changes every turn) — **gitignored** | Low — committed |
| Written by | Orchestrator + any long-running agent, every turn | `remember` skill + learning-detector hook |

When a CONTINUITY entry under **Mistakes & Learnings** is durable (a correction, convention, or hard-won insight that should outlive this task), promote it to `agent-memory/` via the `remember` skill. CONTINUITY is the scratchpad; agent-memory is the notebook.

## Location & lifecycle

- **Live file:** `.claude/CONTINUITY.md` — gitignored, local working state.
- **Seed:** `.claude/CONTINUITY.template.md` — committed. The `load-continuity.sh` SessionStart hook copies the template to the live file if the live file is missing, then prints it into context.
- Never commit the live file. Never store secrets, tokens, or credentials in it.

**This rule deliberately restates what the hook already does.** Ablation shows `load-continuity.sh`
is both necessary and sufficient for the file-observable half of this protocol: with the hook on,
the behaviour happens whether or not this rule is loaded. That makes the overlap look like dead
weight, and it is kept anyway — hooks are opt-out, can be disabled per project, are skipped by
harnesses that do not run SessionStart, and are the first thing removed when someone is debugging.
An install with no hooks still needs the resume contract to be *stated somewhere*, so the prose is
defence-in-depth rather than duplication. Read it as the contract; the hook is one implementation
of it, not the only one. Do not delete either on the grounds that the other covers it.

## Resume snapshot (`.claude/state/pipeline-snapshot.json`)

`CONTINUITY.md` is the human-readable scratchpad; for a pipeline run it is paired with a small **structured snapshot** so a later session can re-enter precisely. The Orchestrator writes/updates it at every stage transition (alongside the `PIPELINE:` line it mirrors into **Current Phase**). It is gitignored runtime state under `.claude/state/` — created by the installer and ensured by the `load-continuity` SessionStart hook.

Schema (keep it small and truthful — omit a field rather than guess it):

```json
{
  "schema": 1,
  "task": "<one-line description of the run>",
  "profile": "lean | standard | enterprise",
  "scope": "individual | team | organization",
  "mode": "A | B | C | D | E",
  "stage": "<current PIPELINE stage label>",
  "lanes": { "<lane>": "not-started | in-progress | passed | failed" },
  "last_gate_passed": "<gate token, e.g. code-review>",
  "open_findings": { "critical": 0, "high": 0, "medium": 0 },
  "gate_evidence": { "<gate token>": "<path to the evidence artifact>" },
  "gate_overrides": { "<gate token>": "<why a blocking gate was force-closed>" },
  "gate_history": [
    {
      "gate": "<gate token>",
      "status": "passed | skipped | overridden",
      "evidence_path": "<path relative to the project root (portable across checkouts); null for skipped>",
      "evidence_sha256": "<sha256 of the evidence file at close time>",
      "verification": "agent | mechanical | human | override",
      "recorded_at": "<UTC ISO timestamp>",
      "override": "<reason when force-closed, else null>",
      "reason": "<why a skipped gate does not apply (skipped entries only)>"
    }
  ],
  "git": { "branch": "<branch>", "sha": "<HEAD sha>", "worktrees": { "<lane>": "<path>" } },
  "pr": { "number": "<n>", "url": "<url>", "state": "<open|merged|closed>", "base": "<base>", "head": "<head>" },
  "next": "<the immediate next action>"
}
```

The optional `git` / `pr` objects are the run's **machine-derived identity anchors** — populate them
from commands (`git rev-parse --abbrev-ref HEAD`, `git rev-parse HEAD`, `git worktree list`, a
read-only `gh pr view`), **never from conversation memory**; omit any field you cannot prove. On
resume, compare `git.branch`/`git.sha` against a fresh `git rev-parse` **before touching anything** —
a mismatch means the checkout moved since the snapshot; stop and verify rather than acting on stale
state. (`abort` likewise treats `git.worktrees` as the authoritative list of what this run created.)

The sha comparison catches a checkout that *moved*; it cannot catch one that is **behind**. Snapshot
and CONTINUITY timestamps are self-reported — they can look fresh while commits have landed
out-of-band (another worktree, a teammate, CI). So on resume also verify **upstream currency**:
`git fetch`, then `git rev-list --left-right --count @{upstream}...HEAD` (left = commits behind,
right = ahead). **Behind** → the snapshot may describe state the remote has since changed;
reconcile (usually `git pull --rebase`) before trusting it. **Diverged** (both sides > 0) → stop
and reconcile before planning any new work on that tip. No upstream configured, or the fetch fails
offline → note it and continue; the check is advisory, never a hard stop. (Currency and staleness
checks adapted, in the kit's own terms, from the MIT-licensed
[`pborenstein/handoff`](https://github.com/pborenstein/handoff) `session-pickup` skill,
© 2026 Philip Borenstein.)

A gate is PASS only when zero **critical/high/medium** findings remain open (low/cosmetic may pass with notes). `gate_evidence` records the artifact backing each passed gate; `gate_overrides` is written **only** when a gate is deliberately force-closed despite open blocking findings, so a reviewer (or `claude-kit pipeline validate`) can surface and re-examine it.

`gate_history` is the **append-only ledger** behind those mirrors: gates close **in the installed
order** (the `gates:` list in `stack-catalog.snapshot.yaml` is execution-ordered; the first record
may anchor anywhere so a run can be adopted mid-flight), a conditional gate that doesn't apply is
recorded `skipped` with a reason (`claude-kit pipeline skip-gate`), and each closed entry carries
the evidence file's **sha256** — `validate` re-hashes every entry, so evidence cannot silently
change after its gate closed. `verification` records *how* the evidence was checked: `agent`
(a reviewer agent cited it — also the level for CLI-recorded skips), `mechanical` / `human`
(reserved for parsed evidence and explicit human sign-off), `override` (force-closed). Old
snapshots without `gate_history` stay valid. **Write ledger entries through the CLI whenever it
is on PATH** (`claude-kit pipeline close-gate <gate> --evidence <file>` / `skip-gate <gate>
--reason '<why>'`) — it enforces the order, refuses blocking findings, and hashes the evidence;
hand-append an entry per this schema only when the CLI is not installed.

**Resume by reloading, not by re-running.** On resume, read the snapshot as *context* to decide where to continue — then continue from there. Do **not** re-run setup that already ran, re-apply edits already committed, or re-open a gate already PASSed. Re-enter at the first gate *after* `last_gate_passed`, re-running only un-passed or defect-affected lanes. The snapshot records what was *true when written*, so the verify-before-trust check still applies (`.claude/rules/agent-memory.md`): if a "passed" gate's artifact is gone, treat it as not passed. If the snapshot is absent or unparseable, fall back to the freeform CONTINUITY state (back-compatible) and proceed.

## Concurrency

- There is exactly **one** live `.claude/CONTINUITY.md` per working directory. Two pipeline runs in the **same** checkout share it and will clobber each other's state — don't run concurrent `/sdlc` in one directory.
- To run pipelines **concurrently** on one repo, give each its own **git worktree** (the isolation primitive already used for parallel lanes in `.claude/rules/mandatory-workflow.md`). Each worktree is a separate checkout, so the `load-continuity.sh` SessionStart hook seeds it an independent `CONTINUITY.md` (it copies the template to `$ROOT/.claude/CONTINUITY.md` when absent).
- `agent-memory/` is the opposite by design: a single **shared, committed** store any session reads and contributes to (last-writer-wins on distinct kebab-case files; the `remember` skill dedups). It is intentionally **not** namespaced per branch — cross-run learnings pool on purpose.

## Protocol

**At the start of every turn / session / after compaction:**
1. Read `.claude/CONTINUITY.md`.
2. Read **Mistakes & Learnings** and **Attempted & Ruled Out** first — do not repeat past errors,
   and do not re-propose a ruled-out approach without new evidence.
3. Check **Current Phase** and **Active Tasks**; resume from **Next Steps**.
4. Treat every entry as *last-known* state, not current truth: before acting on a note that names a file, command, or gate result, confirm it still holds (the verify-before-trust checks in `.claude/rules/agent-memory.md`).

The `load-continuity.sh` hook warns when the live file hasn't been written for 7+ days. Treat such
state as **historical context**, not a current plan: verify it against `git log` / `git status`
(and the upstream-currency check above) before resuming from its **Next Steps**.

**At the end of every turn, and at every pipeline stage transition:**
1. Update **Current Phase** and **Active Tasks**.
2. Move finished work to **Completed (this session)**.
3. Append any new **Decisions Made** and **Mistakes & Learnings** — and record dead-ends in
   **Attempted & Ruled Out** (approach → why ruled out): an approach that failed *this session* is
   exactly what the next session will otherwise re-suggest.
4. Rewrite **Next Steps** so the next turn can act with zero re-derivation.
5. Update **Modified Files**, **Repo State** (from commands — `git rev-parse`, `git status` — never
   from memory), and **Test/Build Status**.

**Write CONTINUITY before** spawning or awaiting subagents, before a risky operation, and whenever context is getting long (pre-compaction insurance).

## Size budget & rotation (hot state vs. cold archive)

`CONTINUITY.md` is **hot state**, and hot state has a hard budget: keep the live file under
**~8,000 bytes (~150 lines)** — the size the `load-continuity.sh` SessionStart hook injects
**uncut**. Past that, the hook still fires but trims the *middle* of the file out of the
injection — and the middle is where **Decisions Made** and **Mistakes & Learnings** sit, so an
over-budget file silently mutilates exactly the sections resume depends on. The read-side trim is
the safety net, not the mechanism. The mechanism is writing small.

When a phase completes — or the file nears the budget — **rotate, don't let the hook trim**:

1. Compress the finished phase to 3–5 lines under **Completed (this session)**: outcome, key
   decisions by one-line reference, where the evidence lives (artifact path / commit / PR).
2. Move the displaced detail to `.claude/state/continuity-archive.md` — an **append-only cold
   file** in the gitignored runtime-state dir the hook already ensures exists. It is never
   injected into context; open it on demand when an archived detail is actually needed.
3. The archive is spillover for *run history only* — durable lessons still promote to
   `agent-memory/` (Rule 4), decisions of record still become ADRs, and neither store is
   duplicated into it.

The test, after rotating: the live file alone still passes both probes below. If the next session
would need the archive just to answer "where am I," you rotated too much. (Hot/cold rotation
adapted, in the kit's own terms, from the MIT-licensed
[`pborenstein/handoff`](https://github.com/pborenstein/handoff) `project-tracking` skill,
© 2026 Philip Borenstein.)

## Template

```markdown
# CONTINUITY — Working Memory

## Current Phase
[Pipeline stage + mode, e.g. "Mode B / Fork 2 — implementation"]

## Active Tasks
- [id]: [description] — [status]

## Completed (this session)
- [id]: [description]

## Decisions Made
- [decision] — [rationale]

## Mistakes & Learnings
- [what went wrong] -> [what we learned]  (promote durable ones to agent-memory)

## Attempted & Ruled Out (this session)
- [approach] — [why ruled out; do not re-propose without new evidence]

## Next Steps
1. [immediate next action]
2. [following action]

## Open Questions
- [needs human / other-lane resolution]

## Blocked Items
- [item]: [why blocked] — [unblock action]

## Modified Files
- [path] — [what changed]

## Repo State (from commands, never from memory)
- branch: [git rev-parse --abbrev-ref HEAD]   HEAD: [short sha]   dirty: [n files]
- PR: [number/url/state, when one exists]

## Test/Build Status
- [linter/formatter status]   [type checker status]   [test runner status]   [build status]
```

## Probe the summary before you rely on it

A CONTINUITY entry is only worth what the *next* turn can reconstruct from it. Before you hand off — at
the end of a turn, before spawning/awaiting subagents, and especially as pre-compaction insurance —
test the summary against two anchor questions, reading **only** what you wrote:

1. **Progress probe** — "From this alone, what is done and what is the task's exact current state?"
2. **Gap probe** — "From this alone, what specific information is still needed to finish?"

A summary passes when the progress answer is **specific and verifiable** (named files/gates/decisions,
no hedging like "some work was done") and the gap answer is a **bounded, concrete list** of named
unknowns. It fails when the progress answer hedges or the gap answer expands into open-ended
categories — that means the summary won't survive the next turn and must be sharpened *now*, while you
still hold the context.

| Progress answer | Gap answer | Verdict |
|-----------------|-----------|---------|
| Specific | Bounded | **Ready** — hand off |
| Specific | "nothing needed" but task is unfinished | **Suspect** — re-read the task; the memory has drifted |
| Hedged / vague | anything | **Rewrite** — expand with explicit answers to both probes before handing off |

The two probes catch different failures: the gap probe alone misses a *confident-but-wrong* belief
about state; the progress probe catches it. This is the same standard as Rule 2 below — truthful state
— applied *before* the handoff rather than after. (Dual-probe pattern adapted, stack-agnostic, from
the MIT-licensed [`athola/claude-night-market`](https://github.com/athola/claude-night-market)
`memory-clarity-probe` skill, © 2025 athola.)

## Rules

1. **Keep it short.** Working memory, not a transcript. Overwrite stale content; do not append endlessly — stay under the size budget above and rotate completed detail to the archive.
2. **Truthful state only.** If tests are failing, say so. CONTINUITY must never claim green when it isn't.
3. **Orchestrator owns the phase line.** Mirror the `PIPELINE:` state line into **Current Phase**.
4. **Promote, don't hoard.** Durable lessons go to `agent-memory/` via `remember`; CONTINUITY keeps only what this run needs.
5. **No secrets.** Same redaction rules as logging.
