# Exporting to Cursor / VS Code / GitHub Copilot

claude-kit has a stable native Claude Code scaffold and a native Codex scaffold in Preview. The
`export` command is a separate, lower-fidelity bridge for **Cursor**, generic `AGENTS.md` consumers,
and **GitHub Copilot**. It does not install native Codex skills, custom-agent TOML, hooks, MCP tables,
or shared lifecycle state.

Use `CKIT_EXPERIMENTAL=1 ckit init --runtime codex` for Codex. Do not use `export -t agents` as a
Codex installation or as evidence of Codex parity.

It is a **projection**, not a second source of truth: the exporter re-targets the exact `ResolvedPlan`
that `init` installs (`catalog.resolve()` is untouched, no new stack knowledge). Re-run it any time to
regenerate; it writes **configuration only** — no application code, no Docker.

## Usage

```bash
ckit export .                                   # default target: cursor
ckit export . -t cursor -t agents -t copilot    # all three generic targets
ckit export . --dry-run                         # preview; write nothing
ckit export . --force                           # refresh existing files in place
ckit export . -t agents --json                  # machine-readable file list
```

By default `export` resolves from the project's **installed selection**
(`.ckit/config/init-options.json`, with a legacy `.claude` reader), so the export matches what was
scaffolded. Pass `--config FILE`
or `--defaults` to resolve a fresh selection instead — useful for a standalone export into a project
that never ran `init`.

**Conflict-safe writes.** Exports are regenerable, so `--force` refreshes them in place. Without
`--force`, an existing (possibly hand-edited) file is preserved and the new version is written beside it
as a `<name>.claude-kit` sidecar — the same non-destructive convention the installer uses.

## What each target emits

| Target | Files | Contents |
|---|---|---|
| `cursor` | `.cursor/rules/000-project.mdc` | The project **charter** + single-agent SDLC workflow + fidelity note. `alwaysApply: true` — always in context. |
| | `.cursor/rules/<rule>.mdc` (one per rule) | Every core rule and every stack overlay, `alwaysApply: false` (agent pulls on demand by `description`); overlays also carry `globs` to auto-attach on matching files. |
| | `.cursor/mcp.json` | Your selected MCP servers (omitted when none are selected). |
| `agents` | `AGENTS.md` (repo root) | Generic charter + single-agent workflow + a **rule index** + fidelity note. This is not the native Codex renderer's managed workflow/gate document. |
| `copilot` | `.github/copilot-instructions.md` | The same synthesized document as `agents`. |

## `.mdc` frontmatter derivation

Each Cursor rule file gets YAML frontmatter derived generically from the rule's own content — no
per-stack branching:

- **`description`** — the rule's H1 heading plus its first lead sentence (falling back to a humanized
  filename), trimmed to ~200 characters. Cursor uses this to decide when to pull an on-demand rule.
- **`alwaysApply`** — `false` for the whole rule set (mirroring Claude Code's on-demand rule loading);
  `true` only for the synthesized `000-project.mdc` charter.
- **`globs`** — attached to **overlay** rules only. The overlay rule's own `paths:` frontmatter
  (Claude Code's [scoped rule loading](https://code.claude.com/docs/en/memory)) is the source of
  truth: its glob list projects verbatim, comma-joined, and the block is stripped from the `.mdc`
  body so the export carries exactly one frontmatter fence. An overlay *without* a `paths:` block
  (e.g. a user-added rule) falls back to the lane's *language/database* values (not framework
  names):

  | Lane | Source value | Example glob |
  |---|---|---|
  | frontend | `frontend_language` | `typescript` → `**/*.ts,**/*.tsx` |
  | backend | `backend_language` | `python` → `**/*.py`, `go` → `**/*.go` |
  | database | `database` | `postgres` → `**/*.sql` |

  A store with no reliable file signal (e.g. a document database) gets **no** glob and loads by
  `description` instead. Core rules never get globs.

Values are JSON-quoted so the frontmatter is always valid YAML — an unquoted glob such as
`**/*.{ts,tsx}` would be misparsed as a YAML flow mapping.

## MCP projection

Cursor's `.cursor/mcp.json` uses a top-level `mcpServers` map and infers transport from the keys
present — stdio servers use `command`/`args`/`env`, remote servers use `url`/`headers`. claude-kit's
internal `type` discriminator is **dropped**; every other key passes through verbatim.

## Fidelity: what ports, and what doesn't

| Capability | Native scaffold | Generic export (Cursor / AGENTS.md / Copilot) |
|---|---|---|
| Engineering rules + stack/design-system overlays | Claude native files; Codex adapted managed instructions + complete `.ckit/rules` | Full text (`.mdc`) or an advisory index (`AGENTS.md`) |
| Project charter (stack, commands, lanes) | ✅ | ✅ |
| MCP servers | `.mcp.json` (Claude) or `.codex/config.toml` (Codex) | Cursor `.cursor/mcp.json`; not applicable to AGENTS.md/Copilot |
| SDLC phases and gate ledger | Shared `.ckit` lifecycle with native instructions | Single-agent **self-check checklist** only |
| Independent reviewer agents | Native/adapted named project agents, subject to the runtime support matrix | One editor agent plays every role |
| Hooks and automatic defect loop | Host-specific mappings plus Python gate enforcement | Not exported; prose guidance does not block |
| Continuity, upgrades, and state | One ownership-aware `.ckit` control plane | Not exported |

The generic targets cannot reproduce a host-native multi-agent workflow. Their charter states that
the workflow is a self-check checklist rather than an enforced gate pipeline. Native Codex support
is documented separately in [runtime support](runtime-support.md).

## Out of scope (for now)

- **Cursor hooks** (`.cursor/hooks.json`) and **commands/skills** export — a different event/format
  model; noted as future work.
- **Drift tracking** of exported files in the `init-options.json` ownership manifest — exports are
  regenerable projections (`export --force` refreshes), so they are intentionally not tracked.
