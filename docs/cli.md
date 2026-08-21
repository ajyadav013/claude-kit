# CLI reference & troubleshooting

The `claude-kit` command (aliases `ckit` · `claude-sdlc`) scaffolds, validates, upgrades, and
exports the kit's configuration. Install: `pip install claude-code-kit` (see
[docs/install.md](install.md)).

## All commands

| Command | Description |
|---------|-------------|
| `init [path] [--defaults] [--config FILE] [--force]` | Scaffold `CLAUDE.md` + `.claude/` (interactive or non-interactive) |
| `validate [path] [--strict]` | Structurally validate an installed config; `--strict` fail-closes on hooks→script, JSON Schema, `.mcp.json`, persisted-artifact, snapshot, and catalog-integrity errors (schema support is a normal dependency and is never silently skipped) |
| `doctor [path] [--mcp]` | Strict validate + environment/health checks; `--mcp` checks MCP commands, `${ENV}` vars, and lockfile drift |
| `diff [path]` | Preview what an `upgrade` would change (no writes) |
| `export [path] -t cursor\|agents\|copilot [--force] [--dry-run] [--json]` | Project the config into Cursor (`.cursor/`), a root `AGENTS.md`, or GitHub Copilot (`.github/copilot-instructions.md`) for editors that aren't Claude Code |
| `upgrade [path] [--force]` | Refresh kit/overlay files; protect your edits; prune orphans |
| `pipeline start · adopt · resume · record-findings · close-gate · not-applicable · accept-risk · complete · abort · validate · status` | Inspect/mutate schema-versioned `/sdlc` state; **does not run** the pipeline. Lifecycle is explicit, required gates cannot be skipped, Critical/High always block, Medium uses a distinct structured risk acceptance, and findings/evidence are SHA-256 bound to the current gate/commit. `skip-gate` is retained only as a compatibility alias for structured `not-applicable` |
| `list-options` | List available frontend/backend/database/profile/MCP options |
| `privacy-report [path] [--json]` | One line per installed hook: what it reads/writes/spawns; flags non-kit hook commands; states whether background learning capture is on and how to disable it |
| `status [path]` | Show what's installed, the selection, and working memory |
| `tickets [ID] [--path DIR] [--graph\|--graph-git] [--html] [--watch N] [--json]` | Live ticket board with tokens / model / agent / elapsed per ticket; `--graph` for the dependency graph, `--graph-git` for the commit graph, `--html` for a browser Kanban board, an `ID` for the detail view |
| `version` | Print the version |
| `package-org-pack` · `install-org-pack` | **Planned** — packaging/distribution of org capability packs. Today these are hidden stubs that describe the intended behavior and exit 2; org packs already install via `init` (organization scope) |

Plugin slash commands: `/claude-kit:init`, `/claude-kit:sdlc <task>`, `/claude-kit:status`, and
`/claude-kit:abort` (cleanly tear down an in-progress `/sdlc` run — removes only that run's
worktrees); plus the `/sdlc` skill inside any scaffolded project.

**These four are plugin-only, by design.** `claude-kit init` installs agents, skills, rules, hooks,
templates and config, but no `.claude/commands/`, so a pip-only project has none of the
`/claude-kit:*` commands. No capability is lost — the `sdlc` skill *is* installed, so `/sdlc` reaches
the same pipeline, and `claude-kit status` / `claude-kit pipeline abort` cover the rest — but the two
distribution paths do not present the same surface, and it is worth knowing which one you are on
before looking for a command that was never installed.

## Pipeline state lifecycle

The CLI will not create a ledger implicitly from `close-gate`. Start a fresh run at the installed
profile's first active gate, or explicitly adopt work already in flight:

```bash
claude-kit pipeline start . --task "Add health endpoint" --mode B
claude-kit pipeline adopt code-review . \
  --task "Adopt emergency fix" \
  --reason "spec and EM review happened before the v2 ledger" \
  --adopted-by "release manager"
claude-kit pipeline resume .
```

Before every gate transition, bind all five exact open-finding counts to a project-contained report.
Repeat this after the commit, report, or finding set changes; `start`/`adopt` deliberately leaves the
finding set unrecorded rather than assuming zero:

```bash
claude-kit pipeline record-findings . \
  --critical 0 --high 0 --medium 0 --low 1 --cosmetic 0 \
  --evidence artifacts/current-findings.json
```

An ordinary pass then requires its own gate evidence file. A conditional gate can be resolved only
with one of the condition identifiers embedded in the installed gate definition and evidence proving
it:

```bash
claude-kit pipeline close-gate build-green . --evidence artifacts/build.txt
claude-kit pipeline not-applicable contract-clear . \
  --condition no-api-contract-surface \
  --reason "documentation-only change" \
  --evidence artifacts/changed-files.txt
```

Critical and High findings have no waiver transition. A Medium finding cannot be recorded as
`passed`; it requires a human-attested record with every accountability field:

```bash
claude-kit pipeline accept-risk security-clear . \
  --finding-id SEC-17 \
  --reason "upstream fix is not yet released" \
  --accepted-by "security lead" \
  --owner "platform team" \
  --ticket GH-123 \
  --revisit "2026-09-01 or dependency release" \
  --compensating-control "feature remains disabled by default" \
  --evidence artifacts/security-review.json
```

The acceptance is bound to the current commit, gate-definition digest, finding identity/count, and
evidence hash. If one changes, validation marks it stale. `accept-risk --refresh` is an explicit new
attestation and preserves the superseded record; it is not an automatic carry-forward. Finish with
`pipeline complete` only after every gate is resolved, or `pipeline abort`; both terminal states
refuse later transitions. `pipeline status --json` and `pipeline validate --json` expose the complete
records for automation and never translate `accepted-risk` into PASS.

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
| A mutating command is refused on **native Windows** | Secure project writes require descriptor-anchored paths and a handle-tied lease; the old pathname fallback had a junction race | Run claude-kit in **WSL on a POSIX-semantics filesystem**. Read-only inspection and plugin discovery remain available; a native handle-backed writer is Phase 2 |
| Hooks do nothing on **Windows** | No POSIX shell — `.sh` hooks can't run under `cmd`/PowerShell | Run inside **WSL** with `jq`; `claude-kit doctor` confirms. Hook portability is separate from filesystem mutation safety |
| A selected MCP server won't start | `node` / `npx` missing (most MCP servers launch via `npx`) | Install Node.js, or remove the server from `.mcp.json` |
| `pip install claude-kit` fails ("no matching distribution") | The PyPI package name is **`claude-code-kit`** — the repo and CLI are `claude-kit`, the pip name is not | `pip install claude-code-kit` |
| `pip install claude-code-kit` fails | Outdated `pip`, or you want an unreleased change | Upgrade pip (`pip install -U pip`); for unreleased changes use `pip install "git+https://github.com/ajyadav013/claude-kit.git"` |
| `validate` reports missing files | Partial or outdated install | Re-run `claude-kit init` (choose **merge**), or `claude-kit upgrade` |
