---
name: ckit-command-status
description: Show ckit working memory, runtime selection, and installed config status
---

Report the current ckit status for this project. Gather and summarize:

1. **Working memory** — read `.ckit/CONTINUITY.md` and summarize the current phase, active
   tasks, decisions, and next steps. If it doesn't exist, say the project hasn't started a
   pipeline run yet.
2. **Installed config** — check each native surface separately: `AGENTS.md`,
   `.agents/skills/`, `.codex/agents/`, `.codex/hooks.json`, `.codex/hooks/scripts/`, and
   `.codex/config.toml`. Then summarize shared state under `.ckit/` (`rules/`, `templates/`,
   `config/`, `state/`, `agent-memory/`, and `scripts/`). Note missing required surfaces and
   suggest this plugin's `init` skill.
3. **Selection & profile** — if `.ckit/config/init-options.json` exists, report the stack
   selection (frontend / backend / database), the SDLC profile, and any MCP servers; if
   `.ckit/config/stack-catalog.snapshot.yaml` exists, list the active quality gates. If neither
   exists, note this looks like a minimal/no-CLI install.
4. **Learnings** — if `.ckit/agent-memory/MEMORY.md` exists, show its index entries.

If `ckit` is on PATH, you may instead run `ckit status` and `ckit validate` and
summarize their output. Keep it to a concise, scannable status report. Do not modify any files.
