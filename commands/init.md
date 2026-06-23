---
description: Scaffold the claude-kit SDLC config (CLAUDE.md + .claude/rules, agents, skills, hooks) into this project
argument-hint: "[target-dir] [--defaults] [--force]"
allowed-tools: Bash, Read, Glob
---

Install the claude-kit autonomous-SDLC configuration into the current project.

**The Python CLI is required.** It runs the ordered prompts, resolves the stack/profile/MCP catalog,
installs overlay rules + agents, assembles `settings.json`, and records `init-options.json` for safe
upgrades (`claude-kit upgrade` / `diff`). Check whether it's on PATH and use it, passing through
`$ARGUMENTS`:

```
command -v claude-kit >/dev/null 2>&1 && claude-kit init $ARGUMENTS \
  || { command -v ckit >/dev/null 2>&1 && ckit init $ARGUMENTS \
  || echo "CKIT_CLI_MISSING"; }
```

**If the output is `CKIT_CLI_MISSING`, STOP — do not scaffold anything.** Neither `claude-kit` nor
`ckit` is installed. Tell the user the CLI is required and how to install it, then have them re-run
`/claude-kit:init`. Do **not** silently fall back to a partial install:

- Recommended: `pipx install claude-code-kit`
- Or: `pip install claude-code-kit`

**Escape hatch (advanced, opt-in only).** A thin shell scaffolder exists for locked-down environments
where installing the CLI is impossible. It copies the full payload as a **superset** with **no**
stack/profile/MCP resolution, and `claude-kit upgrade` / `diff` will **not** work against it. Use it
**only** if the user has explicitly opted in by setting `CLAUDE_KIT_BASIC=1`:

```
if [ "${CLAUDE_KIT_BASIC:-0}" = "1" ]; then
  bash "${CLAUDE_PLUGIN_ROOT}/scripts/init.sh" $ARGUMENTS
else
  echo "set CLAUDE_KIT_BASIC=1 to use the degraded no-CLI scaffolder (the CLI is the supported path)"
fi
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
