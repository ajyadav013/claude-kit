---
name: ckit-command-init
description: 'Install the Codex-native ckit configuration: AGENTS.md plus .agents, .codex, and shared .ckit state'
---

Install the ckit autonomous-SDLC configuration into the current project.

**The Python CLI is required.** It resolves the stack/profile/MCP catalog, projects
Codex-native `AGENTS.md`, `.agents/skills/`, `.codex/agents/`, hooks, and MCP config, and records
the neutral `.ckit/config/init-options.json` manifest for safe upgrades (`ckit upgrade` / `diff`).
Detect the preferred `ckit` entry point first; the older names are compatibility aliases:

```
command -v ckit >/dev/null 2>&1 && echo "CKIT_CLI=ckit" \
  || { command -v claude-kit >/dev/null 2>&1 && echo "CKIT_CLI=claude-kit" \
  || { command -v claude-sdlc >/dev/null 2>&1 && echo "CKIT_CLI=claude-sdlc" \
  || echo "CKIT_CLI_MISSING"; }; }
```

**If the output is `CKIT_CLI_MISSING`, offer to install it — never scaffold without it.** The CLI
is not installed under any of its names. When an installer is available on PATH (`pipx`, else
`pip`/`pip3`), ask ONE pause and request user input with the install option first:

- **"Install claude-code-kit now (Recommended)"** — on accept, run `pipx install claude-code-kit`
  (fall back to `pip install claude-code-kit` when pipx is absent), then **re-run the detection
  block above** and proceed only if a CLI name now resolves.
- **"Skip"** — or if the install fails, or no installer is on PATH: STOP — do not scaffold
  anything. Tell the user the CLI is required, show both install commands below, and have them
  re-run the init skill. Do not silently fall back to a partial install.

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

   > `the invocation request`

   **Always make the runtime explicit.** Preserve a `--runtime claude|codex|both` argument that the
   user supplied, or a top-level `runtime` already present in their `--config` file. Otherwise
   append `--runtime codex`. Codex projection is preview in this release, so set
   `CKIT_EXPERIMENTAL=1` for any `codex` or `both` init. Never invoke `init` from this adapter with
   an implicit runtime.

2. **Otherwise — interview the user yourself, then run non-interactively.** Ask the ordered
   questions in chat (pause and request user input where available; every question has a default the user can
   accept):

   1. Frontend framework + language (default: React / TypeScript)
   2. Backend language + framework (default: Python / FastAPI; Go / net-http also live)
   3. Database (default: PostgreSQL; MongoDB also live)
   4. SDLC profile (`lean` · `standard` default · `enterprise`)
   5. Optional MCP integrations (default: none; ids via `ckit list-options`)
   6. Learning capture (`off` default and recommended · `session-end` · `per-task` ·
      `session-end-catchup` compatibility mode) — capture is **opt-in**. Explain that Codex capture
      uses the repository's changed-path set in a sandboxed background task and does not assume a
      historical transcript contract; catch-up safely no-ops when no stable transcript source exists.
      `CKIT_NO_AUTOCAPTURE=1` disables capture, and `ckit privacy-report` audits the installed
      hooks. Only record a non-`off` mode when the user explicitly picks one.
   7. Usage scope (`individual` · `team` default · `organization`; organization adds teams,
      autonomy level, review strictness, and org packs)

   Then write the answers to a temp YAML (nested form below), run
   `CKIT_EXPERIMENTAL=1 <CLI> init <target-dir> --config <temp-file> --runtime codex`, and delete the temp file afterwards:

   ```yaml
   runtime: codex
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
the detected CLI was `ckit` and the user passed `/path/to/proj --defaults`, run
`CKIT_EXPERIMENTAL=1 ckit init /path/to/proj --defaults --runtime codex`. If the request already selected another runtime, preserve that value instead.

**No shell-write fallback.** As of 0.83.0, project installation always goes through the Python CLI's
path-containment checks, strict staging validation, and rollback transaction. `scripts/init.sh` is a
compatibility dispatcher only: it invokes `ckit init` (or a compatibility CLI alias) when installed and otherwise
exits non-zero after printing `pipx install claude-code-kit`. Do not copy the payload with shell
`cp`/`rm` commands and do not treat `CKIT_BASIC` as a bypass (the legacy `CLAUDE_KIT_BASIC` alias is not a bypass either). If the CLI cannot be installed,
STOP and report that **no project files were changed**.

After it completes:
1. Summarize the native Codex surfaces with counts: `AGENTS.md`, `.agents/skills/`,
   `.codex/agents/`, `.codex/hooks.json`, `.codex/hooks/scripts/`, `.codex/config.toml`, and the
   shared `.ckit/` rules, templates, configuration, state, memory, and scripts.
2. Report the persisted runtime from `.ckit/config/init-options.json`; it must match the explicit
   runtime selection. Do not call a Codex install successful if it silently recorded `claude`.
3. Report managed-section merges, conflicts, and any `.claude-kit` sidecars exactly as the installer
   logged them. Do not claim that `AGENTS.md` or `.codex/config.toml` was overwritten.
4. Tell the user to restart Codex so newly installed project agents, skills, and hooks load.
5. Suggest this plugin's `sdlc` skill with their first task.
