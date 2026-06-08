---
description: Show claude-kit working memory and installed-config status for this project
allowed-tools: Bash, Read, Glob
---

Report the current claude-kit status for this project. Gather and summarize:

1. **Working memory** — read `.claude/CONTINUITY.md` and summarize the current phase, active
   tasks, decisions, and next steps. If it doesn't exist, say the project hasn't started a
   pipeline run yet.
2. **Installed config** — list what's present under `.claude/`: counts of `rules/`, `agents/`,
   `skills/`, and `hooks/`. Note if any are missing (suggest `/claude-kit:init`).
3. **Learnings** — if `.claude/agent-memory/MEMORY.md` exists, show its index entries.

Keep it to a concise, scannable status report. Do not modify any files.
