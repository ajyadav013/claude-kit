# ADR-001: Compile provider-neutral plans into runtime projections

## Status

Accepted; implementation is incremental. The current stable release remains Claude Code-first until
the promotion gates in [runtime support](../runtime-support.md) pass.

## Date

2026-08-20

## Context

The catalog resolver currently answers a provider-neutral question: which rules, agents, skills,
hooks, gates, overlays, and MCP servers belong to a selected SDLC configuration. Host deployment is
a different question. Claude Code and Codex discover instructions, skills, agents, hooks, and MCP
configuration through different paths and formats, and neither host's directory is an appropriate
owner for shared kit state.

Putting the host on `Selection` would mix deployment metadata into the domain model and invite
provider branches in `catalog.resolve()`. Copying the payload into parallel Claude and Codex source
trees would create two sources of truth. Storing state under both `.claude/` and `.codex/` would make
`both` installs ambiguous and allow the two hosts to advance different gate ledgers.

## Decision

### Keep runtime outside selection and resolution

`Selection` and `ResolvedPlan` remain provider-neutral. A deployment request carries them across a
separate seam:

```text
InstallRequest(selection, runtime)
        |
        +-- catalog.resolve(selection) -> ResolvedPlan
        |
        +-- ProjectionCompiler.compile(plan, runtime)
                -> ClaudeProjection, CodexProjection, or both
                -> runtime renderer(s)
                -> ownership-aware installation
```

`runtime` is deployment metadata with exactly three values: `claude`, `codex`, and `both`. The
resolver must not branch on it. `both` compiles the same `ResolvedPlan` through both renderers and
then reconciles shared outputs; it is not a third content model.

The projection compiler owns semantic translation. Examples include converting canonical agent
personas to Codex TOML, converting manual-only skill metadata, routing scoped rules through the
host's instruction mechanism, and mapping hooks without assuming identical event behavior. A
renderer owns syntax and paths only. Unsupported semantics must be reported as degraded or
unsupported instead of being silently copied.

### Use one host-neutral state root

Every fresh scaffolded install writes kit-owned mutable state under `.ckit/`, regardless of runtime.
This includes the install request, ownership/checksum manifest, resolved-plan snapshot, upgrade
journal, continuity data, and pipeline state. Host-native discovery files remain under their host
locations, but they refer to the same `.ckit` state when they need continuity or gate data.

Consequently, a `both` install has one manifest, one upgrade journal, and one append-only gate
ledger. Runtime must be read from `.ckit` metadata, never inferred from the presence of `.claude/`,
`.codex/`, `CLAUDE.md`, or `AGENTS.md`.

### Treat rendered host files as generated outputs

The catalog, canonical payload, templates, and projection code are sources. Host-native files are
derived outputs. The installer records the renderer, ownership class, and checksum for each derived
file in `.ckit`.

Generated-output handling follows four rules:

1. Regenerate from the canonical source; do not promote a rendered Claude or Codex file into a
   second source of truth.
2. Preserve text outside marked managed sections in shared files such as `AGENTS.md`.
3. Semantically merge structured host configuration and retain unknown user keys. Do not replace a
   whole TOML or JSON file to update kit-owned entries.
4. When a kit-owned file has user edits, preserve it and write the proposed generated version as a
   sidecar or report a conflict through the existing safe-upgrade mechanism.

Generated files must carry a generated/managed marker where the host format permits one. CI golden
tests compare compiler output to committed expectations; hand-editing a golden-derived output does
not change the product source.

### Read legacy Claude state during a bounded migration window

Legacy installs may store their manifest and mutable state under `.claude/`. If `.ckit` is absent,
the compatibility reader treats a legacy manifest with no runtime as `runtime: claude` and keeps
that legacy control plane active. Migration occurs only through the explicit transactional
`ckit migrate-state` command or an install using `--migrate-state`; ordinary state-changing
operations never create a competing ledger implicitly. The migration copies equivalent state to
`.ckit`, leaves the legacy files intact, and is non-destructive and resumable. If both roots exist,
`.ckit` is authoritative and legacy state is read only for diagnostics.

The compatibility reader is required from the first dual-runtime minor release, `N`, through `N+2`
inclusive. `N+2` must emit a deprecation notice before removal can be considered. Removing the
legacy reader before `N+3`, or removing it in any release without a replacement ADR and explicit
migration command, is prohibited. Claude host payload may continue to live under `.claude/`; this
window concerns kit-owned mutable state, not Claude's native discovery directory.

### Separate plugin and scaffold guarantees

The pip scaffolder is the first-class deployment path. It can resolve the catalog, compile a runtime
projection, merge project configuration, record ownership, migrate state, and install custom agent
or instruction surfaces.

A host plugin is a static distribution path. It may expose only components the host discovers from
an installed plugin, such as skills, hooks, and MCP declarations. Plugin installation does not run
the project projection compiler, does not choose a stack/profile/scope, does not create or migrate
`.ckit`, and does not install project `AGENTS.md`, `CLAUDE.md`, or project-scoped custom agents.
Plugin documentation must therefore list its supported component subset and must not claim scaffold
parity.

The repository root remains the Claude Code plugin root. The Codex repository marketplace points to
`providers/codex/claude-kit`, whose own `.codex-plugin/plugin.json`, `skills/`, and `hooks/` form the
Codex package root. This nested package is a deliberate deviation from the requested single shared
plugin root: Codex validation forbids Claude-only skill invocation metadata and treats every direct
`skills/*` directory as a skill. It is acceptable because every nested file is generated from the
same canonical skill records, hook registry/scripts, and plugin metadata, with drift and native-host
discovery tests; it is not an independently maintained payload tree.

## Alternatives considered

### Add runtime to `Selection`

Rejected because host choice does not change the semantic SDLC plan. It would contaminate catalog
resolution and multiply the profile-by-stack matrix with deployment-only state.

### Store state under the selected host directory

Rejected because `both` would need an arbitrary primary host or duplicate state. Host-neutral
`.ckit` gives upgrades and pipeline operations one authority.

### Maintain separate Claude and Codex payload trees

Rejected because fixes would drift and reviewers could not tell which copy was canonical. Runtime
differences belong in compiler rules and renderer tests.

### Copy the Claude tree and rely on Codex compatibility import

Rejected as a first-class architecture. Compatibility import is useful for migration, but it does
not prove native instruction routing, custom-agent configuration, hook semantics, or safe project
configuration merges.

## Consequences

- Existing catalog resolution and selection tests remain provider-neutral.
- Projection and renderer tests become the compatibility boundary for each host.
- Fresh installs gain a visible `.ckit` directory even for Claude-only projects.
- Dual-runtime installations cannot diverge at the mutable state layer.
- Some Claude concepts have no exact Codex analogue and must remain visibly adapted, degraded, or
  unsupported.
- Plugin support is intentionally narrower than scaffold support.
- The legacy reader adds temporary maintenance work, bounded by the stated release window.
