# Contributing to claude-kit

Thanks for helping improve claude-kit! This guide covers the repo conventions, how to test
locally, and how to release.

## Mental model

- The directories at the repo root — `agents/`, `skills/`, `commands/`, `hooks/`, `rules/`,
  `templates/`, `catalog/` — are the **kit payload** and the **single source of truth**.
- The plugin reads them directly from the root; the pip wheel bundles them under
  `claude_kit/_payload/` via `force-include` in `pyproject.toml`. **Never duplicate this content.**
- `src/claude_kit/` is the pip CLI (the canonical scaffolder). `scripts/init.sh` is a **thin no-pip
  fallback** for the `/claude-kit:init` plugin command — it copies the full payload with no catalog
  resolution; don't reimplement the resolver in bash.
- claude-kit installs **configuration only** — never application code, never Docker.

## Golden rules

1. **Keep the payload stack-agnostic.** No language/framework/Docker assumptions in `rules/`,
   `agents/`, or `skills/`. Use neutral phrasing ("the project's linter / test runner / build"); the
   `devops-engineer` is container-optional. The backend/frontend split may appear only as the
   canonical example of two independent parallel work streams.
2. **All stack-specific content lives under `templates/stacks/<kind>/<id>/`** and is wired via
   `catalog/stacks.yaml` — overlay rules, and DB overlay agents. Nothing stack-specific in the core.
3. **Reference rules by their canonical filename** under `.claude/rules/…` — that's where they land.
4. **Plugin components live at the repo root**, never inside `.claude-plugin/` (only the two
   manifests go there).
5. **Hook scripts** use `${CLAUDE_PLUGIN_ROOT}` for plugin context and **degrade to no-ops** when a
   tool isn't present — detect, never hard-fail.

## Adding components

- **Agent** → add `agents/<name>.md` with YAML frontmatter (`name`, `description`, `tools`, optional
  `model`, `color`, and a `tier:` of orchestrator/stage-lead/specialist/review). The `description`
  drives selection — make it accurate and trigger-friendly. Add the name to the relevant profile(s)
  in `catalog/profiles.yaml` so it gets installed.
- **Skill** → add `skills/<name>/SKILL.md` (uppercase `SKILL.md`). Keep the `description` focused on
  *when* to use it. Add it to the relevant profile(s) in `catalog/profiles.yaml`.
- **Rule** → add `rules/<name>.md`; cross-reference siblings as `.claude/rules/<name>.md`.
- **Hook** → add a script to `hooks/scripts/`, register it in the `HOOK_REGISTRY` in
  `src/claude_kit/hooks.py`, wire it in `hooks/hooks.json` (plugin), and list its id in the relevant
  profile's `hooks:`.
- **Stack** (framework / database) → a **data change**: add an entry to `catalog/stacks.yaml`
  (`label`, `overlay_rules`, optional `overlay_agents`, `skills`, `stack_dir`, `commands`) and create
  `templates/stacks/<stack_dir>/rules/<name>.md` (+ `agents/` for a database). Mark not-yet-ready
  entries `status: planned`. No Python change is needed — `catalog.resolve()` must stay branch-free.
- **Profile** → add an entry to `catalog/profiles.yaml` (compose with `inherit:`; `all` selects
  everything). **MCP server** → add an entry to `catalog/mcp.yaml` with a `config` fragment using
  `${ENV}` placeholders (never real credentials).

## Local testing

```bash
# Plugin (dogfood this checkout):
#   in Claude Code:  /plugin marketplace add .   then   /plugin install claude-kit

# CLI:
pip install -e '.[dev]'
claude-kit list-options
claude-kit init /tmp/ck-demo --defaults && ls -R /tmp/ck-demo/.claude
claude-kit validate /tmp/ck-demo
claude-kit diff /tmp/ck-demo

# Tests:
pytest

# Build + validate the package:
python3 -m build
python3 -m twine check dist/*
```

Verify there's no stack/Docker leakage in the **core** payload before opening a PR (stack specifics
belong under `templates/stacks/`, which is intentionally excluded here):

```bash
grep -rInE 'fastapi|sqlalchemy|alembic|docker' rules agents skills && echo "REVIEW these" || echo "clean"
```

(Balanced multi-framework *example* lists are acceptable; a real leak is agnostic logic branching on
a specific stack — `pytest` enforces the no-Docker invariant on a scaffolded project.)

## Releasing

1. Bump the version in **all four** places: `pyproject.toml`, `.claude-plugin/plugin.json`, the
   `.claude-plugin/marketplace.json` entry, and `src/claude_kit/__init__.py`.
2. Add a `CHANGELOG.md` entry.
3. `pytest` green, then `python3 -m build && python3 -m twine check dist/*`.
4. `python3 -m twine upload dist/*` (PyPI).
5. Tag the release and push so plugin users get the update.

## License

By contributing you agree your contributions are licensed under the project's [MIT License](LICENSE).
