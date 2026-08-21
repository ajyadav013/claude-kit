---
description: Scaffold the claude-kit SDLC config (CLAUDE.md + .claude/rules, agents, skills, hooks) into this project
argument-hint: "[target-dir] [--defaults] [--force]"
allowed-tools: Bash, Read, Glob, Write, AskUserQuestion
---

Install the claude-kit autonomous-SDLC configuration into the current project.

**The Python CLI is required.** It resolves the stack/profile/MCP catalog, installs overlay rules +
agents, assembles `settings.json`, and records `init-options.json` for safe upgrades
(`claude-kit upgrade` / `diff`). First detect whether it is on PATH (three entry points ship):

```
command -v claude-kit >/dev/null 2>&1 && echo "CKIT_CLI=claude-kit" \
  || { command -v ckit >/dev/null 2>&1 && echo "CKIT_CLI=ckit" \
  || { command -v claude-sdlc >/dev/null 2>&1 && echo "CKIT_CLI=claude-sdlc" \
  || echo "CKIT_CLI_MISSING"; }; }
```

**If the output is `CKIT_CLI_MISSING`, offer to install it — never scaffold without it.** The CLI
is not installed under any of its names. When an installer is available on PATH (`pipx`, else
`pip`/`pip3`), ask ONE AskUserQuestion with the install option first:

- **"Install claude-code-kit now (Recommended)"** — on accept, run `pipx install claude-code-kit`
  (fall back to `pip install claude-code-kit` when pipx is absent), then **re-run the detection
  block above** and proceed only if a CLI name now resolves.
- **"Skip"** — or if the install fails, or no installer is on PATH: STOP — do not scaffold
  anything. Tell the user the CLI is required, show both install commands below, and have them
  re-run `/claude-kit:init`. Do not silently fall back to a partial install.

Never ask when the CLI is already present, and never ask when no installer exists on PATH (nothing
to offer — go straight to the stop-with-instructions):

- Recommended: `pipx install claude-code-kit`
- Or: `pip install claude-code-kit`

**You have no TTY — never run the CLI's interactive flow.** Your shell tool is not a terminal:
every prompt the CLI would show silently falls back to its default instead of asking. Running bare
`init` would install the default stack (React + FastAPI + PostgreSQL, standard profile) without the
user ever choosing. Pick the path that matches what the user gave you:

1. **The user passed `--defaults` and/or `--config <file>`, or explicitly asked for defaults** — run
   the detected CLI's `init` subcommand with the arguments the user passed to this command:

   > `$ARGUMENTS`

2. **Otherwise — interview the user yourself, then run non-interactively.** Ask the ordered
   questions in chat (AskUserQuestion where available; every question has a default the user can
   accept):

   1. Frontend framework + language (default: React / TypeScript)
   2. Backend language + framework (default: Python / FastAPI; Go / net-http also live)
   3. Database (default: PostgreSQL; MongoDB also live)
   4. SDLC profile (`lean` · `standard` default · `enterprise`)
   5. Optional MCP integrations (default: none; ids via `claude-kit list-options`)
   6. Learning capture (`off` default · `session-end-catchup` recommended · `session-end` ·
      `per-task`) — capture is **opt-in**: tell the user the background job reads session
      transcripts + changed files before they choose, that `CLAUDE_KIT_NO_AUTOCAPTURE=1` disables
      it at runtime, and that `claude-kit privacy-report` audits what got installed. Only record a
      non-`off` mode when the user explicitly picks one.
   7. Usage scope (`individual` · `team` default · `organization`; organization adds teams,
      autonomy level, review strictness, and org packs)

   Then write the answers to a temp YAML (nested form below), run
   `<CLI> init <target-dir> --config <temp-file>`, and delete the temp file afterwards:

   ```yaml
   frontend: { framework: react, language: typescript }
   backend:  { language: python, framework: fastapi }
   database: postgres
   profile:  standard
   mcp:      []                          # e.g. [github, playwright]
   capture_mode: "off"                   # or the mode the user explicitly chose (keep it quoted)
   scope:    team
   ```

**Argument safety (important).** Pass user-supplied arguments to the CLI as **ordinary, separate
command-line arguments, exactly as the user gave them** — do **not** interpolate them into a shell
command string. If any single argument contains spaces or shell metacharacters (`$`, `` ` ``, `;`,
`|`, `&`, `>`, `(`, quotes, …), quote that one argument so the shell treats it as literal text. This
prevents word-splitting, globbing, and command injection from the raw argument text. For example, if
the detected CLI was `claude-kit` and the user passed `/path/to/proj --defaults`, run
`claude-kit init /path/to/proj --defaults`.

**No shell-write fallback.** As of 0.83.0, project installation always goes through the Python CLI's
path-containment checks, strict staging validation, and rollback transaction. `scripts/init.sh` is a
compatibility dispatcher only: it invokes `claude-kit init`/`ckit init` when installed and otherwise
exits non-zero after printing `pipx install claude-code-kit`. Do not copy the payload with shell
`cp`/`rm` commands and do not treat `CLAUDE_KIT_BASIC` as a bypass. If the CLI cannot be installed,
STOP and report that **no project files were changed**.

After it completes:
1. Summarize what was installed — `CLAUDE.md`, `.claude/{rules, agents, skills, hooks, templates}`,
   `.claude/config/`, and optional `.mcp.json` — with counts.
2. If `CLAUDE.md` / `settings.json` / `.mcp.json` already existed, the installer wrote a
   `.claude-kit` sidecar instead of overwriting. Point these out and offer to merge them (or suggest
   re-running with `--force`).
3. Tell the user to **restart Claude Code** so the newly installed project agents, skills, and hooks load.
4. Suggest the next step: run `/sdlc <your first task>` (or `/claude-kit:sdlc` from the plugin).
