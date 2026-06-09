---
name: archive-sprint
description: Archive a completed sprint's planning docs and update the backlog status.
argument-hint: [backlog item number]
disable-model-invocation: true
---

Archive the completed sprint for backlog item #$ARGUMENTS.

## Steps

1. **Find the planning folder**: Look in `docs/planning/` for the directory corresponding to backlog item #$ARGUMENTS.

2. **Verify completion**: Check that the work is actually done:
   - Read the sprint plan and verify tasks are complete
   - Verify the Sprint Report section is filled in (Results, Metrics, What went well/wrong, Learnings, Unresolved). If missing, tell the user to write the post-sprint report first — do not archive without it.
   - Check if any new learnings should be added to `docs/reference/post-sprint-learnings.md`. If the sprint report has learnings not already captured there, append them.
   - Optionally run the project's build to confirm nothing is broken

3. **Move to archive**: Use `git mv` to move:
   - The scope doc → `docs/archive/plans/{slug}-scope.md`
   - The sprint plan → `docs/archive/sprints/{slug}-sprint.md`
   - Any other planning docs in the folder → `docs/archive/plans/`

4. **Update backlog**: Find the item in its horizon file (`docs/backlog/now.md`, `next.md`, or `later.md`) and move it to `docs/backlog/completed.md` with `Completed` status and the date. Update the item counts in `docs/backlog/README.md`.

5. **Clean up**: Remove the now-empty planning directory.

6. **Commit**: Stage all moved/modified files and commit with message: `backlog: complete #N — {Title}`

7. **Summarize**: Tell the user what was archived and confirm the backlog was updated.
