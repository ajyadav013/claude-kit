# Known limitations

claude-kit is deliberately a **configuration scaffolder** — not a runtime, sandbox, or security
product. Claude Code support is stable; Codex and `both` are Preview. Being honest about the edges is
part of the design. If one of these is a blocker for you, that's useful signal — open an issue.

## Guard hooks are guardrails, not a security boundary

- The event hooks (block `rm -rf`, secret-file reads, pushes to `main`, destructive git, `kubectl
  delete`, …) require **`jq` and a POSIX shell**. Without them they **degrade to no-ops** — agents,
  rules, and skills still work, but the guards do nothing. Run `ckit doctor` to
  check.
- The git guards normalize the command (stripping `git -c …` / `git -C …` global options and matching
  force-push refspecs like `+main`) so they aren't trivially evaded — but they are **best-effort
  regex/tokenizers, not a sandbox**. A determined operator who deliberately crafts an obfuscated
  command (env-var indirection, `python -c`, `find -delete`) can still get past them. They exist to
  stop *accidental* agent mistakes, not a motivated adversary who already controls the machine.

## Plugins are not project scaffolds

- The static plugins expose only components their host can discover. They cannot select a
  stack/profile/scope, create or migrate `.ckit`, perform safe upgrades, or install project
  `CLAUDE.md`, `AGENTS.md`, rules, and custom-agent surfaces.
- The Claude plugin's `/claude-kit:sdlc` works immediately. Project `/sdlc`, selected agents/rules,
  and project hooks appear only after `ckit init --runtime claude` plus a restart.
- The Codex plugin is Preview and does not install `.codex/agents/*.toml` or the project-managed
  `AGENTS.md`. Use `CKIT_EXPERIMENTAL=1 ckit init --runtime codex` for those.
- A plugin plus a project scaffold can expose a logical skill twice. `ckit doctor` checks
  project-local manifests and the enabled native plugin inventory when the host can return readable
  JSON; it reports an unavailable registry check instead of treating it as proof of no duplication.

## Codex and `both` are Preview, not parity claims

- Native Codex artifacts parse, install, strictly validate, and survive wheel/sdist and runtime-
  transition smokes. Normalized hook adapters also have positive allow/block tests. These checks do
  not yet prove every protected live-host persona, delegation, permission, worktree, and lifecycle
  event behavior.
- Codex project hooks require trust. `PermissionRequest` and `PostCompact` are not projected. Only
  supported command-handler semantics are adapted; event-name overlap is not treated as equivalence.
- Semantic model tiers are preserved, but Codex agent TOML deliberately inherits the active model.
  Per-agent permission classes become instructions while the native sandbox/approval policy remains
  authoritative. Equivalent enforcement is not claimed.
- `CKIT_EXPERIMENTAL=1 ckit pipeline run --provider claude|codex` now executes the frozen managed
  Mode A–D graph as far as the selected adapter's attested capabilities allow and defaults to a
  run-owned integration worktree. Every shell-capable Claude route requires
  `process.descendant_containment`. The built-in Codex adapter admits only passive read-only,
  nondelegating roles on exact compatibility-pinned hosts after a fail-closed feature-lockdown
  probe. It supplies a bounded, filtered projection of tracked text and disables local command,
  hook, plugin, MCP, browser, app, and delegation surfaces. Every shell, write, delegation, browser,
  MCP, and external-effect Codex route still requires descendant containment and stops before
  spawn. Process-group cleanup cannot contain a deliberately re-sessioned descendant. The
  deterministic adapter, routing, retry, cancellation, ledger, and isolation boundaries are tested,
  but protected credentialed live-host behavior remains a promotion gate.
- Codex managed workers run with strict config, an OS-enforced project sandbox, outbound command
  networking disabled, `/tmp` excluded from writable roots, and automatic secret-name filtering in
  spawned command environments. Claude managed workers receive exact tools and permission modes,
  unrelated deployment credentials are withheld, and their complete worktree delta is verified,
  but Claude Code does not expose an equivalent portable OS-enforced shell-network sandbox. A
  manually delegated or independently contained shell-capable Claude role could still attempt an
  external action through local credentials or helpers; this is a Preview degradation, not an
  asserted containment guarantee. The bundled managed backend stops those roles before spawn.
- Managed human-stop approval is **Unsupported**. A project-local evidence file and free-form
  resolver identity cannot safely authorize one exact stage/action/workspace once, so an
  `approved` decision remains pending. A `rejected` decision records only replan/abort intent.
  Non-managed legacy/manual approval records remain compatible, but they are not a managed
  capability grant. Managed closeout now separates credential-free `pull-request-prepare` from a
  final typed PR-create leaf requiring exactly `external.mutation`; the latter is never passed to a
  native-role fallback and remains stopped until a genuinely external signer and broker exist.
- Managed execution deliberately does not merge its integration worktree into the main checkout.
  It requires provider configuration and application inputs to be committed in `HEAD` (only
  mutable `.ckit/` state is exempt) and preserves the workspace for an explicit human-reviewed
  handoff. Mode E now has a typed manifest-bound wave/unit ledger, program gates, bounded evidence,
  checkpoints, and cross-provider no-replay, but remains **Degraded**. The bundled adapters can run
  only pure read/search audit units; shell/write/gate/closeout units require an independently
  attested physical no-follow boundary backend. Irreversible units stop before claim because no
  consume-once external approval broker is integrated. This is not a general managed-parity claim.
- New headless-loop iterations are **Unsupported** for both hosts. The installed script can strictly
  validate an already-completed run, but `begin_headless_iteration` refuses before host launch and
  mints no transition token. Process-group cleanup is not descendant containment; promotion needs a
  true containment primitive plus crash-recoverable coordinator authority.
- Historical learning catch-up and automatic Codex ticket telemetry are degraded/unsupported. The
  native projection emits an explicit no-op rather than invoking a Claude executable.
- See [runtime support](runtime-support.md) for every Native / Adapted / Degraded / Unsupported label
  and the promotion gates.

## Learning capture reads session content (when enabled)

- With `capture_mode` enabled (**off by default since 0.76.0** — it turns on only when you choose a
  mode at interactive init or set one in a `--config` file), a sandboxed background job reads
  **changed files and available host context** to distil learnings into `.ckit/agent-memory/`.
  The Claude capture worker is allowlisted to file tools only. The Codex classifier runs read-only
  from a private temporary directory, ignores user config and project rules, and disables local
  command, hook, plugin, MCP, browser, web, and delegation surfaces. It receives only a bounded
  coordinator-produced changed-file diff after sensitive paths are withheld and secret-shaped
  values are redacted. Its strict JSON is untrusted: `ckit` validates it, derives the contained
  destination, and performs the only writes to the canonical memory store. Historical Codex
  transcript catch-up remains unavailable. The worker also fails closed outside the exact audited
  Codex host-version window, so a newly released CLI may require a compatibility-catalog update
  before background capture resumes. Filters cannot recognize every sensitive value, and the
  inference provider still receives the filtered diff — controls:
  `capture_mode: off` in your init config, `CKIT_NO_AUTOCAPTURE=1` at runtime, and
  `ckit privacy-report` to audit what is installed. The matching `CLAUDE_KIT_*` variables remain
  compatibility aliases. `doctor` warns when capture is on, and
  installs made before 0.76.0 keep their recorded choice across upgrades (the upgrade prints a
  notice when capture is on).

## `pentest-scanner` may be refused at the platform level, and needs more than an install

- The agent is **enterprise-profile only, opt-in, and preflight-gated**: it runs nothing without an
  explicit request, a concrete **authorized non-production** target, and an installed tool (Strix,
  Shannon, PentesterFlow or ZAP) with its runtime. A default install has none of those, so out of the
  box it reports `SKIPPED` — by design. It never edits code and never blocks the Security Clear gate.
- Separately, and outside claude-kit's control: **a request phrased as a general "run a penetration
  test" can be refused by the model platform itself** under its cyber-content usage policy, ending the
  session before the agent's own preflight gate is ever reached. Measured twice; the refusal is a
  platform response to the request, not a kit malfunction, and the kit cannot suppress it.
- Practical consequence: treat this agent as available only inside a genuine, authorized engagement
  where you can state the target and the authorization. If you need static coverage instead, the four
  scanners that always run (`secret-scanner`, `dependency-scanner`, `owasp-reviewer`,
  `policy-validator`) read code and stand on their own.
- We have deliberately **not** reworded the agent to make the refusal go away. Tuning wording until a
  safety control stops firing would be evading it, not fixing anything.

## MCP servers are third-party

- `catalog/mcp.yaml` **references** external MCP servers (pinned to exact versions); claude-kit does
  **not vendor or audit** them. A scheduled freshness check flags stale pins, but bumping a pin is a
  deliberate, reviewed action. Treat each server as third-party software you are choosing to run.

## Command discovery is best-effort

- `init`/`upgrade` inspect a populated target for **unambiguous** package-manager signals and wire the
  real commands into the provider-projected project instructions. Current scope: JavaScript
  (npm·pnpm·yarn·bun) → the install command
  plus whichever `package.json` scripts exist (`dev`/`test`/`lint`/`build`/`typecheck`); Python
  (uv·poetry·pdm·hatch) → the **install** command only. Task runners (make·just·task) and rewriting
  Python *run/test/lint* commands are not yet detected — those keep the catalog defaults.
- Discovery is fail-open and conservative (an empty target is a no-op, which keeps `init --dry-run` ≡ a
  real install). Uncommon or bespoke setups may still need explicit overrides via `--config`; pass
  `--no-detect-commands` to skip discovery entirely and keep the generic catalog commands.

## Planned commands are not yet implemented

- `package-org-pack`, `install-org-pack`, and `research import-sources` are **planned**. They are
  hidden unless `CKIT_EXPERIMENTAL=1` and exit non-zero with a "planned" notice; they do not yet do
  anything. `CLAUDE_KIT_EXPERIMENTAL` remains a temporary alias.

## Project updates are rollback-journalled, not one atomic whole-tree swap

- `init`, merge, force install, and `upgrade` resolve and preflight the selected payload, render a
  complete install in controlled staging, strictly validate it, then snapshot the bounded live
  mutation surface before applying. An ordinary exception restores the snapshot immediately; an
  abrupt interruption leaves a schema-versioned journal and rollback data that the next invocation
  recovers. `doctor` reports an interrupted transaction. This is a tested rollback transaction, not
  a filesystem-wide atomic rename: power loss can leave recovery work for the next run, and the
  project must remain on a filesystem that preserves ordinary rename/write semantics. Each complete
  managed subtree is digest-verified and promoted with two renames under the cooperative project
  lease; a non-cooperating reader can still observe the brief gap between those renames.
- The filesystem layer refuses symlinks, junctions, or reparse points in managed destination paths,
  including `.ckit/`, `.claude/`, `.codex/`, backups, and sidecars. It does not "repair" an
  untrusted path automatically;
  replace the link with a regular project-local directory and retry.

## Native Windows project mutation fails closed

- In 0.83, mutating CLI operations require POSIX directory-descriptor operations plus `flock`-style
  project leases. Native Windows path rechecks cannot close the junction/reparse swap window before
  a pathname-based replace or recursive delete, so `init`, merge, `upgrade`, export, ticket-board
  writes, and pipeline transitions refuse rather than claim an unsafe guarantee. Existing project
  files are left untouched by that refusal.
- Use WSL on a filesystem that supplies those POSIX semantics for mutation. Plugin discovery and
  read-only inspection are not converted into writes. A Win32 handle-anchored backend and native
  Windows junction/race CI are explicitly deferred in the Phase 2 operating-system issue.

## Legacy state migration is explicit and temporarily dual-readable

- Fresh native installs use one `.ckit` control plane even for `both`. Existing mutable `.claude`
  state is not silently moved or deleted: use `--migrate-state` or the Preview `ckit migrate-state`
  command. If both exist, `.ckit` is authoritative and legacy bytes remain for diagnostics.
- The legacy reader is intentionally temporary: it is guaranteed from the first dual-runtime minor
  through the following two minor releases, with a deprecation warning required in the last one.
  See [runtime migration](runtime-migration.md) before changing runtimes.

## Evidence hashes are integrity checks, not signatures

- Passed/not-applicable/accepted-risk records bind evidence by SHA-256 and validation detects later
  drift. The hash and ledger live in the same mutable project, so an actor able to edit both can
  rewrite both. claude-kit therefore calls this **content-integrity checked** or **evidence-hashed**,
  not tamper-evident. Authenticated signed evidence/provenance is a post-Phase-1 backlog item.
- The Python layer mechanically enforces lifecycle, gate ordering, allowed transition types, and
  record bindings. It does not yet parse arbitrary test, coverage, SARIF, or review output to prove
  the semantic verdict. Those results remain Agent-enforced or Externally verified as labelled.
