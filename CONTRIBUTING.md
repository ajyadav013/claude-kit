# Contributing to claude-kit

Thanks for helping improve claude-kit! This guide covers the repo conventions, how to test
locally, and how to release. Participation is governed by our [Code of Conduct](CODE_OF_CONDUCT.md);
security issues go through [SECURITY.md](SECURITY.md) rather than a public issue.

## Mental model

- The directories at the repo root — `agents/`, `skills/`, `commands/`, `hooks/`, `rules/`,
  `templates/`, `catalog/` — are the **kit payload** and the **single source of truth**.
- The plugin reads them directly from the root; the pip wheel bundles them under
  `claude_kit/_payload/` via `force-include` in `pyproject.toml`. **Never duplicate this content.**
- `src/claude_kit/` is the pip CLI and the only supported scaffolder. `scripts/init.sh` is a
  compatibility dispatcher to that CLI; it performs no project writes. Do not reimplement catalog
  resolution or filesystem mutation in bash.
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
6. **All project mutations go through `ProjectFS`.** Treat a target checkout and `.claude/` as
   untrusted: no direct `Path.write_*`, `mkdir`, rename, unlink, `shutil.copy*`, or recursive delete
   in installer, upgrader, or pipeline-state paths. Keep mutation-time ancestry/leaf checks and add
   adversarial symlink/reparse tests for every new destination class.
7. **Gate policy is catalog data.** Add or change a gate once in the canonical `gate_definitions`
   registry in `catalog/profiles.yaml`; do not reproduce required/skippable policy in CLI branches or
   prose. Conditional gates need closed condition identifiers. Run installs persist the definition
   digest so state cannot silently inherit changed policy.

## Adding components

- **Agent** → add `agents/<name>.md` with YAML frontmatter (`name`, `description`, `tools`, optional
  `model`, `color`, and a `tier:` of orchestrator/stage-lead/specialist/review). The `description`
  drives selection — make it accurate and trigger-friendly. Add the name to the relevant profile(s)
  in `catalog/profiles.yaml` so it gets installed.
- **Skill** → add `skills/<name>/SKILL.md` (uppercase `SKILL.md`). Keep the `description` focused on
  *when* to use it. Add it to the relevant profile(s) in `catalog/profiles.yaml`.
- **Rule** → add `rules/<name>.md`; cross-reference siblings as `.claude/rules/<name>.md`.
- **Hook** → add a script to `hooks/scripts/`, register it in the `HOOK_REGISTRY` in
  `src/claude_kit/hooks.py`, and list its id in the relevant profile's `hooks:`. To surface it in the
  plugin and/or static starter template, add its id to `PLUGIN_HOOK_IDS` / `STARTER_HOOK_IDS` (same module),
  then **run `python scripts/gen_hooks.py`** to regenerate `hooks/hooks.json` and
  `templates/settings.json` — **never hand-edit those two files** (a drift test, `gen_hooks.py --check`,
  fails the build if they diverge from the registry). A plugin-only hook (no CLI scaffold equivalent,
  e.g. `guard-kubectl-delete`) goes in `PLUGIN_ONLY_HOOKS` with a `reason` instead of the registry.
  (Exception: the agent-side capture hooks `capture-learnings[-catchup|-stop]` are **not** profile-listed
  — they're installed by the init-time `capture_mode` choice via `catalog/capture.yaml` +
  `catalog._apply_capture_mode`. One script, three triggers, dispatched by an arg.)
- **Stack** (framework / database) → a **data change**: add an entry to `catalog/stacks.yaml`
  (`label`, `overlay_rules`, optional `overlay_agents`, `skills`, `stack_dir`, `commands`) and create
  `templates/stacks/<stack_dir>/rules/<name>.md` (+ `agents/` for a database). Mark not-yet-ready
  entries `status: planned`. No Python change is needed — `catalog.resolve()` must stay branch-free.
- **Profile** → add an entry to `catalog/profiles.yaml` (compose with `inherit:`; `all` selects
  everything). Every referenced gate must have one canonical `gate_definitions` entry; required
  gates set `skippable: false`, while conditional gates enumerate exact `skip_conditions`.
  **MCP server** → add an entry to `catalog/mcp.yaml` with a `config` fragment using
  `${ENV}` placeholders (never real credentials).

## Local testing

```bash
# Plugin (dogfood this checkout):
#   in Claude Code:  /plugin marketplace add .   then   /plugin install claude-kit@claude-kit

# CLI:
pip install -e '.[dev]'
claude-kit list-options
claude-kit init ./ck-demo --defaults && ls -R ./ck-demo/.claude
claude-kit validate ./ck-demo
claude-kit diff ./ck-demo

# Tests:
pytest

# Lint / type / shell / drift checks (all run in CI — keep them green locally):
ruff check src scripts tests && ruff format --check src scripts tests
mypy
shellcheck -S warning hooks/scripts/*.sh scripts/*.sh
python scripts/gen_hooks.py --check
python scripts/check_docs_consistency.py
python scripts/check_cross_references.py --strict
python scripts/check_skill_descriptions.py --strict
python scripts/check_rule_sizes.py
python scripts/check_mcp_pins.py
claude plugin validate . --strict

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

1. Bump the version in **all five** places: `pyproject.toml`, `.claude-plugin/plugin.json`, the
   `.claude-plugin/marketplace.json` entry, `src/claude_kit/__init__.py`, and `SECURITY.md`
   (`check_docs_consistency.py` enforces parity across all of them + the latest `CHANGELOG.md` heading).
2. Add a `CHANGELOG.md` entry, including a **"Not adopted (deliberately)"** block stating what you
   chose *not* to add and why — this is a marketed feature of the changelog (the README links to it),
   so keep it. If those blocks ever grow unwieldy they may later split into `docs/decision-log.md`,
   but **only if** the README's CHANGELOG cross-reference is updated in the same change; until then
   they stay in `CHANGELOG.md` by design.
3. `pytest` and every static/drift check green, then `python3 -m build` and
   `python3 -m twine check dist/*`. Run the official `claude plugin validate . --strict` at the
   declared minimum and current stable Claude Code versions (CI owns that matrix).
4. CI builds wheel + sdist **once**, smoke-tests the exact wheel, writes `SHA256SUMS`, and uploads the
   `verified-dist` artifact. The publish workflow authenticates the successful main-branch CI run and
   promotes those exact files through OIDC Trusted Publishing with PEP 740 and GitHub artifact
   attestations. It must never rebuild or use `skip-existing`.
5. The tag and GitHub Release are created from the verified commit and receive the same wheel, sdist,
   and checksum manifest. A partial release is recovered by dispatching the documented workflow for
   the original CI run; do not make an ad-hoc local rebuild. Follow
   [`docs/operations/release-recovery.md`](docs/operations/release-recovery.md).
6. Publish the context-cost report for the release: run `claude plugin details claude-kit@claude-kit`
   in Claude Code and paste the token/context figures into the release notes, so users can see what
   the plugin costs their context window before installing.

## License

By contributing you agree your contributions are licensed under the project's [MIT License](LICENSE).
