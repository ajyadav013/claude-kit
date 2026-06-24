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

## Resume snapshot (`.claude/state/pipeline-snapshot.json`)

`CONTINUITY.md` is the human-readable scratchpad; for a pipeline run it is paired with a small **structured snapshot** so a later session can re-enter precisely. The Orchestrator writes/updates it at every stage transition (alongside the `PIPELINE:` line it mirrors into **Current Phase**). It is gitignored runtime state under `.claude/state/` — created by the installer and ensured by the `load-continuity` SessionStart hook.

Schema (keep it small and truthful — omit a field rather than guess it):

```json
{
  "schema": 1,
  "task": "<one-line description of the run>",
  "profile": "lean | standard | enterprise",
  "scope": "individual | team | organization",
  "mode": "A | B | C | D",
  "stage": "<current PIPELINE stage label>",
  "lanes": { "<lane>": "not-started | in-progress | passed | failed" },
  "last_gate_passed": "<gate token, e.g. code-review>",
  "open_findings": { "critical": 0, "high": 0, "medium": 0 },
  "gate_evidence": { "<gate token>": "<path to the evidence artifact>" },
  "gate_overrides": { "<gate token>": "<why a blocking gate was force-closed>" },
  "next": "<the immediate next action>"
}
```

A gate is PASS only when zero **critical/high/medium** findings remain open (low/cosmetic may pass with notes). `gate_evidence` records the artifact backing each passed gate; `gate_overrides` is written **only** when a gate is deliberately force-closed despite open blocking findings, so a reviewer (or `claude-kit pipeline validate`) can surface and re-examine it.

**Resume by reloading, not by re-running.** On resume, read the snapshot as *context* to decide where to continue — then continue from there. Do **not** re-run setup that already ran, re-apply edits already committed, or re-open a gate already PASSed. Re-enter at the first gate *after* `last_gate_passed`, re-running only un-passed or defect-affected lanes. The snapshot records what was *true when written*, so the verify-before-trust check still applies (`.claude/rules/agent-memory.md`): if a "passed" gate's artifact is gone, treat it as not passed. If the snapshot is absent or unparseable, fall back to the freeform CONTINUITY state (back-compatible) and proceed.

## Concurrency

- There is exactly **one** live `.claude/CONTINUITY.md` per working directory. Two pipeline runs in the **same** checkout share it and will clobber each other's state — don't run concurrent `/sdlc` in one directory.
- To run pipelines **concurrently** on one repo, give each its own **git worktree** (the isolation primitive already used for parallel lanes in `.claude/rules/mandatory-workflow.md`). Each worktree is a separate checkout, so the `load-continuity.sh` SessionStart hook seeds it an independent `CONTINUITY.md` (it copies the template to `$ROOT/.claude/CONTINUITY.md` when absent).
- `agent-memory/` is the opposite by design: a single **shared, committed** store any session reads and contributes to (last-writer-wins on distinct kebab-case files; the `remember` skill dedups). It is intentionally **not** namespaced per branch — cross-run learnings pool on purpose.

## Protocol

**At the start of every turn / session / after compaction:**
1. Read `.claude/CONTINUITY.md`.
2. Read **Mistakes & Learnings** first — do not repeat past errors this session.
3. Check **Current Phase** and **Active Tasks**; resume from **Next Steps**.
4. Treat every entry as *last-known* state, not current truth: before acting on a note that names a file, command, or gate result, confirm it still holds (the verify-before-trust checks in `.claude/rules/agent-memory.md`).

**At the end of every turn, and at every pipeline stage transition:**
1. Update **Current Phase** and **Active Tasks**.
2. Move finished work to **Completed (this session)**.
3. Append any new **Decisions Made** and **Mistakes & Learnings**.
4. Rewrite **Next Steps** so the next turn can act with zero re-derivation.
5. Update **Modified Files** and **Test/Build Status**.

**Write CONTINUITY before** spawning or awaiting subagents, before a risky operation, and whenever context is getting long (pre-compaction insurance).

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

## Next Steps
1. [immediate next action]
2. [following action]

## Open Questions
- [needs human / other-lane resolution]

## Blocked Items
- [item]: [why blocked] — [unblock action]

## Modified Files
- [path] — [what changed]

## Test/Build Status
- [linter/formatter status]   [type checker status]   [test runner status]   [build status]
```

## Rules

1. **Keep it short.** Working memory, not a transcript. Overwrite stale content; do not append endlessly.
2. **Truthful state only.** If tests are failing, say so. CONTINUITY must never claim green when it isn't.
3. **Orchestrator owns the phase line.** Mirror the `PIPELINE:` state line into **Current Phase**.
4. **Promote, don't hoard.** Durable lessons go to `agent-memory/` via `remember`; CONTINUITY keeps only what this run needs.
5. **No secrets.** Same redaction rules as logging.
