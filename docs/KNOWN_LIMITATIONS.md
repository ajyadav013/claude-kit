# Known limitations

claude-kit is deliberately a **configuration scaffolder for Claude Code** — not a runtime, sandbox, or
security product. Being honest about the edges is part of the design. If one of these is a blocker for
you, that's useful signal — open an issue.

## Guard hooks are guardrails, not a security boundary

- The event hooks (block `rm -rf`, secret-file reads, pushes to `main`, destructive git, `kubectl
  delete`, …) require **`jq` and a POSIX shell**. Without them they **degrade to no-ops** — agents,
  rules, and skills still work, but the deterministic guards do nothing. Run `claude-kit doctor` to
  check.
- The git guards normalize the command (stripping `git -c …` / `git -C …` global options and matching
  force-push refspecs like `+main`) so they aren't trivially evaded — but they are **best-effort
  regex/tokenizers, not a sandbox**. A determined operator who deliberately crafts an obfuscated
  command (env-var indirection, `python -c`, `find -delete`) can still get past them. They exist to
  stop *accidental* agent mistakes, not a motivated adversary who already controls the machine.

## Plugin vs. CLI behavior differs before `init`

- Installed as a **plugin**, `/claude-kit:sdlc <task>` works immediately. The project-scaffolded
  `/sdlc` skill (and the project's agents/rules/hooks) only appear **after `claude-kit init` + a Claude
  Code restart/reload**. See the plugin-vs-CLI compatibility table in the README.

## Learning capture reads session content (when enabled)

- With `capture_mode` enabled (**off by default since 0.76.0** — it turns on only when you choose a
  mode at interactive init or set one in a `--config` file), a sandboxed background job reads
  **changed files and the session transcript tail** to distil learnings into `.claude/agent-memory/`.
  It runs with file tools only (no Bash), **skips sensitive files** (`.env`, `*.pem`, `*.key`,
  `id_rsa`, `credentials*`, `secrets/`, `.ssh/`, `.aws/`, …), **redacts secret-shaped values**, and
  **caps the transcript** by lines and bytes. It still summarizes your working context — controls:
  `capture_mode: off` in your init config, `CLAUDE_KIT_NO_AUTOCAPTURE=1` at runtime, and
  `claude-kit privacy-report` to audit what is installed. `doctor` warns when capture is on, and
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
  real commands into `CLAUDE.md`. Current scope: JavaScript (npm·pnpm·yarn·bun) → the install command
  plus whichever `package.json` scripts exist (`dev`/`test`/`lint`/`build`/`typecheck`); Python
  (uv·poetry·pdm·hatch) → the **install** command only. Task runners (make·just·task) and rewriting
  Python *run/test/lint* commands are not yet detected — those keep the catalog defaults.
- Discovery is fail-open and conservative (an empty target is a no-op, which keeps `init --dry-run` ≡ a
  real install). Uncommon or bespoke setups may still need explicit overrides via `--config`; pass
  `--no-detect-commands` to skip discovery entirely and keep the generic catalog commands.

## Planned commands are not yet implemented

- `package-org-pack`, `install-org-pack`, and `research import-sources` are **planned**. They are
  hidden unless `CLAUDE_KIT_EXPERIMENTAL=1` and exit non-zero with a "planned" notice; they do not yet
  do anything.

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
  including `.claude/`, backups, and sidecars. It does not "repair" an untrusted path automatically;
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

## Evidence hashes are integrity checks, not signatures

- Passed/not-applicable/accepted-risk records bind evidence by SHA-256 and validation detects later
  drift. The hash and ledger live in the same mutable project, so an actor able to edit both can
  rewrite both. claude-kit therefore calls this **content-integrity checked** or **evidence-hashed**,
  not tamper-evident. Authenticated signed evidence/provenance is a post-Phase-1 backlog item.
- The Python layer mechanically enforces lifecycle, gate ordering, allowed transition types, and
  record bindings. It does not yet parse arbitrary test, coverage, SARIF, or review output to prove
  the semantic verdict. Those results remain Agent-enforced or Externally verified as labelled.
