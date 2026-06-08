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
3. **Selection & profile** — if `.claude/config/init-options.json` exists, report the stack
   selection (frontend / backend / database), the SDLC profile, and any MCP servers; if
   `.claude/config/stack-catalog.snapshot.yaml` exists, list the active quality gates. If neither
   exists, note this looks like a minimal/no-CLI install.
4. **Learnings** — if `.claude/agent-memory/MEMORY.md` exists, show its index entries.

If `claude-kit` is on PATH, you may instead run `claude-kit status` and `claude-kit validate` and
summarize their output. Keep it to a concise, scannable status report. Do not modify any files.
