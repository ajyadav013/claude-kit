# Runtime migration guide

This guide covers legacy Claude state migration and transitions among the native `claude`, `codex`,
and `both` projections. Codex and `both` remain **Preview**, so every command that selects either
requires `CKIT_EXPERIMENTAL=1`.

## Before you change a runtime

1. Commit or otherwise back up the project.
2. Run `ckit validate . --strict`, `ckit doctor .`, and `ckit diff .`.
3. Check for an authoritative `.ckit/config/init-options.json` manifest.
4. Stop any active run or record its exact state before changing discovery surfaces.

Do not infer the installed runtime from `CLAUDE.md`, `AGENTS.md`, `.claude`, or `.codex`. Those are
provider outputs; the `.ckit` manifest is the authority after migration.

## Legacy `.claude` state to `.ckit`

Older Claude-only installs kept mutable kit state under `.claude`. Migration copies that state into
the provider-neutral layout, upgrades the manifest, and preserves the legacy bytes:

```bash
CKIT_EXPERIMENTAL=1 ckit migrate-state .
ckit validate . --strict
```

The operation copies the legacy config, continuity, memory, artifacts, state, and temporary trees.
It excludes a transient legacy upgrade journal. Destination conflicts are detected before commit,
the inventory is checked again while the project mutation lease is held, and an interrupted
transaction is recoverable.

If `.ckit` is already authoritative, the command is idempotent. If both roots exist, `.ckit` wins
and `.claude` remains available only for compatibility diagnostics. The compatibility reader is
guaranteed for the first dual-runtime minor release through its next two minor releases; the last of
those must warn before removal can be considered.

You can migrate and select the first native projection in one explicit install:

```bash
ckit init . --runtime claude --migrate-state
# Preview alternatives:
CKIT_EXPERIMENTAL=1 ckit init . --runtime codex --migrate-state
CKIT_EXPERIMENTAL=1 ckit init . --runtime both --migrate-state
```

The installer refuses a legacy-to-native transition without `--migrate-state`; it never silently
chooses which ledger to keep.

## Transition matrix

Once the neutral manifest exists, use `ckit upgrade --runtime ...`. Adding a provider does not need
removal confirmation. Removing one does.

| From | To | Command |
|---|---|---|
| `claude` | `both` | `CKIT_EXPERIMENTAL=1 ckit upgrade . --runtime both` |
| `claude` | `codex` | `CKIT_EXPERIMENTAL=1 ckit upgrade . --runtime codex --confirm-runtime-removal` |
| `codex` | `both` | `CKIT_EXPERIMENTAL=1 ckit upgrade . --runtime both` |
| `codex` | `claude` | `ckit upgrade . --runtime claude --confirm-runtime-removal` |
| `both` | `claude` | `ckit upgrade . --runtime claude --confirm-runtime-removal` |
| `both` | `codex` | `CKIT_EXPERIMENTAL=1 ckit upgrade . --runtime codex --confirm-runtime-removal` |

Removal confirmation covers recoverable backup and removal of only the provider-native surface.
The transaction keeps `.ckit` and the remaining provider projection intact. It reuses the installed
provider-neutral selection; a transition does not silently re-resolve a different stack or profile.

Before removing a provider, the upgrader locks and checks the shared pipeline snapshot. If an active
maker–checker run froze that provider in either role, removal is refused even when the current pair
has since been reconfigured or disabled. Resume the exact run to a terminal result or explicitly
`ckit pipeline abort .`, then retry the transition. An unrelated provider or a valid terminal
snapshot does not create this active-binding block.

## What remains shared

All transition directions retain one:

- `.ckit/config/init-options.json` ownership/checksum manifest;
- `.ckit/config/upgrade-in-progress.json` transactional journal when an operation is active;
- `.ckit/state/pipeline-snapshot.json` and append-only gate history;
- `.ckit/CONTINUITY.md` working-memory file; and
- `.ckit/agent-memory` and `.ckit/artifacts` trees.

Cross-runtime tests update the same ledger from Claude and Codex directions and assert that the
gate-definition digest is unchanged. This tests the kit control plane, not every live-host behavior
listed in the [Preview promotion gates](runtime-support.md#promotion-gates).

## Rollback and conflicts

- Provider surfaces removed during a transition are moved into a numbered project-local backup.
- If a transaction fails, the journal supports recovery instead of leaving a half-transitioned
  tree.
- User-modified managed files are preserved unless you explicitly use `--force`; generated updates
  otherwise arrive as `.claude-kit` sidecars.
- If migration reports incompatible destination bytes or types, do not delete either root. Compare
  the named paths, decide which content is authoritative, and retry after resolving the conflict.

Finish with:

```bash
ckit validate . --strict
ckit doctor .
ckit status .
```

For native layouts and trust/duplication guidance, see [installation](install.md). For capability
differences, see [runtime support](runtime-support.md).
