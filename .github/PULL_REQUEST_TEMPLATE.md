<!-- Thanks for contributing to claude-kit! See CONTRIBUTING.md and CLAUDE.md (golden rules). -->

## What & why

Briefly describe the change and the motivation.

## Type

- [ ] Bug fix
- [ ] New stack / profile / MCP server / org pack (catalog + `templates/` data change)
- [ ] Core rule / agent / skill / hook change
- [ ] Docs only

## Checklist

- [ ] `pytest` passes locally.
- [ ] Core payload stays **stack-agnostic** (no framework/language/Docker specifics in
      `rules/`, `agents/`, `skills/`); stack-specific content lives only under `templates/stacks/`.
- [ ] If this is a release, the version is bumped in **all four** places (`pyproject.toml`,
      `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`, `src/claude_kit/__init__.py`)
      with a `CHANGELOG.md` entry.
- [ ] Docs/README updated if behavior, counts, or commands changed.
- [ ] Verified a clean-room install (`claude-kit init` + `validate`) still passes.
