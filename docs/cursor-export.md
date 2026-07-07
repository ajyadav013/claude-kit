# Exporting to Cursor / VS Code / GitHub Copilot

claude-kit's home is **Claude Code**, where it installs a `.claude/` configuration and runs a gated,
multi-agent `/sdlc` pipeline. A teammate working in **Cursor**, **VS Code**, or **GitHub Copilot**
uses that editor's *own* single agent — which can't read `.claude/` or run the pipeline. `claude-kit
export` bridges the gap by projecting the **same resolved plan** into the formats those agents read
natively.

It is a **projection**, not a second source of truth: the exporter re-targets the exact `ResolvedPlan`
that `init` installs (`catalog.resolve()` is untouched, no new stack knowledge). Re-run it any time to
regenerate; it writes **configuration only** — no application code, no Docker.

## Usage

```bash
claude-kit export .                                   # default target: cursor
claude-kit export . -t cursor -t agents -t copilot    # all three
claude-kit export . --dry-run                         # preview; write nothing
claude-kit export . --force                            # refresh existing files in place
claude-kit export . -t agents --json                  # machine-readable file list
```

By default `export` resolves from the project's **installed selection**
(`.claude/config/init-options.json`), so the export matches what was scaffolded. Pass `--config FILE`
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
| `agents` | `AGENTS.md` (repo root) | Charter + workflow + a **rule index** (one line per rule) + the fidelity note. Read by both Cursor and Copilot. `claude-kit init` already emits this file (sidecar-safe); the target regenerates it — a byte-identical existing file is reported as current, never sidecar'd. |
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

| Capability | Claude Code | Exported (Cursor / AGENTS.md / Copilot) |
|---|---|---|
| Engineering rules + stack/design-system overlays | ✅ enforced/on-demand | ✅ full text (`.mdc`) or index (AGENTS.md) |
| Project charter (stack, commands, lanes) | ✅ | ✅ |
| MCP servers | ✅ (`.mcp.json`) | ✅ Cursor (`.cursor/mcp.json`); not applicable to AGENTS.md/Copilot |
| SDLC phases | ✅ **enforced quality gates** | ⚠️ single-agent **self-check checklist** (guidance) |
| Independent reviewer subagents | ✅ separate agents | ❌ one agent plays every role |
| Security scan (parallel sub-scanners) | ✅ | ⚠️ a security self-check step in the checklist |
| Automated defect loop (blocks on unproven verdict) | ✅ | ⚠️ described as discipline; nothing blocks |

The enforced gates, reviewer subagents, and automated defect loop depend on Claude Code's multi-agent
runtime and **cannot** be reproduced under a single-agent editor. The export is honest about this: the
charter carries a "What ports from Claude Code — and what doesn't" note, and the workflow guide opens
by stating it is a self-check checklist, not enforced gates.

## Out of scope (for now)

- **Cursor hooks** (`.cursor/hooks.json`) and **commands/skills** export — a different event/format
  model; noted as future work.
- **Drift tracking** of exported files in the `init-options.json` ownership manifest — exports are
  regenerable projections (`export --force` refreshes), so they are intentionally not tracked.
