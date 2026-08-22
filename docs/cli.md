# CLI reference & troubleshooting

The `ckit` command (legacy aliases `claude-kit` · `claude-sdlc`) scaffolds, validates, upgrades, and
exports the kit's configuration. Install: `pip install claude-code-kit` (see
[docs/install.md](install.md)).

Claude Code is stable. Commands that select `codex` or `both`, and the standalone `migrate-state`
command, are Preview and require `CKIT_EXPERIMENTAL=1`. The legacy
`CLAUDE_KIT_EXPERIMENTAL=1` alias remains accepted during the compatibility window.

## All commands

| Command | Description |
|---------|-------------|
| `init [path] [--defaults] [--config FILE] [--runtime claude\|codex\|both] [--migrate-state] [--force]` | Resolve one provider-neutral plan and scaffold the selected native runtime. Omit `--runtime` only for the legacy Claude installer; Codex/`both` require the experimental switch |
| `validate [path] [--strict]` | Structurally validate an installed config; `--strict` fail-closes on hooks→script, JSON Schema, `.mcp.json`, persisted-artifact, snapshot, and catalog-integrity errors (schema support is a normal dependency and is never silently skipped) |
| `doctor [path] [--mcp]` | Strict validate + environment/health checks; `--mcp` checks MCP commands, `${ENV}` vars, and lockfile drift |
| `diff [path]` | Preview what an `upgrade` would change (no writes) |
| `export [path] -t cursor\|agents\|copilot [--force] [--dry-run] [--json]` | Project the config into Cursor (`.cursor/`), a root `AGENTS.md`, or GitHub Copilot (`.github/copilot-instructions.md`) for editors that aren't Claude Code |
| `upgrade [path] [--runtime claude\|codex\|both] [--confirm-runtime-removal] [--force]` | Refresh managed files or transition an existing neutral install. Removing a provider surface requires explicit confirmation and creates a recoverable backup |
| `migrate-state [path]` | **Preview/hidden:** transactionally copy legacy mutable `.claude` state into authoritative `.ckit` while preserving legacy bytes |
| `pipeline run --provider claude\|codex [--condition NAME=true\|false]… [--program-manifest FILE]` | **Preview/hidden:** execute or resume one active frozen workflow through a concrete installed host. Modes A–D freeze the structured stage graph; Mode E additionally requires an explicit project-contained program manifest and freezes its waves, units, budgets, evidence, and checkpoints in the same ledger |
| `pipeline start · adopt · resume · reconcile-stale-attempt · reconcile-stale-program-attempt · pause · resolve-pause · record-findings · close-gate · not-applicable · accept-risk · complete · abort · validate · status` | Inspect/mutate schema-versioned `/sdlc` state. Lifecycle is explicit, required gates cannot be skipped, Critical/High always block, Medium uses a distinct structured risk acceptance, and findings/evidence are SHA-256 bound to the current gate/commit. `skip-gate` is retained only as a compatibility alias for structured `not-applicable` |
| `worktree create · list · mark · cleanup · abort-run · resume-run` | Manage provider-neutral, run-owned fallback worktrees. Dirty/failed artifacts require explicit discard; exact ownership is revalidated on resume/cleanup |
| `list-options` | List available frontend/backend/database/profile/MCP options |
| `privacy-report [path] [--json]` | One line per installed hook: what it reads/writes/spawns; flags non-kit hook commands; states whether background learning capture is on and how to disable it |
| `status [path]` | Show what's installed, the selection, and working memory |
| `tickets [ID] [--path DIR] [--graph\|--graph-git] [--html] [--watch N] [--json]` | Live ticket board with tokens / model / agent / elapsed per ticket; `--graph` for the dependency graph, `--graph-git` for the commit graph, `--html` for a browser Kanban board, an `ID` for the detail view |
| `version` | Print the version |
| `package-org-pack` · `install-org-pack` | **Planned** — packaging/distribution of org capability packs. Today these are hidden stubs that describe the intended behavior and exit 2; org packs already install via `init` (organization scope) |

Claude plugin slash commands: `/claude-kit:init`, `/claude-kit:sdlc <task>`, `/claude-kit:status`, and
`/claude-kit:abort` (cleanly tear down an in-progress `/sdlc` run — removes only that run's
worktrees); plus the `/sdlc` skill inside any scaffolded project.

**These four are plugin-only, by design.** `ckit init` installs agents, skills, rules, hooks,
templates and config, but no `.claude/commands/`, so a pip-only Claude project has none of the
`/claude-kit:*` commands. No capability is lost — the `sdlc` skill *is* installed, so `/sdlc` reaches
the same pipeline, and `ckit status` / `ckit pipeline abort` cover the rest — but the two
distribution paths do not present the same surface, and it is worth knowing which one you are on
before looking for a command that was never installed.

Codex has no exact project slash-command analogue. Its native projection adapts the four wrappers
as explicit skills, including `$sdlc`; plugin and scaffold capabilities remain distinct. See
[installation](install.md#plugin-installation-is-narrower-than-scaffolding).

## Pipeline state lifecycle

The CLI will not create a ledger implicitly from `close-gate`. Start a fresh run at the installed
profile's first active gate, or explicitly adopt work already in flight:

```bash
ckit pipeline start . --task "Add health endpoint" --mode B
ckit pipeline adopt code-review . \
  --task "Adopt emergency fix" \
  --reason "spec and EM review happened before the v2 ledger" \
  --adopted-by "release manager"
ckit pipeline resume .
```

If the coordinator is killed after durably claiming a stage, ordinary resume refuses to guess
whether its detached worker is still active. The only bounded recovery is an explicit operator
reconciliation for an exact **Claude, read-only, no-shell, no-delegation** claim whose worktree and
provider controls are unchanged:

```bash
ckit pipeline reconcile-stale-attempt classify . \
  --dispatch-id <exact-ledger-id> \
  --reconciled-by "release owner" \
  --evidence artifacts/operator-crash-observation.json
```

The command acquires the coordinator lease, copies and hashes the project-contained evidence, marks
that exact attempt cancelled, and permits a retry. It deliberately refuses Codex-origin, shell,
write, external-effect, delegation, changed-workspace, or still-live coordinator claims; abort and
investigate those manually.

With `CKIT_EXPERIMENTAL=1`, the structured runner is the Preview adapter-backed path for an active
run. It derives the task and mode from the ledger; select exactly one installed host per
invocation and state every task-dependent stage condition explicitly on the first invocation:

```bash
CKIT_EXPERIMENTAL=1 ckit pipeline run . --provider codex \
  --condition ui-surface-present=true \
  --condition frontend-surface-present=true \
  --condition backend-surface-present=false \
  --condition api-contract-surface-present=false \
  --condition api-surface-present=false \
  --condition risk-or-uncertainty-present=true \
  --condition multiple-boundaries-present=false \
  --condition end-to-end-path-present=true \
  --condition application-attack-surface-present=true \
  --condition deploy-surface-present=false \
  --condition observable-surface-present=true
```

Mode E instead requires a frozen, project-contained manifest on the managed entry point:

```bash
CKIT_EXPERIMENTAL=1 ckit pipeline run . --provider claude \
  --program-manifest docs/specs/migration-program.json
```

The coordinator binds that manifest to the run, source commit, workflow/gate/selection digests,
ordered waves and units, budgets, typed evidence, program gates, attempts, and workspace
checkpoints. The bundled adapters can progress only pure read/search audit units: any shell or
write unit requires a separate dispatcher that attests exact physical no-follow boundary
containment. Irreversible units always stop because no consume-once external approval broker is
integrated. Failed workspaces remain preserved and are never merged automatically.

Those decisions are frozen in `.ckit`; later invocations may omit them, including when resuming the
same run with `--provider claude`. The runner stops at each unresolved gate so the controlling
session can inspect the run-owned evidence, record exact findings, and use the lifecycle transitions
below. Run it again after the gate resolves. Status `waiting-gate` exits 0, `human-stop` exits 3, and
an execution failure exits 1; `--json` emits bounded metadata and artifact references, not raw host
transcripts. A persisted unresolved stop also returns the same structured `human-stop` document and
exit 3 on every resume attempt, including its `stop_id`. Managed `--decision approved` is currently
unsupported because a local evidence file is not a trustworthy stage/attempt/workspace-scoped,
one-shot authorization; the stop stays pending. `--decision rejected` records only a replan/abort
signal and never authorizes the stopped action. The legacy/manual lifecycle retains its approval
record compatibility.

Managed closeout first runs the credential-free `pull-request-prepare` stage. The final
`pull-request` / `fast-pull-request` leaf is a typed `repository.pull-request.create` action with
the exact requirement `external.mutation`; it is never routed to a native worker or fallback.
Until the documented external signer and broker boundary is configured, that leaf returns a
blocking external-side-effect stop.

Each attempt's public `artifact` object contains only its project-relative path, SHA-256, category,
and truncation flag. The raw bounded host capture remains mode-0600 under `.ckit/artifacts/`.

Every selected shell-capable Claude route requires the semantic capability
`process.descendant_containment`. The built-in Codex adapter may waive that requirement only for a
passive read-only, nondelegating role on an exact compatibility-pinned CLI after a local probe
confirms all command, extension, and delegation features are disabled. The coordinator supplies a
bounded, sensitive-path-filtered tracked-text projection; the host receives no local file or shell
tool. Every other Codex invocation requires containment. The built-in subprocess backend
deliberately does not attest it: portable process-group cleanup cannot contain a deliberately
re-sessioned descendant. The runner therefore emits an `unsupported-required-capability` human
stop before spawning those invocations. This is a non-
bypassable Preview boundary, not a retryable or resolvable stage failure.

Managed execution uses one persistent run-owned integration worktree so later stages see earlier
changes. Because that worktree is created from `HEAD`, the selected provider's scaffolded files and
all application inputs must be committed first; only mutable `.ckit/` state is exempt. It refuses
missing or dirty provider/application context, preserves the worktree at checkpoints/failure, and
does not merge it into the main checkout automatically. Inspect and merge it through an explicit
human-controlled handoff. Mode E uses the same shared ledger but remains Degraded Preview: its
typed runtime is executable only as far as the selected adapter's attested capabilities. The
bundled adapters stop before shell/write gate and implementation units, and every irreversible unit
stops at the absent external approval broker. Do not translate either stop into a successful wave
or ordinary Mode A–D claim.

For a manual, unmanaged run, bind all five exact open-finding counts to a project-contained report
before every gate transition. Repeat this after the commit, report, or finding set changes;
`start`/`adopt` deliberately leaves the finding set unrecorded rather than assuming zero:

```bash
ckit pipeline record-findings . \
  --critical 0 --high 0 --medium 0 --low 1 --cosmetic 0 \
  --evidence artifacts/current-findings.json
```

An ordinary manual pass then requires its own gate evidence file. A conditional gate can be resolved
only with one of the condition identifiers embedded in the installed gate definition and evidence
proving it:

```bash
ckit pipeline close-gate build-green . --evidence artifacts/build.txt
ckit pipeline not-applicable contract-clear . \
  --condition no-api-contract-surface \
  --reason "documentation-only change" \
  --evidence artifacts/changed-files.txt
```

Managed Modes A–D use a stronger path. A successful owner stage must return the exact frozen typed
evidence set; the coordinator validates required fields and kind-specific pass/finding semantics,
then stores normalized 0600 content-addressed records under `.ckit/artifacts`. For those runs,
`record-findings` rejects counts that differ from the owner records and `close-gate` derives its
authoritative bundle from those records. The CLI `--evidence` file remains required for compatibility
and conditional context, but cannot replace or contradict the managed owner evidence.

Critical and High findings have no waiver transition. A Medium finding cannot be recorded as
`passed`; it requires a human-attested record with every accountability field:

```bash
ckit pipeline accept-risk security-clear . \
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

## The ticket chart (`ckit tickets`)

Reads the local ticket store (`docs/project/tickets/`, created by the `ticketing-and-traceability`
skill). In Claude Code it can join that store with usage figures parsed from session transcript
metadata:

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
with `-` in the telemetry columns. That is the current Codex behavior: the shared board works, but
automatic Codex host telemetry is unsupported and the projected hook is an explicit no-op.

### In the browser (`--html`)

```bash
ckit tickets --html                # writes .ckit/state/ticket-board.html, prints a file:// URL
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

Every native install records per-file checksums, provider/component identity, and an `owner` (kit /
overlay / user-editable) in `.ckit/config/init-options.json`. `upgrade` refreshes managed files,
**never clobbers your edits** (a user-modified file is kept and the new version dropped beside it as a
`.claude-kit` sidecar), backs up anything it changes or removes, and restores files you deleted. Run
`diff` first to preview.

An explicit `--runtime` on `upgrade` transitions native surfaces while retaining that shared state.
If the destination removes Claude or Codex files, add `--confirm-runtime-removal`; the removed
surface is first moved into a numbered project-local backup. See the
[runtime migration guide](runtime-migration.md).

## Troubleshooting

Run **`ckit doctor`** first — it reports installed runtimes and shared state, host CLI compatibility,
strict validation, hook requirements, Codex trust, and detectable project-local plugin/scaffold
duplication.

| Symptom | Likely cause | Fix |
|---|---|---|
| `/sdlc`, agents, or skills "not found" right after `init` | Claude Code hasn't loaded the new project config yet | **Restart Claude Code** — or use `/claude-kit:sdlc <task>` (works without a restart) |
| `$sdlc` or a Codex agent is missing | Codex Preview was not selected, the project was not reopened, or the wrong skill syntax was used | Run `CKIT_EXPERIMENTAL=1 ckit init . --runtime codex` (or `both`), reopen the project, and use `$sdlc` rather than a Claude slash command |
| Codex project hooks do nothing | The project is not trusted, the event is unsupported, or `jq`/a POSIX shell is absent | Trust the project after reviewing `.codex/hooks.json`; run `ckit doctor`; `PermissionRequest` and `PostCompact` are intentionally not projected |
| `init --runtime codex` or `both` exits 2 | Preview features are not enabled | Set `CKIT_EXPERIMENTAL=1`; the legacy `CLAUDE_KIT_EXPERIMENTAL=1` alias is accepted temporarily |
| Native install refuses because legacy state exists | Mutable state still lives under `.claude` | Retry with `--migrate-state`, or run `CKIT_EXPERIMENTAL=1 ckit migrate-state .` first; do not manually copy the ledger |
| A runtime transition refuses to remove files | Provider surface removal was not explicitly confirmed | Review `ckit diff`, then rerun `ckit upgrade --runtime … --confirm-runtime-removal`; the surface is backed up recoverably |
| The same skill appears twice | A project scaffold and a plugin both expose it | `ckit doctor` reports detectable project-local duplication. Choose one invocation source; user-level host registries remain outside its inspection scope |
| Guard / quality hooks seem to do nothing | `jq` isn't installed (the hooks parse tool input with it) | Install `jq`; without it the hooks degrade to no-ops by design |
| A mutating command is refused on **native Windows** | Secure project writes require descriptor-anchored paths and a handle-tied lease; the old pathname fallback had a junction race | Run `ckit` in **WSL on a POSIX-semantics filesystem**. Read-only inspection and plugin discovery remain available; a native handle-backed writer is Phase 2 |
| Hooks do nothing on **Windows** | No POSIX shell — `.sh` hooks can't run under `cmd`/PowerShell | Run inside **WSL** with `jq`; `ckit doctor` confirms. Hook portability is separate from filesystem mutation safety |
| A selected MCP server won't start | Its command/environment is missing | Run `ckit doctor --mcp`; inspect `.mcp.json` for Claude or the managed `[mcp_servers.*]` tables in `.codex/config.toml` for Codex |
| `pip install claude-kit` fails ("no matching distribution") | The PyPI package name is **`claude-code-kit`** — the repo and CLI are `claude-kit`, the pip name is not | `pip install claude-code-kit` |
| `pip install claude-code-kit` fails | Outdated `pip`, or you want an unreleased change | Upgrade pip (`pip install -U pip`); for unreleased changes use `pip install "git+https://github.com/ajyadav013/claude-kit.git"` |
| `validate` reports missing files | Partial or outdated install | Re-run `ckit init` in merge mode, or `ckit upgrade` |
