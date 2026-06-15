---
description: Abort the in-progress /sdlc run — remove only this run's worktrees and mark CONTINUITY aborted
argument-hint: "[reason]"
allowed-tools: Bash, Read, Edit
---

Cleanly abort the in-progress autonomous SDLC run in this project. There is **no destructive CLI** for
this by design — aborting is a guided, reversible cleanup you perform, never removing anything this run
did not create.

1. **Confirm a run is in progress.** Read `.claude/CONTINUITY.md` — check **Current Phase** /
   **Active Tasks** and the orchestrator's `PIPELINE:` line to see which lanes/worktrees this run
   created. If no run is in progress, say so and stop.
2. **List worktrees:** `git worktree list`. Identify **only** the worktrees this run created for its
   lanes (the `developer` lanes use the Agent tool's `isolation: "worktree"`). **Never** remove a
   worktree this run did not create, and never the primary checkout.
3. **Remove them:** `git worktree remove <path>` for each identified worktree. Unchanged worktrees are
   auto-cleaned by the Agent tool; this handles any that remain. Add `--force` **only** after telling
   the user exactly what uncommitted lane work would be lost and getting confirmation.
4. **Mark the run aborted:** append `ABORTED <date> — <reason from $ARGUMENTS>` under **Current Phase**
   in `.claude/CONTINUITY.md`, and reset **Active Tasks** / **Next Steps** so the next `/sdlc` starts
   fresh. (To merely *pause*, leave the `PIPELINE:` line intact so `/sdlc` can offer RESUME instead.)
5. **Report** what was removed and the final state. Do not touch the user's branches, commits, or other
   worktrees.

This is the counterpart to the worktree-teardown step in `orchestrator` Stage 7: use it when a run must
be cancelled mid-pipeline rather than completing to a PR.
