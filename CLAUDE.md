# Developing claude-kit

This repository **is** claude-kit — a Cookiecutter-style scaffolder that installs a stack-agnostic,
autonomous-SDLC **configuration** (no application code, no Docker) into a Claude Code project. It is
distributed two ways from one source of truth:

1. **As a Claude Code plugin** — components are auto-discovered from the repo root.
2. **As a pip package** — `claude-kit` (CLI: `claude-kit` / `ckit` / `claude-sdlc`) scaffolds the
   same content into any project's `.claude/`, driven by the `catalog/` (stacks · profiles · MCP).

> Note: the files in this repo are the **kit's payload**, not rules for this repo itself. The
> generic engineering ruleset that gets installed into user projects lives in
> `templates/CLAUDE.md`, **not** this file.

## Repository layout

| Path | Purpose |
|------|---------|
| `.claude-plugin/plugin.json` | Plugin manifest (name, version, hooks path) |
| `.claude-plugin/marketplace.json` | Marketplace entry so `/plugin marketplace add` works |
| `agents/` | SDLC pipeline subagents (auto-discovered by the plugin); each carries a `tier:` field |
| `skills/` | Agent skills (auto-discovered by the plugin); `skills/sdlc/` is the `/sdlc` entrypoint |
| `commands/` | Slash commands: `/claude-kit:init`, `:sdlc`, `:status` (init prefers the pip CLI, falls back to `init.sh`; sdlc delegates to the `sdlc` skill) |
| `hooks/hooks.json` + `hooks/scripts/` | Event hooks (paths via `${CLAUDE_PLUGIN_ROOT}`) |
| `rules/` | The 21-file stack-agnostic engineering rule set (scaffolded into `.claude/rules/`), including the agent-operation rules (reasoning, guardrails, resilience, goal-setting, human-in-the-loop, model-tiers — see `docs/agentic-patterns.md`) and the org-core rules `autonomy-levels` + `risk-classification` (see `docs/org-capabilities.md`) |
| `catalog/` | **Data-driven registry** — `stacks.yaml` · `profiles.yaml` · `mcp.yaml` · `org.yaml`. The only thing that decides what `resolve()` installs. Adding a stack/profile/server/pack is a data change here. |
| `templates/` | `CLAUDE.md`, `CLAUDE.stack.md.tmpl`, `README.claude-sdlc.md.tmpl`, `CONTINUITY.template.md`, `settings.json`, `artifacts/`, `agent-memory/` seed |
| `templates/stacks/<kind>/<id>/` | Per-stack **overlay** content: `rules/` (+ `agents/` for DB stacks). **No application code, no Docker** — the only place stack-specific content lives. |
| `templates/org/` | **Org overlay** content (scope-gated, organization only): `skills/`, `agents/` (personas), `rules/` (policy/vibe), `packs/<pack>/{pack.yaml,README.md}`, `README.md`. Wired via `catalog/org.yaml`. The only place org-specific content lives. |
| `scripts/init.sh` | Thin no-pip fallback scaffolder (copies the full payload; no catalog resolution) |
| `src/claude_kit/` | The pip CLI (Typer): `cli.py`, `catalog.py` (resolver), `prompts.py`, `models.py`, `scaffold.py` (installer), `render.py` (Jinja2), `hooks.py`, `validator.py`, `upgrader.py` |
| `tests/` | pytest suite (catalog, render, scaffold, validator, upgrader, CLI) |
| `docs/architecture.md` · `docs/agents.md` | Architecture diagrams · agent guide |
| `pyproject.toml` | Packaging (deps: typer/jinja2/pyyaml); `[tool.hatch...force-include]` bundles the payload into the wheel |

**One source of truth:** `agents/ skills/ commands/ hooks/ rules/ templates/ catalog/` at the repo
root are read directly by the plugin **and** bundled into the wheel (mapped to
`claude_kit/_payload/`) for the pip CLI. Never duplicate this content.

## Golden rules for changes here

1. **Keep the core payload stack-agnostic.** No FastAPI/React/Python/TypeScript/Docker/etc.
   specifics in `rules/`, `agents/`, or `skills/`. Use neutral phrasing ("the project's linter /
   test runner / build"); the `devops-engineer` is **container-optional**, never Docker-required.
   The backend/frontend split may appear only as the canonical example of two independent parallel
   lanes. **All** stack-specific content (overlay rules like `fastapi-patterns.md`, DB overlay agents
   like `postgres-specialist`, exact commands) lives **only** under `templates/stacks/<kind>/<id>/`
   and is wired up via `catalog/stacks.yaml` — never leak it into the agnostic core, and never add
   application code or Docker anywhere.
2. **Reference rules by their canonical filename** under `.claude/rules/…` (that's where they
   land in a user project). The current core rule set is the 21 files in `rules/` (org policy/vibe
   rules under `templates/org/rules/` install only in organization scope).
3. **Plugin components live at the repo root**, never inside `.claude-plugin/` (only the
   manifest goes there).
4. **Hook scripts use `${CLAUDE_PLUGIN_ROOT}`** for plugin context and degrade to no-ops when
   a tool isn't present (stack detection, never hard failure).
5. **Bump the version** in all four places together for a release — `pyproject.toml`,
   `.claude-plugin/plugin.json`, the `.claude-plugin/marketplace.json` entry, and
   `src/claude_kit/__init__.py` (`__version__`, what the CLI prints) — and add a `CHANGELOG.md` entry.
6. **Extend via the catalog, not code.** A new framework/database/profile/MCP server is a
   `catalog/*.yaml` edit plus a `templates/stacks/<dir>/` folder; a new org pack/team/autonomy level
   is a `catalog/org.yaml` edit plus content under `templates/org/`. `catalog.resolve()` must not grow
   stack- or org-specific branches (the org layer is the same scope-gated lookup/union as profiles/mcp).
   Mark not-yet-shipped entries `status: planned`.
7. **Keep the org layer scope-gated and reuse-first.** Org content installs **only** when
   `scope == organization`; packs MAP roles to existing components (`existing: true`) and create only
   genuinely-new content (`existing: false`) — never a competing duplicate of an existing
   agent/skill/rule. Org rules/skills/agents are stack-agnostic too. See `docs/org-capabilities.md`.

## Dogfooding / local testing

- **Plugin:** `claude` → `/plugin marketplace add .` → `/plugin install claude-kit` (loads the
  agents/skills/commands/hooks from this checkout).
- **CLI:** `pip install -e '.[dev]'` then `claude-kit init /tmp/demo --defaults` (or interactive),
  `claude-kit validate /tmp/demo`, `claude-kit diff /tmp/demo`, and inspect the result.
- **Tests:** `pytest` (the suite installs into temp dirs and asserts the no-Docker, profile-subset,
  MCP-gating, and upgrade-safety invariants).
- **Build:** `python3 -m build && python3 -m twine check dist/*`.

See `CONTRIBUTING.md` for the full contributor workflow.
