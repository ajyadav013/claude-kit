---
name: remember
description: Capture a durable learning so future sessions reuse it automatically. Use whenever the user corrects Claude, states a preference or rule (UX, code style, architecture, API behavior), shares a hard-won debugging insight, or explicitly says "remember this" / "note this for next time" / "don't make this mistake again". Writes a structured entry into .claude/agent-memory/ and updates the index. Pairs with the SessionStart hook that loads these learnings back into context each session.
---

# Remember — Durable Learning Capture

Turn a one-off correction or insight into a permanent, reusable learning. This is the **capture** half of the self-improving loop. The **application** half is automatic: the `load-learnings.sh` SessionStart hook injects the index below into context at the start of every session, so anything recorded here is surfaced before future work.

## When to invoke this skill

**This is now automatic.** A `UserPromptSubmit` hook semantically scans every message you send; when it detects a durable learning it injects a `LEARNING DETECTED` note telling Claude to invoke this skill silently. You do not need to type `/remember` — though you still can to force a capture. Invoke proactively whenever any of these happen:

- The user **corrects** something Claude did ("no, buttons should be 44px touch targets", "always validate at the boundary").
- The user states a **preference or rule** for how work should be done (UX, design, naming, architecture, testing, tone).
- A **debugging session** uncovered a non-obvious root cause that took real effort to find.
- An **API / integration quirk** surfaced that isn't visible in the code.
- The user says "remember this", "note this", "next time…", "don't repeat this", or similar.

Do **not** record:
- Facts already visible in the codebase or the rules under `.claude/rules/`.
- Standard framework behavior (look it up instead).
- Temporary task state (that's what tasks are for).
- Anything already captured — update the existing entry instead of duplicating.

## How to capture (4 steps)

### 1. Decide the category

Map the learning to one folder under `.claude/agent-memory/`:

| Category | Folder | What goes here |
|----------|--------|----------------|
| UX / Design | `ux/` | Interaction rules, design-system preferences, accessibility musts, layout/visual decisions |
| Architecture | `architecture/` | Why X over Y, structural decisions, module boundaries |
| Debugging | `debugging/` | Root causes of tricky bugs, non-obvious failure modes |
| Patterns | `patterns/` | Recurring project-specific patterns and conventions |
| API & Integration | `api/` | API quirks, auth flows, endpoint behaviors |
| Performance | `performance/` | Optimization discoveries, bottleneck insights |
| Gotchas | `gotchas/` | Looks-right-but-isn't traps, common mistakes |

If unsure, pick the closest fit; UX preferences go in `ux/`.

### 2. Check for an existing entry

Read `.claude/agent-memory/MEMORY.md` and skim the relevant category folder. If a similar learning exists, **edit that file** (refine, add nuance, correct it) rather than creating a duplicate.

### 3. Write the learning file

Filename: lowercase kebab-case describing the insight, e.g. `touch-target-min-size.md`, `filter-resets-on-persona-change.md`. Write to `.claude/agent-memory/<category>/<filename>.md` using this format:

```markdown
---
title: {short descriptive title}
category: {category name}
date: {YYYY-MM-DD}
trigger: {when this applies — e.g. "designing any UI", "writing an HTTP endpoint"}
---

## Context
{What situation produced this learning — keep it brief}

## Learning
{The rule/insight, stated as a clear, actionable directive Claude can follow next time}

## Evidence
{How it was discovered — the user's words, an error, debugging steps}

## Apply when
{Concrete signal that this learning is relevant to the current task}
```

The `trigger` and `Apply when` fields matter most — they are how a future session knows to pull this learning before acting.

### 4. Update the index

Add a one-line entry to `.claude/agent-memory/MEMORY.md` under the matching `###` section:

```markdown
- [Title](category/filename.md) — one-line hook | applies when: {trigger}
```

Keep each index line under ~150 chars. The index is what the SessionStart hook injects, so it must stay scannable.

## After capturing

Confirm to the user in one line what was recorded and where, e.g.:
> Recorded: "44px minimum touch targets" → `agent-memory/ux/touch-target-min-size.md`. I'll apply it automatically next time I design UI.

## How application works (for reference)

You do not need to do anything to apply learnings — the loop closes on its own:

1. `load-learnings.sh` runs on **SessionStart** and prints the MEMORY.md index into context.
2. Before doing design/implementation work, open the relevant category file(s) flagged by `Apply when` and follow them.
3. When you learn something new, this skill records it — and it shows up automatically next session.
