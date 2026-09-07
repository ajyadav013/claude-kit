# Contributing to claude-kit

Thanks for helping improve claude-kit! This guide covers the repo conventions, how to test
locally, and how to release. Participation is governed by our [Code of Conduct](CODE_OF_CONDUCT.md);
security issues go through [SECURITY.md](SECURITY.md) rather than a public issue.

## Mental model

- Provider-neutral component sources live under `canonical/`; workflow and selection data live under
  `catalog/`; semantic hook definitions live in the Python hook registry. Root `agents/`, `skills/`,
  `commands/`, `rules/`, and compatible template files are **generated provider payloads**, not a
  second authoring surface.
- Deterministic generators produce the established Claude-compatible root payload and both provider
  manifests. Codex scaffolding consumes the same canonical definitions through its renderer. The
  wheel bundles these sources/outputs under `claude_kit/_payload/` via `force-include`.
- `src/claude_kit/` is the pip CLI and the only supported scaffolder. `scripts/init.sh` is a
  compatibility dispatcher to that CLI; it performs no project writes. Do not reimplement catalog
  resolution or filesystem mutation in bash.
- claude-kit installs **configuration only** — never application code, never Docker.

## Golden rules

1. **Keep the canonical core stack-agnostic.** No language/framework/Docker assumptions in core
   canonical rules, agents, or skills. Use neutral phrasing ("the project's linter / test runner / build"); the
   `devops-engineer` is container-optional. The backend/frontend split may appear only as the
   canonical example of two independent parallel work streams.
2. **All stack-specific source lives in canonical stack subtrees** and is wired via
   `catalog/stacks.yaml`; generators project compatibility rules/DB agents under
   `templates/stacks/<kind>/<id>/`. Nothing stack-specific belongs in the canonical core.
3. **Use symbolic component references in canonical sources.** Physical `.claude`, `.codex`,
   `CLAUDE.md`, `AGENTS.md`, model names, permission syntax, and provider tool identifiers belong at
   renderer/generator boundaries, not in neutral component bodies.
4. **Plugin components live at the repo root.** Provider manifest/marketplace files are generated
   from `catalog/plugin-metadata.yaml`; never duplicate payload components inside provider metadata
   directories and never hand-edit the generated JSON.
5. **Hooks are semantic first.** Register events/handlers once, generate provider registrations, and
   keep provider input/output adaptation at the hook boundary. Missing tools degrade safely; Codex
   trust and unsupported events must be reported rather than implied equivalent.
6. **All project mutations go through `ProjectFS`.** Treat a target checkout, `.ckit/`, `.claude/`,
   and `.codex/` as
   untrusted: no direct `Path.write_*`, `mkdir`, rename, unlink, `shutil.copy*`, or recursive delete
   in installer, upgrader, or pipeline-state paths. Keep mutation-time ancestry/leaf checks and add
   adversarial symlink/reparse tests for every new destination class.
7. **Workflow and gate policy are structured data.** Role routing, dependencies, parallel lanes,
   retries, evidence requirements, and ordered/conditional gates live in `catalog/workflows/` and the
   profile gate registry. Do not reproduce provider tool names or policy in CLI branches or prose.
   Run installs persist the definition digest so state cannot silently inherit changed policy.
8. **Maker/reviewer bindings are installation policy, not selection data.** Keep them on
   `InstallRequest` / `InitOptions` and in the single `.ckit` control plane; never add runtime or
   model fields to `Selection` or branch inside `catalog.resolve()`. Canonical maker/checker roles
   remain provider-neutral and passive. Exact model IDs belong only in project configuration and
   provider adapters.

## Adding components

- **Agent** → add a schema-valid definition under `canonical/agents/` with semantic capabilities,
  fast/balanced/deep tier, permission class, write scope, isolation, delegation, required skills, and
  symbolic references. Add its ID to the relevant profile, then run
  `python scripts/gen_provider_payloads.py`.
- **Skill or command** → add it under `canonical/skills/` or `canonical/commands/`, keeping the
  description focused on *when* to use it and avoiding provider invocation syntax. Update the
  profile if needed, then run `python scripts/gen_canonical_skill_payloads.py`.
- **Rule or template** → add it under `canonical/rules/` or `canonical/templates/` with separate
  applicability/path-glob metadata and symbolic placeholders, then run
  `python scripts/gen_provider_payloads.py`.
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
  the corresponding canonical stack rule/agent source. Mark not-yet-ready entries `status: planned`.
  No provider or stack branch belongs in `catalog.resolve()`.
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
ckit list-options
ckit init ./ck-demo --defaults --runtime claude
CKIT_EXPERIMENTAL=1 ckit init ./ck-demo-codex --defaults --runtime codex
CKIT_EXPERIMENTAL=1 ckit init ./ck-demo-both --defaults --runtime both
ckit validate ./ck-demo --strict
ckit diff ./ck-demo
ckit maker-checker configure ./ck-demo \
  --maker-provider claude --maker-model-tier deep \
  --reviewer-provider claude --reviewer-model-tier balanced
ckit maker-checker probe ./ck-demo

# Tests:
pytest

# Lint / type / shell / drift checks (all run in CI — keep them green locally):
ruff check src scripts tests && ruff format --check src scripts tests
mypy
shellcheck -S warning hooks/scripts/*.sh scripts/*.sh
python scripts/gen_hooks.py --check
python scripts/gen_provider_payloads.py --check
python scripts/gen_canonical_skill_payloads.py --check
python scripts/gen_provider_manifests.py --check
python scripts/check_docs_consistency.py
python scripts/check_cross_references.py --strict
python scripts/check_skill_descriptions.py --strict
python scripts/check_rule_sizes.py
python scripts/check_mcp_pins.py
claude plugin validate . --strict

# Focused provider/runtime conformance:
pytest -q tests/test_codex_renderer.py tests/test_claude_renderer.py \
  tests/test_runtime_scaffold.py tests/test_runtime_upgrader.py \
  tests/test_cross_runtime_pipeline.py tests/test_hook_adapter.py \
  tests/test_maker_checker.py tests/test_maker_checker_cli.py

# Build + validate the package:
python3 -m build
python3 -m twine check dist/*
```

Verify there's no stack/Docker leakage in the **core** payload before opening a PR (stack specifics
belong under `templates/stacks/`, which is intentionally excluded here):

```bash
rg -n -i 'fastapi|sqlalchemy|alembic|docker' \
  canonical/agents/core canonical/rules/core canonical/skills/core \
  && echo "REVIEW these" || echo "clean"
```

(Balanced multi-framework *example* lists are acceptable; a real leak is agnostic logic branching on
a specific stack — `pytest` enforces the no-Docker invariant on a scaffolded project.)

## Releasing

1. Bump the version in `pyproject.toml`, `src/claude_kit/__init__.py`, and `SECURITY.md`, then run
   `python scripts/gen_provider_manifests.py`. The generator derives the Claude Code manifest,
   Claude marketplace version, and Codex manifest version from `pyproject.toml`; the native Codex
   marketplace has no version field. `check_docs_consistency.py` enforces parity across all versioned
   outputs and the latest `CHANGELOG.md` heading.
2. Add a `CHANGELOG.md` entry, including a **"Not adopted (deliberately)"** block stating what you
   chose *not* to add and why — this is a marketed feature of the changelog (the README links to it),
   so keep it. If those blocks ever grow unwieldy they may later split into `docs/decision-log.md`,
   but **only if** the README's CHANGELOG cross-reference is updated in the same change; until then
   they stay in `CHANGELOG.md` by design.
3. `pytest` and every static/drift check green, then `python3 -m build` and
   `python3 -m twine check dist/*`. Run the official Claude plugin validator at the declared minimum
   and current stable versions, and the isolated Codex plugin lifecycle at its pinned versions. CI
   owns both compatibility matrices.
4. CI builds wheel + sdist **once**, checks repeated-build byte reproducibility, then runs isolated
   source/wheel/sdist `claude`, `codex`, and `both` init + strict-validation smokes before writing
   `SHA256SUMS` and uploading the
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
