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

## Protocol

**At the start of every turn / session / after compaction:**
1. Read `.claude/CONTINUITY.md`.
2. Read **Mistakes & Learnings** first — do not repeat past errors this session.
3. Check **Current Phase** and **Active Tasks**; resume from **Next Steps**.

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
