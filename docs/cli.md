# CLI reference & troubleshooting

The `claude-kit` command (aliases `ckit` · `claude-sdlc`) scaffolds, validates, upgrades, and
exports the kit's configuration. Install: `pip install claude-code-kit` (see
[docs/install.md](install.md)).

## All commands

| Command | Description |
|---------|-------------|
| `init [path] [--defaults] [--config FILE] [--force]` | Scaffold `CLAUDE.md` + `.claude/` (interactive or non-interactive) |
| `validate [path] [--strict]` | Structurally validate an installed config; `--strict` adds hooks→script, `.mcp.json`-shape, snapshot, and catalog-integrity checks |
| `doctor [path] [--mcp]` | Strict validate + environment/health checks; `--mcp` checks MCP commands, `${ENV}` vars, and lockfile drift |
| `diff [path]` | Preview what an `upgrade` would change (no writes) |
| `export [path] -t cursor\|agents\|copilot [--force] [--dry-run] [--json]` | Project the config into Cursor (`.cursor/`), a root `AGENTS.md`, or GitHub Copilot (`.github/copilot-instructions.md`) for editors that aren't Claude Code |
| `upgrade [path] [--force]` | Refresh kit/overlay files; protect your edits; prune orphans |
| `pipeline validate · status · close-gate · skip-gate · abort` | Inspect/mutate the `/sdlc` state files; **does not run** the pipeline. `close-gate` appends to the gate ledger (evidence sha256 + UTC timestamp) and refuses out-of-order or findings-blocked closes; `skip-gate --reason` records a conditional gate that doesn't apply; `validate` re-hashes **every** ledger entry; `--strict` fails closed when the install snapshot is missing (CI) |
| `list-options` | List available frontend/backend/database/profile/MCP options |
| `privacy-report [path] [--json]` | One line per installed hook: what it reads/writes/spawns; flags non-kit hook commands; states whether background learning capture is on and how to disable it |
| `status [path]` | Show what's installed, the selection, and working memory |
| `tickets [ID] [--path DIR] [--graph\|--graph-git] [--html] [--watch N] [--json]` | Live ticket board with tokens / model / agent / elapsed per ticket; `--graph` for the dependency graph, `--graph-git` for the commit graph, `--html` for a browser Kanban board, an `ID` for the detail view |
| `version` | Print the version |
| `package-org-pack` · `install-org-pack` | **Planned** — packaging/distribution of org capability packs. Today these are hidden stubs that describe the intended behavior and exit 2; org packs already install via `init` (organization scope) |

Plugin slash commands: `/claude-kit:init`, `/claude-kit:sdlc <task>`, `/claude-kit:status`, and
`/claude-kit:abort` (cleanly tear down an in-progress `/sdlc` run — removes only that run's
worktrees); plus the `/sdlc` skill inside any scaffolded project.

> When MCP servers are selected, `init` also writes a derived **`.mcp.lock.json`** pinning each
> server's resolved package version — inspect it (or run `doctor --mcp`) to see exactly what would run.

## The ticket chart (`claude-kit tickets`)

Reads the local ticket store (`docs/project/tickets/`, created by the `ticketing-and-traceability`
skill) and joins it with usage figures parsed live from the Claude Code session transcript:

```
CKIT  4 tickets  3 open  2 actionable  1 blocked  1 in progress  1 done

ID      TITLE                              STATUS       AGENT      MODEL     TOKENS  CACHE  TIME  COMMITS
CKIT-2  Ticket board and dependency graph  IN PROGRESS  developer  opus-4-8  34.5k   5.9M   9m    -
CKIT-3  Wire the tickets CLI command       BLOCKED      -          -         -       -      -     -
```

Three things worth knowing:

- **`BLOCKED` is derived, not stored.** A ticket is blocked when something it `depends_on` is still
  open. Sub-tickets (`child_of`) are *not* blocked by an open parent. The header always shows the open
  count next to actionable, so a fully-gated backlog can't be mistaken for an empty one.
- **Telemetry is per branch.** `gitBranch` is the only ticket-shaped key a transcript carries, so
  tickets sharing a branch show that branch's totals — the board footnotes this and the detail view
  names the tickets that share the figure.
- **Only metadata is read** — token counts, model ids, agent names, timestamps, branch. Never message
  content. `--watch N` re-renders every N seconds; figures move as each turn completes.

Without a ticket store the command prints a short hint; without transcripts the board still renders
with `-` in the telemetry columns.

### In the browser (`--html`)

```bash
claude-kit tickets --html          # writes .claude/state/ticket-board.html, prints a file:// URL
```

That produces a Kanban board — **IN PROGRESS · IN REVIEW · ACTIONABLE · BLOCKED · DONE** — with one
card per ticket showing its model, tokens, cache, elapsed time, agent, branch, commits, and any
blocker. Open the printed `file://` URL and leave the tab up.

It is a **file, not a server**. Nothing runs in the background: a `<meta http-equiv="refresh">` tag
makes the browser re-read the file, and the `capture-ticket-telemetry` Stop hook rewrites it as the
session progresses — together that gives live progress with no daemon and no port. The hook only
refreshes the board *if the file already exists*, so generating it once is what opts you in.

The page is fully self-contained: inline CSS, no JavaScript, no fonts, no images, no CDN. Opening it
makes zero network requests, so ticket titles never leave the machine. It follows your OS light/dark
preference. Use `--refresh 0` for a static snapshot you want to keep or share, or `--refresh 30` to
slow the reload down.

## Safe upgrades — how your edits are protected

Every install records per-file checksums and an `owner` (kit / overlay / user-editable) in
`.claude/config/init-options.json`. `upgrade` refreshes kit and overlay files to the latest version,
**never clobbers your edits** (a user-modified file is kept and the new version dropped beside it as a
`.claude-kit` sidecar), backs up anything it changes or removes, and restores files you deleted. Run
`diff` first to preview.

## Troubleshooting

Run **`claude-kit doctor`** first — it checks your environment (git, `jq`, hook scripts) and prints fix
hints.

| Symptom | Likely cause | Fix |
|---|---|---|
| `/sdlc`, agents, or skills "not found" right after `init` | Claude Code hasn't loaded the new project config yet | **Restart Claude Code** — or use `/claude-kit:sdlc <task>` (works without a restart) |
| Guard / quality hooks seem to do nothing | `jq` isn't installed (the hooks parse tool input with it) | Install `jq`; without it the hooks degrade to no-ops by design |
| Hooks do nothing on **Windows** | No POSIX shell — `.sh` hooks can't run under `cmd`/PowerShell | Run claude-kit inside **WSL or Git Bash** (with `jq`); `claude-kit doctor` confirms. Config + CLI work natively regardless |
| A selected MCP server won't start | `node` / `npx` missing (most MCP servers launch via `npx`) | Install Node.js, or remove the server from `.mcp.json` |
| `pip install claude-kit` fails ("no matching distribution") | The PyPI package name is **`claude-code-kit`** — the repo and CLI are `claude-kit`, the pip name is not | `pip install claude-code-kit` |
| `pip install claude-code-kit` fails | Outdated `pip`, or you want an unreleased change | Upgrade pip (`pip install -U pip`); for unreleased changes use `pip install "git+https://github.com/ajyadav013/claude-kit.git"` |
| `validate` reports missing files | Partial or outdated install | Re-run `claude-kit init` (choose **merge**), or `claude-kit upgrade` |
