# Developing claude-kit

This repository **is** claude-kit — a stack-agnostic, autonomous-SDLC kit for Claude Code,
distributed two ways from one source of truth:

1. **As a Claude Code plugin** — components are auto-discovered from the repo root.
2. **As a pip package** — `claude-kit` (CLI: `claude-kit` / `ckit`) scaffolds the same content
   into any project's `.claude/`.

> Note: the files in this repo are the **kit's payload**, not rules for this repo itself. The
> generic engineering ruleset that gets installed into user projects lives in
> `templates/CLAUDE.md`, **not** this file.

## Repository layout

| Path | Purpose |
|------|---------|
| `.claude-plugin/plugin.json` | Plugin manifest (name, version, hooks path) |
| `.claude-plugin/marketplace.json` | Marketplace entry so `/plugin marketplace add` works |
| `agents/` | SDLC pipeline subagents (auto-discovered by the plugin) |
| `skills/` | Agent skills (auto-discovered by the plugin) |
| `commands/` | Slash commands: `/claude-kit:init`, `:sdlc`, `:status` |
| `hooks/hooks.json` + `hooks/scripts/` | Event hooks (paths via `${CLAUDE_PLUGIN_ROOT}`) |
| `rules/` | The engineering rule set (scaffolded into `.claude/rules/`) |
| `templates/` | `CLAUDE.md`, `CONTINUITY.template.md`, `settings.json`, `agent-memory/` seed |
| `scripts/init.sh` | Shared scaffolder used by `/claude-kit:init` |
| `src/claude_kit/` | The pip CLI (`init`, `status`, `list`, `upgrade`, `version`) |
| `docs/architecture.md` | Architecture diagrams |
| `pyproject.toml` | Packaging; `[tool.hatch...force-include]` bundles the payload into the wheel |

**One source of truth:** `agents/ skills/ commands/ hooks/ rules/ templates/` at the repo
root are read directly by the plugin **and** bundled into the wheel (mapped to
`claude_kit/_payload/`) for the pip CLI. Never duplicate this content.

## Golden rules for changes here

1. **Keep the payload stack-agnostic.** No FastAPI/React/Python/TypeScript/etc. specifics in
   `rules/`, `agents/`, or `skills/`. Use neutral phrasing ("the project's linter / test
   runner / build"). The backend/frontend split may appear only as the canonical example of
   two independent parallel lanes.
2. **Reference rules by their canonical filename** under `.claude/rules/…` (that's where they
   land in a user project). The current rule set is the 13 files in `rules/`.
3. **Plugin components live at the repo root**, never inside `.claude-plugin/` (only the
   manifest goes there).
4. **Hook scripts use `${CLAUDE_PLUGIN_ROOT}`** for plugin context and degrade to no-ops when
   a tool isn't present (stack detection, never hard failure).
5. **Bump the version** in both `pyproject.toml` and `.claude-plugin/plugin.json` together for
   a release, and add a `CHANGELOG.md` entry.

## Dogfooding / local testing

- **Plugin:** `claude` → `/plugin marketplace add .` → `/plugin install claude-kit` (loads the
  agents/skills/commands/hooks from this checkout).
- **CLI:** `pip install -e .` then `claude-kit init /tmp/demo` and inspect the result.
- **Build:** `python3 -m build && python3 -m twine check dist/*`.

See `CONTRIBUTING.md` for the full contributor workflow.
