---
name: ticketing-and-traceability
description: Local git-native ticket store with a per-change work-log, a functional/technical/decision wiki, and ticket-to-commit linkage. Use when starting tracked work, recording what changed and why, or tracing a commit back to its reasoning.
---

# Ticketing and Traceability

## Overview

Every change should trace back to a ticket that says *why it happened*. This skill defines a
**local, git-native** ticket store that lives in the repo alongside the code — a ticket is created
before work starts, gains a **work-log** as work proceeds, links to the spec/design/decision docs
that justify it, and is referenced by the commits that implement it. The result is a spine you can
walk in either direction: from a line of code, `git blame` → commit → ticket → the reasoning; from a
requirement, ticket → commits → the code that satisfies it.

The store is plain Markdown + a small JSON index, committed with the code. No server, no database, no
external account is required. When the project *does* run an external tracker (GitHub Issues, Linear,
Jira), the local store stays the source of truth and `task-tracker-sync` optionally mirrors it out.

## When to Use

- Before implementing an approved story or change — open its ticket first.
- While implementing — append a work-log entry for each meaningful step (what changed, why, which
  files, what you decided).
- When committing — reference the ticket id so the commit traces back to its reasoning.
- When shipping — close the ticket and record the commits/PR against it.

**When NOT to use:** a throwaway experiment or a trivial one-line fix the team has agreed needs no
ticket. Don't spin up the store for a scratch prototype. To push tickets to an *external* tracker,
use `task-tracker-sync`; to record a *decision's* rationale, use `documentation-and-adrs` (this skill
links to those ADRs, it does not replace them).

## The local store

```
docs/project/
  tickets/
    <PREFIX>-<N>-<slug>.md     # one file per ticket
    index.json                 # machine-readable id -> {title, status, spec, commits[]}
  wiki/
    functional.md              # what the system does  -> docs/specs/*_spec.md (Part 1)
    technical.md               # how it works          -> _spec.md dev-docs + *_design-spec.md
    decisions.md               # why                   -> docs/decisions/*.md  (ADRs)
```

Create the tree on first use. Everything here is committed — the audit trail is part of history, not
a side channel.

### Ticket id scheme

`<PREFIX>-<N>`:

- **`PREFIX`** — a short uppercase token for the project, derived from the repository or product name
  (e.g. a repo `acme-billing` → `BILLING` or `ACME`). Pick it once and keep it stable; record it at
  the top of `index.json` so every run agrees.
- **`N`** — a sequential integer, allocated from `index.json` (the highest existing `N` plus one). The
  index is the allocator, so two tickets never collide.

The filename adds a human-readable slug: `BILLING-7-add-invoice-export.md`.

### Ticket lifecycle

```
OPEN  ->  IN PROGRESS  ->  IN REVIEW  ->  DONE
```

- **OPEN** — created before work starts (one per story).
- **IN PROGRESS** — an agent is implementing it; the work-log is accumulating.
- **IN REVIEW** — implementation is done and under code review / testing.
- **DONE** — merged; commits and PR recorded on the ticket.

A ticket only moves backward when work is reopened (a defect routed back). Never delete a ticket —
its history is the record.

## Ticket template

```markdown
# <PREFIX>-<N>: <title>

- **Status:** OPEN
- **Story:** <story id / link from the story breakdown, if any>
- **Spec:** docs/specs/<feature>_spec.md          (functional — what & why)
- **Design:** docs/specs/<feature>_design-spec.md (technical — how, if any)
- **Decisions:** docs/decisions/ADR-XXX.md         (any ADRs this change makes or depends on)
- **Files (declared scope):** path/one, path/two

## Why
One or two sentences: the need this change addresses and the outcome expected. Trace to the spec
requirement id(s) (R1, R2, …) where they exist.

## Decisions
Choices made while implementing that are not big enough for their own ADR (naming, a local trade-off,
an edge case handled a particular way). A decision expensive to reverse graduates to an ADR via
`documentation-and-adrs`, and is linked above.

## Work Log
- YYYY-MM-DD — <what changed> — why — files: <paths from `git diff --name-only`>
```

## The work-log discipline

The work-log is the "document every step" requirement. Append one entry per meaningful step — do not
overwrite, do not wait until the end. Each entry answers four questions:

1. **What** changed (the concrete edit, not "worked on the feature").
2. **Why** — the reason, so a reader six months later understands the intent.
3. **Which files** — taken from `git diff --name-only` against the last checkpoint, so scope is
   evidence, not memory. An out-of-scope file appearing here is a signal to check the change.
4. **What was decided** — any judgement call worth recording (promote to a Decision / ADR if it binds
   future work).

Keep entries terse and factual — this is a log, not an essay. The value is completeness and honesty,
not polish.

## The wiki (index, never duplicate)

The wiki is three thin **index** pages that point at documents the pipeline already produces — it does
not re-author them (that would fork the source of truth):

- **`functional.md`** — what the system does. Links each feature to Part 1 of its
  `docs/specs/*_spec.md` (authored by the spec writer).
- **`technical.md`** — how it works. Links to the developer-documentation part of
  `docs/specs/*_spec.md`, any `*_design-spec.md`, and architecture notes.
- **`decisions.md`** — why it is the way it is. Links to the ADRs under `docs/decisions/` (authored
  via `documentation-and-adrs`).

Update the relevant index when a ticket adds or changes one of those documents. The ticket itself
links the same three artifacts, so the wiki is a per-project roll-up and the ticket is a per-change
view of the same underlying docs.

## Linking tickets to commits

This is the "trace any change back to its reasoning" requirement, enforced by convention (see
`git-workflow-and-versioning`):

- **Every commit for a ticket names its id** in the subject or a footer:

  ```
  feat: add invoice export endpoint  [BILLING-7]
  ```

  A footer (`Ticket: BILLING-7`) works equally well — pick one and keep it consistent so
  `git log --grep='BILLING-7'` finds the whole change.
- **The ticket records its commits** — when work merges, write the commit hashes (and the PR URL)
  into the ticket's `index.json` entry and, if useful, the work-log. Now the link is navigable both
  ways: commit → ticket (via the message) and ticket → commits (via the index).

## Seeing the board

When the pip CLI is installed, `claude-kit tickets` renders the store as a live chart — one row per
ticket with its status, the agent and model that did the work, tokens, cache, and elapsed time, ordered
in-progress first. `--graph` shows the dependency graph (what is blocked by what), `--graph-git` walks
the commit graph with each commit's ticket attached, `claude-kit tickets <PREFIX>-<N>` opens one
ticket's detail with its full work log, and `--watch 5` re-renders while a run is in flight.

For a browser view, `claude-kit tickets --html` writes a Kanban board to
`.claude/state/ticket-board.html` and prints a `file://` URL. It is a plain file, not a server — the
page reloads itself and the Stop hook keeps it current, so it tracks progress live with nothing
running in the background.

Two conventions make those figures work, so record them:

- **Put the branch on the ticket** (`- **Branch:** feat/…`). Usage is attributed by branch; a ticket
  with no branch shows no telemetry. Tickets sharing a branch share its totals.
- **Declare dependencies in `index.json`** under `relations`: `depends_on` / `blocks` gate whether a
  ticket is workable and surface it as **BLOCKED**; `child_of` / `parent_of` express structure and
  deliberately do *not* gate. `relates_to` and `duplicates` are informational.

## Optional external mirror

The local store is always the source of truth. If the project runs an external tracker and wants the
tickets reflected there, hand off to `task-tracker-sync`: it reads the breakdown, reconciles against
the tracker idempotently, and creates/updates one issue per ticket. Put the external issue URL back on
the ticket so the two stay cross-linked. Nothing here depends on that mirror — a repo with no tracker
configured is fully functional on the local store alone.

## Where this runs in the pipeline

- **Ticket creation** happens after the personas approve the plan and the story breakdown passes its
  coverage gate, and *before* implementation agents are spawned — one OPEN ticket per story.
- **Work-log entries** are appended as each implementation lane is validated and lanes join.
- **Closure** happens at the PR stage: commits linked, status set to DONE.

For a lighter, single-change flow (a fast-track fix), the same discipline collapses to: open one
ticket, log the change, reference it in the commit, close it.

## Relationship to other skills

| Skill | Boundary |
|---|---|
| `story-planner` (agent) | Produces the stories; each story becomes one ticket here. |
| `documentation-and-adrs` | Owns decision *records* (ADRs). This skill *links* them from tickets and the decisions wiki; it never re-authors them. |
| `git-workflow-and-versioning` | Owns commit format. This skill adds the ticket-id linkage convention on top. |
| `task-tracker-sync` | Mirrors the local store to an *external* tracker on request. Local store stays authoritative. |
| `planning-and-task-breakdown` | Produces breakdowns when there is no `story-planner` run; its tasks map to tickets the same way. |

## Anti-patterns

- Starting to code before the ticket exists (no anchor for the work-log or the commit link).
- A work-log that says "made progress" — an entry with no what/why/files is not a record.
- Copying spec or ADR content into the wiki pages — they must **link**, or they drift.
- Inventing external issue URLs when no tracker is configured — mirror only when asked, via
  `task-tracker-sync`.
- Deleting or rewriting closed tickets — history is the point.

## Verification

- [ ] A ticket exists (status OPEN) before implementation started, one per story.
- [ ] Each ticket links its spec, design-spec (if any), and any ADRs.
- [ ] The work-log has an entry per meaningful step with what / why / files.
- [ ] Every commit references its ticket id; the ticket's `index.json` lists its commits.
- [ ] The three wiki pages index (do not duplicate) the specs and ADRs.
- [ ] Closed tickets are DONE with commits/PR recorded; none deleted.
