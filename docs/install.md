# Installing claude-kit — the full detail

The README's [Quick start](../README.md#quick-start) covers the happy path. This page holds
everything else: prerequisites, Windows, plugin updates, every `init` question, the non-interactive
config format, and exactly what lands on disk.

## Prerequisites

- [Claude Code](https://www.claude.com/product/claude-code)
- Python ≥ 3.9 for the CLI
- `jq` to enable the shell hooks (they no-op without it)
- Node / `npx` only if you enable an MCP (Model Context Protocol) server

**Windows:** the config (agents · skills · rules) and the `claude-kit` CLI work natively. The shell
hooks (`guard-*`, `warn-*`) need a POSIX shell + `jq`, so run inside **WSL or Git Bash** to enable
them — `claude-kit doctor` detects Windows and tells you which case you're in. Without a POSIX shell
the hooks silently no-op (the kit still functions; you just lose the deterministic guards).

## Path A: as a Claude Code plugin

Makes all agents, skills, commands, and hooks available inside Claude Code:

```text
/plugin marketplace add ajyadav013/claude-kit
/plugin install claude-kit
```

Then, inside any project you want the pipeline to manage:

```text
/claude-kit:init        # Claude asks you the questions in chat, then runs the CLI non-interactively
# ↻ restart Claude Code so the project's agents, skills & hooks load
/sdlc Add a CSV export button to the reports page
```

> **`/claude-kit:init` requires the Python CLI** (`pipx install claude-code-kit`, or `pip install
> claude-code-kit`) — it's what resolves your stack/profile/MCP catalog and records `init-options.json`
> for safe `upgrade`/`diff`. If the CLI isn't on PATH the command stops and tells you to install it
> rather than doing a partial install. (A degraded, no-resolution shell scaffolder is available only by
> explicitly setting `CLAUDE_KIT_BASIC=1`; `upgrade`/`diff` won't work against it.)

> `/sdlc` is a **project skill** installed by `init`, so it becomes available after the restart. The
> plugin also exposes `/claude-kit:sdlc <task>`, which works immediately (no restart needed).

### Updating the plugin

The plugin is cached, so a plain `/reload-plugins` won't fetch new code — refresh the marketplace
snapshot first:

```text
/plugin marketplace update claude-kit   # refresh the marketplace snapshot from the repo
/plugin update claude-kit@claude-kit    # install the newer version into the cache
/reload-plugins                         # load it into the running session
```

## Path B: as a pip package

A CLI (`claude-kit`, aliases `ckit` / `claude-sdlc`) that scaffolds the same config into any repo:

```bash
pip install claude-code-kit             # note: the pip name is claude-code-kit, not claude-kit
# or, for the bleeding edge straight from the repo:
#   pip install "git+https://github.com/ajyadav013/claude-kit.git"

claude-kit init                 # interactive: prompts for stack, profile, MCP
claude-kit init --defaults      # non-interactive: React + Python/FastAPI + Postgres + standard
```

## What the init flow asks

`claude-kit init` asks an ordered set of questions (all with sensible defaults), then writes the
config — nothing else:

1. **Target path** (default: current dir; if `.claude/` exists → **merge / overwrite / backup / abort**)
2. **Frontend framework** (default: React; `none` for backend-only projects) → **frontend language** (default: TypeScript; skipped for `none`)
3. **Backend language** (default: Python; `none` for frontend-only projects) → **backend framework** (default: FastAPI)
4. **Database** (PostgreSQL · MongoDB · `none`)
5. **SDLC profile** (`lean` · `standard` · `enterprise`)
6. **Optional MCP integrations** (GitHub · Jira/Linear · Azure DevOps · Postgres/Mongo · Playwright · Chrome DevTools · Docs/MS Learn · Azure · Wassette · Sentry · Grafana · Repowise · the Google security suite — full list: `claude-kit list-options`) — a
   project-root `.mcp.json` is written **only** if you select any (env placeholders, never secrets)
7. **Learning capture** (`session-end-catchup` default · `session-end` · `per-task` · `off`) — how often
   the background learnings job runs. *Privacy note:* it reads your session transcript + changed files
   to write `.claude/agent-memory/` entries (secret-bearing files skipped, secret-shaped values
   redacted); opt out anytime with `CLAUDE_KIT_NO_AUTOCAPTURE=1`
8. **Usage scope** (`individual` · `team` · `organization`) — organization scope asks four follow-ups:
   teams, autonomy level, review strictness, and org capability packs

### Non-interactive: `--defaults` or `--config init.yaml`

Flat keys or this nested form:

```yaml
frontend: { framework: react, language: typescript }
backend:  { language: python, framework: fastapi }
database: postgres
profile:  standard                     # lean · standard · enterprise
mcp:      [github]                     # [] = none; ids from `claude-kit list-options`
capture_mode: session-end-catchup      # off · session-end · session-end-catchup · per-task
scope:    team                         # individual · team · organization (org adds org: {teams, autonomy, review_strictness, packs})
```

### What lands on disk

```
CLAUDE.md                      # "Project-specific rules" filled from your stack's commands
README.claude-sdlc.md
.claude/
  settings.json                # assembled from the profile's hooks
  rules/                        # stack-agnostic core + selected overlay rules
  agents/                       # the profile's agent subset + DB overlay agents
  skills/  (incl. sdlc/)        # the profile's skill subset; sdlc/ is the /sdlc entrypoint
  hooks/                        # the profile's hook scripts
  templates/                    # artifact templates (spec, ADR, test-plan, …)
  config/                       # init-options.json (checksums) + stack snapshot
  state/  tmp/                  # gitignored runtime
.mcp.json                       # only if MCP servers were selected
```

## Stacks & overlays

- **Stack-agnostic core** — the pipeline assumes no language or framework; it never writes your app
  code and never needs Docker.
- **13 stack overlay rule files** layer matching guidance on top — React, FastAPI, Go/net-http,
  PostgreSQL, MongoDB — wired to your exact lint/test/build commands. Overlays are **path-scoped**
  (`paths:` frontmatter) so they enter context only when Claude touches matching files; MongoDB's
  stays always-on (a document store has no reliable file signal to scope by).
- **Installs are stack-true** — every lane offers `none` (backend-only, frontend-only, no-database
  projects), and a lane you don't have installs nothing: no off-stack rules, skills, agents, or
  commands. Frontend-specific skills ride the React selection, not the profile core.
- **A full React design system** — picking React installs design tokens, UX patterns, and
  mobile/Capacitor guidelines that the UI skills and `ui-designer` agent read.

## Memory & continuous learning

- **Working memory across sessions** — `CONTINUITY.md` survives context compaction so the pipeline
  never loses its place.
- **A learnings loop** — `agent-memory/` captures fixes from your corrections *and*, in a non-blocking
  background job, from what Claude changed, so the same mistake isn't made twice.
- **Cost-aware capture** — how aggressively learnings are captured (`capture_mode`: off · on clean
  exit · + catch-up · per task) is a choice at `init` (see question 7 above for the privacy note).
