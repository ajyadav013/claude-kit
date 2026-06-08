---
description: Scaffold the claude-kit SDLC config (CLAUDE.md + .claude/rules, agents, skills, hooks) into this project
argument-hint: "[target-dir] [--force] [--minimal] [--no-hooks]"
allowed-tools: Bash, Read, Glob
---

Install the claude-kit engineering-delivery config into the current project.

Run the bundled scaffolder with the Bash tool, passing through any arguments the user provided
(`$ARGUMENTS`). The scaffolder lives inside the plugin:

```
bash "${CLAUDE_PLUGIN_ROOT}/scripts/init.sh" $ARGUMENTS
```

If `${CLAUDE_PLUGIN_ROOT}` is not set (e.g. running from a source checkout), locate `scripts/init.sh`
in the claude-kit repository and run it the same way.

After it completes:
1. Summarize what was installed — `CLAUDE.md` and `.claude/{rules, agents, skills, hooks}` — with counts.
2. If `CLAUDE.md` or `.claude/settings.json` already existed, the scaffolder wrote
   `CLAUDE.md.claude-kit` / `settings.json.example` instead of overwriting. Point these out and offer
   to merge them (or suggest re-running with `--force`).
3. Tell the user to **restart Claude Code** so the newly installed project agents, skills, and hooks load.
4. Suggest the next step: `/claude-kit:sdlc <your first task>`.
