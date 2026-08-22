---
schema_version: 1
id: status
description: Show {{kit:cli}} working memory and installed-config status for this project
aliases:
- status
invocation: explicit
capabilities:
- filesystem.read
- filesystem.search
- shell
request_input:
  mode: none
pause_for_human: []
references:
- command://init
- state://agent-memory-index
- state://continuity
- state://init-options
- state://root
- state://stack-catalog
---

Report the current {{kit:cli}} status for this project. Gather and summarize:

1. **Working memory** — read `state://continuity` and summarize the current phase, active
   tasks, decisions, and next steps. If it doesn't exist, say the project hasn't started a
   pipeline run yet.
2. **Installed config** — list what's present under `state://root/`: counts of `rules/`, `agents/`,
   `skills/`, and `hooks/`. Note if any are missing (suggest `{{command_alias:command://init}}`).
3. **Selection & profile** — if `state://init-options` exists, report the stack
   selection (frontend / backend / database), the SDLC profile, and any MCP servers; if
   `state://stack-catalog` exists, list the active quality gates. If neither
   exists, note this looks like a minimal/no-CLI install.
4. **Learnings** — if `state://agent-memory-index` exists, show its index entries.

If `{{kit:cli}}` is on PATH, you may instead run `{{kit:cli}} status` and `{{kit:cli}} validate` and
summarize their output. Keep it to a concise, scannable status report. Do not modify any files.
