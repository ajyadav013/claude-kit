---
name: task-tracker-sync
description: Mirrors an existing task or story breakdown into the project's issue tracker as issues, preserving dependencies. Use after planning/story breakdown when the user wants the plan pushed to GitHub / Linear / Jira (e.g. "create issues for these tasks", "sync the plan to the tracker"). Does not create the breakdown — it syncs one that already exists.
---

# Task Tracker Sync

## Overview

Turn a finished plan into tracked work. Given a task or story breakdown that **already exists**
(from `planning-and-task-breakdown`, the `story-planner` agent, or a plan document), create one
issue per task in whatever issue tracker the project has configured, carrying the dependency graph
across so the tracker mirrors the plan instead of a flat dump of tickets.

This skill **consumes** a breakdown; it never invents one. If no plan exists yet, run
`planning-and-task-breakdown` (or the `story-planner` agent) first, then sync its output.

## When to Use

- A plan / story breakdown is approved and the user wants it in the tracker for execution.
- The user says "create issues for these tasks", "open tickets", "push this to Linear/Jira/GitHub".
- Stories from the workflow's stage 1f (Story Planner) need tracker counterparts before lanes start.

**When NOT to use:** there is no breakdown yet (plan first); a single throwaway task; or the user
only wants a local checklist, not tracker issues.

## Tracker-agnostic by design

claude-kit does not assume a tracker. Use whichever **issue-tracker MCP server** is configured for
the project (see `.mcp.json` / the catalog): GitHub, Linear, Jira, or another. Discover the
tracker's create/update tools at run time and use them — never hardcode one vendor's API.

If **no** tracker MCP is configured: stop and say so. Offer to (a) emit the issues as a Markdown
checklist the user can paste, or (b) wait until a tracker is set up. Do not fabricate issue URLs.

## The Sync Process

1. **Read the breakdown.** Load the plan/story file. For each task capture: title, body (the
   description + acceptance criteria + verification steps + files-touched), a stable local id, and
   its `blockedBy`/`blocks` dependencies. Reference the spec requirement ids (R1, R2…) in the body
   so each issue traces back to the spec.
2. **Detect the tracker.** Identify the configured issue-tracker MCP and the fields it supports
   (labels, milestones, parent/child, issue links / "blocks" relations).
3. **Reconcile before creating (idempotent).** Search the tracker for existing issues matching each
   task (by a stable marker in the title or body, e.g. the story id). **Update** a match; **create**
   only what's genuinely missing. Re-running the sync must not produce duplicates.
4. **Create issues** for the unmatched tasks: title, structured body, and any labels the project
   uses. Record the new issue id/URL against the local task id.
5. **Wire dependencies.** Once every task has a tracker id, translate `blockedBy`/`blocks` into the
   tracker's native relation (issue links, task lists, or parent/child). If the tracker can't express
   a relation, note it in the issue body ("Blocked by #N") rather than dropping it.
6. **Report.** A table of local task id → issue URL → created|updated, plus any dependency links
   made and anything that needs manual attention.

## Constraints

- **Confirm before writing.** Creating tracker issues is an outward-facing action — show the user
  what will be created/updated and how many, and get a go-ahead before the first write, unless they
  already said "just do it".
- **Idempotent.** Match-then-update; never blind-create. A second run is a no-op when nothing changed.
- **Faithful, not creative.** Sync the tasks as written. Don't reword acceptance criteria, split,
  merge, or add tasks here — that's the planner's job. Round-trip changes through the plan, then
  re-sync.
- **No secrets.** Never put credentials or tokens in issue bodies. Tracker auth comes from the MCP
  server's configured env vars, not from anything you write.

## Verification

- [ ] Every task in the breakdown has exactly one corresponding tracker issue (no duplicates).
- [ ] Dependencies are represented in the tracker (native links) or explicitly noted in bodies.
- [ ] Each issue body traces to its spec requirement id(s) and lists acceptance criteria.
- [ ] A re-run reports all "updated"/"unchanged" — zero accidental new issues.
