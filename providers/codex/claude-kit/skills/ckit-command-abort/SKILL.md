---
name: ckit-command-abort
description: Abort the in-progress SDLC run, terminate its authoritative snapshot, and clean only its worktrees
---

Cleanly abort the in-progress autonomous SDLC run in this project. The authoritative lifecycle
transition is `ckit pipeline abort`; worktree cleanup remains guided and must never remove
anything this run did not create.

1. **Confirm a run is in progress.** Run `ckit pipeline status` and read
   `.ckit/CONTINUITY.md`. The schema-v2 snapshot is authoritative for lifecycle status; CONTINUITY
   supplies human context and the orchestrator's `PIPELINE:`/lane notes. If there is no active run,
   say so and stop.
2. **List worktrees:** `git worktree list`. Identify **only** the worktrees this run created for its
   lanes (the `developer` lanes use the delegation tool's `isolation: "worktree"`). When
   `.ckit/state/pipeline-snapshot.json` records a `git.worktrees` map, treat it as the
   authoritative list of what this run created (cross-check each path against `git worktree list`);
   fall back to the CONTINUITY prose only when the snapshot lacks it. **Never** remove a
   worktree this run did not create, and never the primary checkout.
3. **Remove them:** `git worktree remove <path>` for each identified worktree. Unchanged worktrees are
   auto-cleaned by the delegation tool; this handles any that remain. Add `--force` **only** after telling
   the user exactly what uncommitted lane work would be lost and getting confirmation.
4. **Terminate the authoritative run:** run `ckit pipeline abort`. It atomically marks the
   schema-v2 snapshot `status: aborted`, records `aborted_at`, and makes the run terminal. If this
   command fails, report the path/error as **BLOCKED** and do not hand-edit snapshot JSON. Then mirror
   `ABORTED <date> — <reason from the invocation request>` under **Current Phase** in `.ckit/CONTINUITY.md`, and
   reset **Active Tasks** / **Next Steps**. A later `pipeline start`/`adopt` archives this terminal
   snapshot before creating the next run. (To merely *pause*, do not abort; leave the `PIPELINE:`
   line intact so the `sdlc` skill can offer RESUME instead.)
5. **Report** what was removed and the final state. Do not touch the user's branches, commits, or other
   worktrees.

This is the counterpart to the worktree-teardown step in `orchestrator` Stage 7: use it when a run must
be cancelled mid-pipeline rather than completing to a PR.
