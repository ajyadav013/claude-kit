# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# Developing claude-kit

This repository **is** claude-kit — an evidence-gated SDLC for Claude Code: a scaffolder that
installs a stack-agnostic, autonomous-SDLC **configuration** (no application code, no Docker) into
a Claude Code project. It is
distributed two ways from one source of truth:

1. **As a Claude Code plugin** — components are auto-discovered from the repo root.
2. **As a pip package** — `claude-kit` (CLI: `claude-kit` / `ckit` / `claude-sdlc`) scaffolds the
   same content into any project's `.claude/`, driven by the `catalog/` (stacks · profiles · MCP).

> Note: the files in this repo are the **kit's payload**, not rules for this repo itself. The
> generic engineering ruleset that gets installed into user projects lives in
> `templates/CLAUDE.md`, **not** this file.

## Core architecture

The kit's central data flow is **Selection → catalog.resolve() → ResolvedPlan → scaffold.install_sdlc()**:

1. **`Selection`** (`models.py`) — user choices (stack, profile, MCP servers, scope, autonomy, …)
   collected interactively by `prompts.py` or passed via `--defaults`/`--config`.
2. **`catalog.resolve()`** (`catalog.py`) — reads `catalog/stacks.yaml`, `profiles.yaml`,
   `mcp.yaml`, `org.yaml` and resolves the Selection into a **`ResolvedPlan`**: which agents,
   skills, hooks, overlay rules, overlay agents, gates, and MCP fragments to install. This
   function must stay **branch-free** — no stack- or org-specific code paths.
3. **`scaffold.install_sdlc()`** (`scaffold.py`) — takes the ResolvedPlan and writes files into
   the target project: `CLAUDE.md`, `.claude/{rules,agents,skills,hooks,templates,config}`,
   optional `.mcp.json` and org packs. Records per-file checksums + ownership in
   `.claude/config/init-options.json` for safe upgrades.
4. **`upgrader.upgrade()`** (`upgrader.py`) — compares the live install against the plan from the
   current kit version, refreshes kit/overlay files whose checksums match, preserves user-edited
   files (drops new versions as `.claude-kit` sidecars), and writes a transactional journal
   (`upgrade-in-progress.json`) so an interrupted run can be safely resumed.
5. **`export`** (`export.py`) — projects the same `ResolvedPlan` into Cursor (`.cursor/rules/*.mdc`),
   a root `AGENTS.md`, or GitHub Copilot (`.github/copilot-instructions.md`) for non-Claude-Code editors.

### key source modules

| Module | Role |
|--------|------|
| `cli.py` | Typer app — all CLI commands (`init`, `validate`, `doctor`, `diff`, `export`, `upgrade`, `pipeline`, `list-options`, `status`, `privacy-report`). Experimental/planned commands are hidden unless `CLAUDE_KIT_EXPERIMENTAL=1`. |
| `models.py` | Dataclass contracts: `Selection`, `ResolvedPlan`, `OrgPlan`, `InitOptions`, `FileRecord`, `UpgradeJournal`. The typed seam between prompts → resolver → installer → upgrader. |
| `catalog.py` | The resolver — converts a `Selection` into a `ResolvedPlan` by reading the catalog YAML files. Must stay branch-free. |
| `prompts.py` | Interactive `init` question flow (stack, profile, MCP, org scope, …). |
| `scaffold.py` | Writes the resolved plan to disk. Also provides `payload_dir()` which locates the bundled payload (source checkout or wheel `_payload/`). |
| `render.py` | Jinja2 rendering — `CLAUDE.md` and `README.claude-sdlc.md` templates. |
| `hooks.py` | The `HOOK_REGISTRY` (all hook definitions + script mappings) plus `PLUGIN_HOOK_IDS`, `STARTER_HOOK_IDS`, and `PLUGIN_ONLY_HOOKS`. Contains the drift-test logic used by `gen_hooks.py --check`. |
| `upgrader.py` | Safe, edit-preserving upgrade: checksum comparison, transactional journal, sidecar fallback for user-edited files. |
| `validator.py` | Structural validation of an installed config (`validate` + `--strict` mode). |
| `schemas.py` | JSON Schema definitions for catalog integrity checks (`validate --strict`). |
| `pipeline.py` | Deterministic `/sdlc` state-file ops (validate, status, close-gate, skip-gate, abort) — owns the append-only `gate_history` ledger (order enforcement, evidence sha256, atomic locked writes); inspects/records state, does **not** run the pipeline. |
| `export.py` | Projection into Cursor / AGENTS.md / Copilot formats. |
| `detect.py` | Stack detection from a target repo (heuristic-based; non-blocking). |
| `report.py` | Human-readable reporting for `doctor` and `status` commands. |
| `__init__.py` | The `__version__` string — one of the five places that must be bumped on release. |

## Repository layout

| Path | Purpose |
|------|---------|
| `.claude-plugin/plugin.json` | Plugin manifest (name, version, hooks path) |
| `.claude-plugin/marketplace.json` | Marketplace entry so `/plugin marketplace add` works |
| `agents/` | SDLC pipeline subagents (auto-discovered by the plugin); each carries a `tier:` field |
| `skills/` | Agent skills (auto-discovered by the plugin); `skills/sdlc/` is the `/sdlc` entrypoint |
| `commands/` | Slash commands: `/claude-kit:init`, `:sdlc`, `:status`, `:abort` (init prefers the pip CLI, falls back to `init.sh`; sdlc delegates to the `sdlc` skill; abort tears down an in-progress `/sdlc` run) |
| `hooks/hooks.json` + `hooks/scripts/` | Event hooks (paths via `${CLAUDE_PLUGIN_ROOT}`) |
| `rules/` | The 25-file stack-agnostic engineering rule set (scaffolded into `.claude/rules/`), including the agent-operation rules (reasoning, guardrails, resilience, goal-setting, human-in-the-loop, model-tiers, evals, tool-design — see `docs/agentic-patterns.md`), the program-scale `wave-orchestration` rule, the service-level `resilience-engineering` rule, and the org-core rules `autonomy-levels` + `risk-classification` (see `docs/org-capabilities.md`) |
| `catalog/` | **Data-driven registry** — `stacks.yaml` · `profiles.yaml` · `mcp.yaml` · `org.yaml`. The only thing that decides what `resolve()` installs. Adding a stack/profile/server/pack is a data change here. |
| `templates/` | `CLAUDE.md`, `CLAUDE.stack.md.tmpl`, `README.claude-sdlc.md.tmpl`, `CONTINUITY.template.md`, `settings.json`, `artifacts/`, `agent-memory/` seed |
| `templates/stacks/<kind>/<id>/` | Per-stack **overlay** content: `rules/` (+ `agents/` for DB stacks). **No application code, no Docker** — the only place stack-specific content lives. |
| `templates/org/` | **Org overlay** content (scope-gated, organization only): `skills/`, `agents/` (personas), `rules/` (policy/vibe), `packs/<pack>/{pack.yaml,README.md}`, `README.md`. Wired via `catalog/org.yaml`. The only place org-specific content lives. |
| `scripts/init.sh` | Thin no-pip fallback scaffolder (copies the full payload; no catalog resolution) |
| `src/claude_kit/` | The pip CLI (Typer): `cli.py`, `catalog.py` (resolver), `prompts.py`, `models.py`, `scaffold.py` (installer), `render.py` (Jinja2), `hooks.py`, `validator.py` (incl. `validate --strict` + `check_catalog`), `upgrader.py`, `pipeline.py` (deterministic `/sdlc` state-file ops) |
| `tests/` | pytest suite (catalog, render, scaffold, validator, upgrader, CLI; incl. the profile×stack×scope self-test matrix) |
| `examples/` | Synthetic end-to-end `/sdlc` worked example (repo reference; **not** bundled into the wheel) |
| `docs/architecture.md` · `docs/agents.md` · `docs/coverage-audit.md` · `docs/eval-harness.md` | Architecture diagrams · agent guide · the GATED-vs-RULE-vs-SKILL enforcement audit · the with/without eval template |
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
   land in a user project). The current core rule set is the 25 files in `rules/` (org policy/vibe
   rules under `templates/org/rules/` install only in organization scope).
3. **Plugin components live at the repo root**, never inside `.claude-plugin/` (only the
   manifest goes there).
4. **Hook scripts use `${CLAUDE_PLUGIN_ROOT}`** for plugin context and degrade to no-ops when
   a tool isn't present (stack detection, never hard failure).
5. **Never hand-edit `hooks/hooks.json` or `templates/settings.json`.** These are generated by
   `python scripts/gen_hooks.py` from the `HOOK_REGISTRY` in `src/claude_kit/hooks.py`. Adding a
   hook means: add the script → register it in `hooks.py` → list it in the relevant profile(s) →
   run `gen_hooks.py`. A drift test (`gen_hooks.py --check`) fails CI if the generated files
   diverge from the registry.
6. **Bump the version in all five places** together for a release — `pyproject.toml`,
   `.claude-plugin/plugin.json`, the `.claude-plugin/marketplace.json` entry,
   `src/claude_kit/__init__.py` (`__version__`), and `SECURITY.md` — and add a `CHANGELOG.md`
   entry (including a "Not adopted (deliberately)" block). `check_docs_consistency.py` enforces
   parity across all five + the latest CHANGELOG.md heading.
7. **Extend via the catalog, not code.** A new framework/database/profile/MCP server is a
   `catalog/*.yaml` edit plus a `templates/stacks/<dir>/` folder; a new org pack/team/autonomy level
   is a `catalog/org.yaml` edit plus content under `templates/org/`. `catalog.resolve()` must not grow
   stack- or org-specific branches (the org layer is the same scope-gated lookup/union as profiles/mcp).
   Mark not-yet-shipped entries `status: planned`.
8. **Keep the org layer scope-gated and reuse-first.** Org content installs **only** when
   `scope == organization`; packs MAP roles to existing components (`existing: true`) and create only
   genuinely-new content (`existing: false`) — never a competing duplicate of an existing
   agent/skill/rule. Org rules/skills/agents are stack-agnostic too. See `docs/org-capabilities.md`.

## Dogfooding / local testing

- **Plugin:** `claude` → `/plugin marketplace add .` → `/plugin install claude-kit@claude-kit` (loads the
  agents/skills/commands/hooks from this checkout).
- **CLI:** `pip install -e '.[dev]'` then `claude-kit init /tmp/demo --defaults` (or interactive),
  `claude-kit validate /tmp/demo`, `claude-kit diff /tmp/demo`, and inspect the result.
- **Tests:** `pytest` runs the full suite. Run a single test with `pytest tests/test_catalog.py -k "test_name"`.
  The suite calls library functions directly (no subprocess) for speed and determinism, using the
  bundled payload resolved via `scaffold.payload_dir()`. Key invariants asserted: no-Docker,
  profile-subset (`lean ⊂ standard ⊂ enterprise`), MCP-gating, upgrade-safety, and export parity.
- **Lint & drift (all run in CI — keep them green locally):**
  ```bash
  ruff check src scripts tests && ruff format --check src scripts tests
  mypy
  shellcheck -S warning hooks/scripts/*.sh scripts/*.sh
  python scripts/gen_hooks.py --check          # hooks.json + settings.json drift
  python scripts/check_docs_consistency.py     # version parity + CHANGELOG heading
  python scripts/check_cross_references.py --strict    # rule/skill/agent refs in prose exist
  python scripts/check_skill_descriptions.py --strict  # descriptions within the 250-char picker cap
  ```
- **Stack-leakage guard:** `grep -rInE 'fastapi|sqlalchemy|alembic|docker' rules agents skills` — should
  be clean (balanced multi-framework *example* lists are acceptable; a real leak is agnostic logic
  branching on a specific stack).
- **Build:** `python3 -m build && python3 -m twine check dist/*`.
- **CI:** Tests + lint + drift checks run on every PR. Publishing to PyPI happens automatically on
  merge to `main` via OIDC trusted publishing when the version is new (`.github/workflows/publish.yml`).

### Test conventions

- Tests mirror the `src/claude_kit/` module they exercise: `test_catalog.py` tests `catalog.py`, etc.
- `tests/_helpers.py` provides reusable factory functions.
- `tests/conftest.py` exposes a session-scoped `payload` fixture pointing at the bundled payload root.
- The profile×stack×scope self-test matrix backs the stack-agnostic claim — every profile installs a
  strict subset of the next (`lean ⊂ standard ⊂ enterprise`).

### Releasing

1. Bump the version in **all five** places (see golden rule #6 above).
2. Add a `CHANGELOG.md` entry with a **"Not adopted (deliberately)"** block.
3. Ensure `pytest` + all lint/drift checks are green.
4. Build: `python3 -m build && python3 -m twine check dist/*`.
5. Merge to `main` — CI auto-publishes to PyPI (OIDC trusted publishing). Manual `twine upload` is
   the fallback.
6. Nothing to tag by hand — `publish.yml`'s `github-release` job creates the `vX.Y.Z` tag and the
   GitHub Release on every successful publish (since 0.57.0). `scripts/backfill-releases.sh
   --dry-run` is the recovery path if a published version is ever missing its tag.

See `CONTRIBUTING.md` for the full contributor workflow.
