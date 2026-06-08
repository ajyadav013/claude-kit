---
description: Generate a new full-stack project (React + FastAPI) with the claude-kit SDLC config baked in
argument-hint: "[name] [--backend python-fastapi] [--frontend react] [--no-input] [--here]"
allowed-tools: Bash, Read, Glob
---

Generate a new project from the claude-kit stack registry, with the autonomous SDLC config baked in.

Prefer the installed CLI if it is on PATH:

```
claude-kit new $ARGUMENTS
```

If `claude-kit` is not installed, run the bundled generator from the plugin instead:

```
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/new.py" $ARGUMENTS
```

After it completes:

1. Summarize what was generated — `backend/`, `frontend/`, `docker-compose.yml`, `Makefile`,
   `CLAUDE.md`, and `.claude/{rules,agents,skills,hooks}` — and the stacks that were selected.
2. Tell the user how to run it: `docker compose up --build` (zero local installs) or `make dev` for
   native development.
3. Tell them to **restart Claude Code** in the new project directory so its agents, skills, and
   hooks load.
4. Suggest the first task: `/claude-kit:sdlc <your first feature>`.
