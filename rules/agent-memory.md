# Agent Memory System

Claude maintains a project-scoped knowledge base in `.claude/agent-memory/` that persists learnings across sessions. This memory is shared — any Claude session working in this project can read and contribute.

## The memory taxonomy (where each kind lives)

Agents use four kinds of memory; this kit splits them across two systems — don't conflate them (see `.claude/rules/continuity.md`).

| Kind | What it is | Where it lives here |
|------|-----------|---------------------|
| **Working** (short-term) | The current task's state — phase, active work, next steps | `.claude/CONTINUITY.md` — ephemeral, this run only |
| **Episodic** | What happened before — incidents, hard-won fixes, surprises | `agent-memory/debugging/`, `agent-memory/gotchas/` |
| **Semantic** | Durable facts & decisions — conventions, architecture, API behavior | `agent-memory/architecture/`, `api/`, `patterns/`, `performance/` |
| **Procedural** | How to do things — repeatable workflows and disciplines | the `.claude/rules/*` and `.claude/skills/*` themselves — and episodic/semantic clusters **graduate here**: when 3+ learnings in a category encode one repeatable procedure (or one learning proves out 3+ times), the `consolidate-learnings` skill's Promote step turns them into a project-local skill/rule |

Working memory is the scratchpad (overwritten constantly); the rest is the notebook (accumulates). Promote a durable CONTINUITY learning into the right `agent-memory/` category via the `remember` skill. Capture is automatic — the `capture-learnings` hook records (in a non-blocking background job) what Claude changed/learned from its own work. How often it fires is the init-time `capture_mode` choice (off · on clean exit · + a SessionStart catch-up for sessions closed abruptly · per task); it routes through the `remember` skill.

## When to READ memory

- **At the start of every task**: Read `.claude/agent-memory/MEMORY.md` to see what's been learned
- **Before debugging**: Check `debugging/` and `gotchas/` for known issues
- **Before architectural decisions**: Check `architecture/` for prior decisions and reasoning
- **Before working with APIs**: Check `api/` for integration notes

## Memory hygiene — verify, scope, reconcile

Recalled memory is a claim about how things *were when it was written*, not a guarantee about now. Apply three checks before you rely on one:

- **Verify before trust.** When an entry names a concrete file, function, flag, command, or endpoint, confirm it still exists (a quick Read / Grep / Bash) before acting on it. If reality has moved — the file was renamed, the flag removed, the behavior changed — the entry is stale: correct it or remove it (see **Maintenance**), and don't propagate the outdated claim.
- **Attach selectively, and cite the source.** Pull in only the entries whose `trigger` / `Apply when` matches the task at hand — not the whole store. When a learning shapes a decision, name the entry it came from (e.g. "per `agent-memory/gotchas/<file>.md`") so the reasoning is traceable and a wrong memory can be found and fixed.
- **Committed instructions win.** When a memory conflicts with `CLAUDE.md` or a rule under `.claude/rules/`, the committed project instruction is authoritative — follow it, and flag or update the contradicting memory. Memory captures what was *learned*; the rules are what the project has *decided*.

## When to WRITE memory

Save a memory when you learn something that:
1. **Would save future sessions time** — a non-obvious fix, a subtle API behavior, a tricky configuration
2. **Cannot be derived from code alone** — the "why" behind a decision, context that isn't in comments
3. **Was surprising or hard-won** — debugging insights that took multiple attempts to discover

### Do NOT save
- Code patterns visible in the codebase (read the code instead)
- Standard framework behavior (check docs instead)
- Temporary task state (use tasks instead)
- Things already in CLAUDE.md or other rules files

## How to WRITE memory

### Step 1: Create the memory file

Write to the appropriate category folder:

| Category | Folder | What goes here |
|----------|--------|---------------|
| Architecture Decisions | `architecture/` | Why we chose X over Y, structural decisions |
| Debugging Insights | `debugging/` | Root causes of tricky bugs, non-obvious failure modes |
| Project Patterns | `patterns/` | Recurring patterns specific to this project |
| API & Integration | `api/` | API quirks, auth flows, endpoint behaviors |
| Performance | `performance/` | Optimization discoveries, bottleneck insights |
| Gotchas & Pitfalls | `gotchas/` | Things that look right but aren't, common mistakes |

File format (canonical — the `remember` skill, the `capture-learnings` hook, and the
`consolidate-learnings` skill all write/expect exactly this shape):
```markdown
---
title: {{descriptive title}}
category: {{category name}}
date: {{YYYY-MM-DD}}
trigger: {{when this applies — e.g. "designing any UI", "writing an HTTP endpoint"}}
---

## Context
{{What situation led to this learning}}

## Learning
{{The key insight — a clear, actionable directive: what to do (or avoid) and why}}

## Evidence
{{How this was discovered — error messages, debugging steps, etc.}}

## Apply when
{{Concrete signal that this learning is relevant to the current task}}

## Related   <!-- optional -->
- [other entry](../category/file.md) — why it's connected
```

Writing style: plain factual voice; state only what the evidence supports (and say how you know);
match depth to the subject — a small remembered fact stays a few lines.

### Step 2: Update the index

Add a one-line entry to `.claude/agent-memory/MEMORY.md` under the appropriate category:
```markdown
- [Title](category/filename.md) — one-line hook
```

## Record the *why*, not just the *what*

The durable value of a memory is the **rationale**, not the outcome — outcomes are visible in the code,
but the reasoning behind a decision is the part that's lost when a person (or session) moves on. When
you write to `architecture/` or `patterns/`, capture the **decision trace**, not just the conclusion:

- **what** was decided, **why** (the reasoning), **what alternatives were rejected** and why, and a
  pointer (PR, file, issue) — roughly `{decision, why, rejected-alternatives, refs, date}`.
- A memory that says *"we use X"* is weak; *"we chose X over Y because Z, see PR #123"* lets a future
  agent inherit the **judgment**, defend the decision, and know when it no longer applies.

This is why the file template above leads with **Context** — fill it and **Learning** with reasoning,
not a restatement of the title.

> Source: "Context Graphs — building persistent memory for the agentic enterprise" (decision traces as
> the system of record). Paraphrased for this kit.

## File naming

Use lowercase kebab-case: `state-selector-infinite-loop.md`, `auth-token-refresh-race.md`

## Maintenance

- Before writing, check if a similar memory already exists — update it instead of duplicating
- If a memory becomes outdated (code changed, pattern no longer applies), remove or update it
- When editing or removing an entry, update any entries whose `## Related` lines point to it
- Keep MEMORY.md index concise — one line per entry, under 150 characters
