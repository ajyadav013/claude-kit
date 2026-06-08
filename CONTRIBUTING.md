# Contributing to claude-kit

Thanks for helping improve claude-kit! This guide covers the repo conventions, how to test
locally, and how to release.

## Mental model

- The directories at the repo root — `agents/`, `skills/`, `commands/`, `hooks/`, `rules/`,
  `templates/` — are the **kit payload** and the **single source of truth**.
- The plugin reads them directly from the root; the pip wheel bundles them under
  `claude_kit/_payload/` via `force-include` in `pyproject.toml`. **Never duplicate this content.**
- `src/claude_kit/` is the pip CLI. `scripts/init.sh` is the equivalent scaffolder used by the
  `/claude-kit:init` plugin command — keep the two in sync when you change scaffolding behavior.

## Golden rules

1. **Keep the payload stack-agnostic.** No language- or framework-specific assumptions in
   `rules/`, `agents/`, or `skills/`. Use neutral phrasing ("the project's linter / test runner
   / build"). The backend/frontend split may appear only as the canonical example of two
   independent parallel work streams.
2. **Reference rules by their canonical filename** under `.claude/rules/…` — that's where they
   land in a user's project.
3. **Plugin components live at the repo root**, never inside `.claude-plugin/` (only the two
   manifests go there).
4. **Hook scripts** use `${CLAUDE_PLUGIN_ROOT}` for plugin context and **degrade to no-ops**
   when a tool isn't present — detect, never hard-fail.

## Adding components

- **Agent** → add `agents/<name>.md` with YAML frontmatter (`name`, `description`, `tools`,
  optional `model`, `color`). The `description` is how the agent is selected — make it accurate
  and trigger-friendly. Register it in the orchestrator's spawn reference if it's part of the pipeline.
- **Skill** → add `skills/<name>/SKILL.md` (uppercase `SKILL.md`; required on case-sensitive
  filesystems). Keep the `description` focused on *when* to use it.
- **Rule** → add `rules/<name>.md`; cross-reference siblings as `.claude/rules/<name>.md`.
- **Hook** → add a script to `hooks/scripts/` and wire it in `hooks/hooks.json` (plugin) and
  `templates/settings.json` (scaffolded projects).

## Local testing

```bash
# Plugin (dogfood this checkout):
#   in Claude Code:  /plugin marketplace add .   then   /plugin install claude-kit

# CLI:
pip install -e .
claude-kit list
claude-kit init /tmp/ck-demo && ls -R /tmp/ck-demo/.claude

# Build + validate the package:
python3 -m pip install build twine
python3 -m build
python3 -m twine check dist/*
```

Verify there's no stack leakage before opening a PR:

```bash
grep -rInE 'sentinel|fastapi|sqlalchemy|alembic' rules agents skills && echo "FOUND — fix it" || echo "clean"
```

## Releasing

1. Bump the version in **both** `pyproject.toml` and `.claude-plugin/plugin.json`
   (and the marketplace entry).
2. Add a `CHANGELOG.md` entry.
3. `python3 -m build && python3 -m twine check dist/*`.
4. `python3 -m twine upload dist/*` (PyPI).
5. Tag the release and push so plugin users get the update.

## License

By contributing you agree your contributions are licensed under the project's [MIT License](LICENSE).
