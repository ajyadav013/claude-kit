# Installing claude-kit

The recommended entry point is the `ckit` CLI. The PyPI package remains
`claude-code-kit`, and the established `claude-kit` and `claude-sdlc` command aliases remain
supported.

Claude Code scaffolding is stable. Native Codex and dual-runtime scaffolding are **Preview** and
must be enabled explicitly. See the normative [runtime support contract](runtime-support.md) before
depending on a Preview mapping.

## Prerequisites

- Python 3.9 or newer for the CLI.
- [Claude Code](https://www.claude.com/product/claude-code), Codex, or both, according to the
  runtime you select.
- `jq` for shell hook adapters. Hooks that need it no-op when it is unavailable.
- Node.js / `npx` only for selected MCP servers that launch through `npx`.

On native Windows, project-mutating commands fail closed because the current secure filesystem
backend requires POSIX descriptor and lock semantics. Use WSL on a POSIX-semantics filesystem.
Plugin discovery and read-only inspection can still work natively. Shell hooks also require a POSIX
shell.

## Install the CLI

```bash
pipx install claude-code-kit
# Or inside a virtual environment:
pip install claude-code-kit

ckit version
```

The aliases below enter the same CLI:

- `ckit` — recommended in new documentation and automation.
- `claude-kit` — compatibility alias.
- `claude-sdlc` — compatibility alias.

## Quick start: Claude Code

Use an explicit runtime on a new install so it receives the provider-neutral `.ckit` control plane:

```bash
ckit init . --defaults --runtime claude
ckit validate . --strict
ckit doctor .
```

Restart Claude Code so it discovers the new project configuration, then run:

```text
/sdlc Add a CSV export button to the reports page
```

For backward compatibility, omitting `--runtime` still enters the legacy Claude-only installer.
New installations should spell out `--runtime claude`.

When starting from the Claude plugin instead of the CLI, `/claude-kit:init` remains the
backward-compatible implicit-Claude path; use the explicit `--runtime claude` command above when a
fresh install must use the provider-neutral `.ckit` control plane. The plugin command asks the
selection questions in chat and delegates to the installed Python CLI. It requires
`pipx install claude-code-kit` (or `pip install claude-code-kit`) because the CLI resolves the
stack/profile/MCP catalog and records `init-options.json` for safe `upgrade` and `diff`. If `ckit`
is not on `PATH`, it stops without making a partial install. The historical shell scaffolder was
retired in 0.83.0 because it could not provide the Python installer's containment and rollback
guarantees; `scripts/init.sh` now only delegates to the installed CLI.

## Quick start: Codex Preview

Codex and `both` are opt-in while their protected live-host promotion gates remain open:

```bash
CKIT_EXPERIMENTAL=1 ckit init . --defaults --runtime codex
ckit validate . --strict
ckit doctor .
```

Trust the project in Codex before relying on project hooks. Open the project and explicitly invoke
the workflow skill:

```text
$sdlc Add a CSV export button to the reports page
```

Codex skills use `$skill-name`; Claude slash-command syntax is not copied into the native Codex
projection.

## Quick start: both runtimes Preview

```bash
CKIT_EXPERIMENTAL=1 ckit init . --defaults --runtime both
ckit validate . --strict
ckit doctor .
```

Open the same checkout in Claude Code or Codex. Both native discovery surfaces refer to exactly one
`.ckit` manifest, continuity file, upgrade journal, and gate ledger. Do not copy `.ckit` into either
host directory.

## Exact emitted layouts

The trees below show the native topology for a fresh default selection. Profiles, stacks, scope,
and selected MCP servers change the files inside each component directory.

### `--runtime claude`

```text
.ckit/CONTINUITY.md
.ckit/agent-memory/
.ckit/artifacts/
.ckit/config/
.ckit/scripts/
.ckit/state/
.ckit/tmp/
.claude-kit-managed-execution.lock
.claude/agents/
.claude/hooks/
.claude/rules/
.claude/scripts/
.claude/settings.json
.claude/skills/
.claude/templates/
.gitignore
CLAUDE.md
README.claude-sdlc.md
```

Selecting Claude MCP servers additionally emits `.mcp.json` and, when locked, `.mcp.lock.json`.

### `--runtime codex`

```text
.agents/skills/
.ckit/CONTINUITY.md
.ckit/CONTINUITY.template.md
.ckit/README.sdlc.md
.ckit/STACK.md
.ckit/agent-memory/
.ckit/artifacts/
.ckit/config/
.ckit/rules/
.ckit/scripts/
.ckit/state/
.ckit/templates/
.ckit/tmp/
.claude-kit-managed-execution.lock
.codex/agents/
.codex/config.toml
.codex/hooks.json
.codex/hooks/scripts/
.gitignore
AGENTS.md
```

### `--runtime both`

```text
.agents/skills/
.ckit/CONTINUITY.md
.ckit/CONTINUITY.template.md
.ckit/README.sdlc.md
.ckit/STACK.md
.ckit/agent-memory/
.ckit/artifacts/
.ckit/config/
.ckit/rules/
.ckit/scripts/
.ckit/state/
.ckit/templates/
.ckit/tmp/
.claude-kit-managed-execution.lock
.claude/agents/
.claude/hooks/
.claude/rules/
.claude/scripts/
.claude/settings.json
.claude/skills/
.claude/templates/
.codex/agents/
.codex/config.toml
.codex/hooks.json
.codex/hooks/scripts/
.gitignore
AGENTS.md
CLAUDE.md
README.claude-sdlc.md
```

Each directory line is a topology family, not a claim that every profile emits the same members.
The lists are checked against a fresh default install in the repository test suite. The `both`
list contains the union of native surfaces and only one `.ckit` family. The ignored root-level
`.claude-kit-managed-execution.lock` is a persistent kernel-lock anchor, not a second state ledger.

The installer also manages relevant `.gitignore` entries. Presence of `CLAUDE.md`, `AGENTS.md`,
`.claude`, or `.codex` is not the runtime authority; `.ckit/config/init-options.json` is.

## Interactive choices and config files

`ckit init` resolves the same provider-neutral selection for every runtime:

1. target project and safe merge behavior;
2. frontend framework/language, backend language/framework, and database;
3. `lean`, `standard`, or `enterprise` profile;
4. optional MCP integrations;
5. opt-in learning capture mode;
6. individual, team, or organization scope and any organization follow-ups; and
7. an optional maker/reviewer provider and model policy for explicit maker–checker runs.

Runtime is deployment metadata, not part of stack/profile catalog resolution. A non-interactive
configuration can include it at the top level:

```yaml
runtime: codex                       # claude · codex · both
frontend: {framework: react, language: typescript}
backend: {language: python, framework: fastapi}
database: postgres
profile: standard                     # lean, standard, enterprise
mcp: [github]                         # [] = none; ids from `ckit list-options`
capture_mode: "off"                   # off, session-end, session-end-catchup, per-task
scope: team                           # individual, team, organization
execution:
  strategy: maker-reviewer
  maker:
    provider: claude
    model: {kind: tier, value: deep}  # inherit · tier (fast/balanced/deep) · exact
  reviewer:
    provider: codex
    model: {kind: exact, value: YOUR_CODEX_MODEL_ID}
  max_revisions: 2                    # 0-3; revisions after the initial iteration
```

`YOUR_CODEX_MODEL_ID` is a placeholder. Replace it with an exact ID accepted by the installed Codex
host; claude-kit does not invent or persist a provider-wide default ID.

For Codex or `both`, the environment switch is still required even when `runtime` comes from the
YAML file:

```bash
CKIT_EXPERIMENTAL=1 ckit init . --config init.yaml
```

`execution` is optional, and `--defaults` leaves it absent. Each role must use a concrete provider
included in `runtime`; use `runtime: both` for a cross-provider pair. Exact model IDs are persisted,
but credentials are not. Change or disable the pair after installation with
`ckit maker-checker configure|show|probe|disable`; see the
[maker–checker guide](maker-checker.md) for the three model-selection forms, `validate`/`doctor`
diagnostics, and probe limits.

Use `ckit list-options` for current catalog IDs. Secrets are never written into the configuration;
MCP entries use environment placeholders.

## Stacks and overlays

The stack-agnostic core never requires a particular language, framework, database, container tool,
or Docker. The catalog currently selects among **15 stack overlay rule files** for React, FastAPI,
Django, Go/net-http, Express, PostgreSQL, and MongoDB. Path-glob metadata is projected into Claude
scoped rules and retained in Codex's complete `.ckit/rules` set while the bounded `AGENTS.md` layer
stays under its host size budget. Unselected lanes install no off-stack rules, skills, agents, or
commands. Every lane also offers `none`, so backend-only, frontend-only, and no-database projects do
not receive irrelevant guidance. Selecting React additionally installs its design-system, UX, and
mobile/Capacitor guidance.

## Watching a managed run

The SDLC workflow can open the ticket board after stories are approved and before implementation
starts. `ckit tickets --open` writes `.ckit/state/ticket-board.html` for runtime-aware installs and
launches the browser; the implicit legacy Claude installer retains `.claude/state/ticket-board.html`.
Claude transcript metadata can enrich the board through the `capture-ticket-telemetry` Stop hook;
automatic Codex host telemetry is not claimed. The board is one self-contained file with no
JavaScript, network request, daemon, or server.

## Plugin installation is narrower than scaffolding

Plugins expose static components that a host can discover. They do not run catalog selection or
the projection compiler. A plugin cannot choose a stack/profile/scope, create or migrate `.ckit`,
perform ownership-aware upgrades, or install project `CLAUDE.md`, `AGENTS.md`, and project custom
agents. Use the CLI for those capabilities.

This boundary also applies to `maker-checker`: the generated plugin exposes the explicit
`/maker-checker` or `$maker-checker` skill, but the skill cannot run until the project scaffolder has
created `.ckit` and the owner has configured a pair.

### Claude Code plugin

```text
/plugin marketplace add ajyadav013/claude-kit
/plugin install claude-kit@claude-kit
```

The plugin exposes its Claude skills, commands, agents, and hooks. In a project,
`/claude-kit:init` delegates to the installed Python CLI's compatibility installer; use
`ckit init . --runtime claude` for the provider-neutral `.ckit` path, then restart Claude Code. If
`ckit` is not on `PATH`, the plugin command stops without performing a partial shell install.

The plugin is cached, so `/reload-plugins` alone does not fetch new code. Refresh the marketplace
snapshot before loading an update:

```text
/plugin marketplace update claude-kit
/plugin update claude-kit@claude-kit
/reload-plugins
```

### Codex plugin Preview

From a local checkout, Codex's non-credentialed lifecycle is:

```bash
codex plugin marketplace add /path/to/claude-kit --json
codex plugin list --available --json
codex plugin add claude-kit@claude-kit --json
```

The repository marketplace and plugin add/content/list/remove lifecycle are exercised in isolated
host tests. The plugin provides the static subset documented in
[runtime-support.md](runtime-support.md#plugin-limits); use `ckit init --runtime codex` for native
project instructions, custom agents, selected rules, `.ckit`, and lifecycle operations.

## Trust, duplication, and project ownership

- Review generated hooks and MCP entries before trusting a project. Codex does not run non-managed
  project hooks until the project is trusted.
- Installing the plugin and scaffolding a project can make the same logical skill visible from two
  sources. `ckit doctor` reports detectable project-local duplication; it does not inspect every
  user-level host registry.
- The scaffold records ownership and checksums in `.ckit/config/init-options.json`. `ckit diff`
  previews an upgrade. User-modified managed files are preserved and receive a `.claude-kit`
  sidecar instead of being silently replaced.
- A runtime transition that removes a native provider surface requires
  `--confirm-runtime-removal` and uses the existing backup/rollback machinery.
- A provider named by an active frozen maker–checker run cannot be removed, even if the current pair
  was reconfigured or disabled. Resume that exact run or use `ckit pipeline abort .`, then retry the
  transition.

## Migrating an existing Claude install

Do not manually move `.claude/state` into `.ckit`. The migration is non-destructive,
transactional, and resumable:

```bash
CKIT_EXPERIMENTAL=1 ckit migrate-state .
# Or migrate while selecting the first native projection:
CKIT_EXPERIMENTAL=1 ckit init . --defaults --runtime codex --migrate-state
```

If both legacy and neutral state exist, `.ckit` is authoritative and legacy state is retained for
diagnostics during the compatibility window. Runtime transitions are described in
[runtime migration](runtime-migration.md).

## Learning capture and privacy

Capture defaults to `off`, including non-interactive installs. When enabled, it writes bounded,
redacted learnings to `.ckit/agent-memory/`. Use the provider-neutral names in new automation:

```bash
CKIT_NO_AUTOCAPTURE=1
CKIT_CAPTURE_MAX_LINES=400
CKIT_CAPTURE_MAX_BYTES=65536
ckit privacy-report .
```

The corresponding legacy names remain accepted during the compatibility window. User-facing
environment variables are:

| Preferred | Compatibility alias | Purpose |
|---|---|---|
| `CKIT_EXPERIMENTAL` | `CLAUDE_KIT_EXPERIMENTAL` | Expose Preview/planned CLI surfaces; Codex/`both` installation requires it |
| `CKIT_NO_AUTOCAPTURE` | `CLAUDE_KIT_NO_AUTOCAPTURE` | Disable learning capture |
| `CKIT_CAPTURE_MAX_LINES` | `CLAUDE_KIT_CAPTURE_MAX_LINES` | Bound captured context by lines |
| `CKIT_CAPTURE_MAX_BYTES` | `CLAUDE_KIT_CAPTURE_MAX_BYTES` | Bound captured context by bytes |
| `CKIT_CAPTURE_MODEL` | `CLAUDE_KIT_CAPTURE_MODEL` | Override the capture job's provider model where supported |
| `CKIT_NO_TELEMETRY` | `CLAUDE_KIT_NO_TELEMETRY` | Disable ticket telemetry enrichment |
| `CKIT_TELEMETRY_INTERVAL` | `CLAUDE_KIT_TELEMETRY_INTERVAL` | Bound telemetry refresh frequency |
| `CKIT_AUTOFIX` | `CLAUDE_KIT_AUTOFIX` | Control the opt-in lint-fix hook behavior |

The fail-closed loop currently accepts no runtime, budget, iteration, sandbox, or prompt knobs and
never launches a host. Former `CKIT_RUNTIME`, `CKIT_SDLC_*`, `CKIT_CODEX_SANDBOX`, and legacy
`SDLC_*` values do not authorize execution. See [autonomous operation](autonomous-operation.md).
`CKIT_PROJECT_ROOT` and `CKIT_HOOK_PROVIDER` are adapter-owned context variables, not user
configuration.

Codex capture uses the changed-path set and a provider background task; historical Claude transcript
catch-up and automatic Codex ticket telemetry are not claimed. See [Security](../SECURITY.md).

## Next steps

- [CLI reference and troubleshooting](cli.md)
- [Runtime support matrix](runtime-support.md)
- [Configurable maker–checker](maker-checker.md)
- [Migration between runtimes](runtime-migration.md)
- [Autonomous operation](autonomous-operation.md)
