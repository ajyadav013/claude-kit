---
description: Scaffold the claude-kit SDLC config (CLAUDE.md + .claude/rules, agents, skills, hooks) into this project
argument-hint: "[target-dir] [--defaults] [--force]"
allowed-tools: Bash, Read, Glob
---

Install the claude-kit autonomous-SDLC configuration into the current project.

**Prefer the full Python CLI** (it runs the ordered prompts, resolves the stack/profile/MCP catalog,
installs overlay rules + agents, assembles `settings.json`, and records `init-options.json` for safe
upgrades). Check whether it's on PATH and use it, passing through `$ARGUMENTS`:

```
command -v claude-kit >/dev/null 2>&1 && claude-kit init $ARGUMENTS \
  || { command -v ckit >/dev/null 2>&1 && ckit init $ARGUMENTS; }
```

If neither `claude-kit` nor `ckit` is installed, fall back to the **thin** bundled scaffolder (it
copies the full payload with no stack/profile resolution — a superset install; suggest the user
`pip install claude-code-kit` afterwards for the catalog-driven experience):

```
bash "${CLAUDE_PLUGIN_ROOT}/scripts/init.sh" $ARGUMENTS
```

If `${CLAUDE_PLUGIN_ROOT}` is not set (running from a source checkout), locate `scripts/init.sh` in
the claude-kit repository and run it the same way.

After it completes:
1. Summarize what was installed — `CLAUDE.md`, `.claude/{rules, agents, skills, hooks, templates}`,
   and (CLI only) `.claude/config/`, optional `.mcp.json` — with counts.
2. If `CLAUDE.md` / `settings.json` / `.mcp.json` already existed, the installer wrote a
   `.claude-kit` sidecar instead of overwriting. Point these out and offer to merge them (or suggest
   re-running with `--force`).
3. Tell the user to **restart Claude Code** so the newly installed project agents, skills, and hooks load.
4. Suggest the next step: run `/sdlc <your first task>` (or `/claude-kit:sdlc` from the plugin).
