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

- With `capture_mode` enabled (the default is `session-end-catchup`), a sandboxed background job reads
  **changed files and the session transcript tail** to distil learnings into `.claude/agent-memory/`.
  It runs with file tools only (no Bash), **skips sensitive files** (`.env`, `*.pem`, `*.key`,
  `id_rsa`, `credentials*`, `secrets/`, `.ssh/`, `.aws/`, …), **redacts secret-shaped values**, and
  **caps the transcript** by lines and bytes. It still summarizes your working context — disable it
  with `--capture-mode off` if that's not acceptable. `doctor` warns when capture is on.

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

## Upgrades are convergent and journalled, but install replace is not atomic

- `claude-kit upgrade` writes an `upgrade-in-progress.json` journal, backs up modified/removed files,
  and is convergent (a re-run finishes an interrupted upgrade; `doctor` warns if a journal is left
  behind). However, the first-time directory install (`_copy_tree`) replaces a kit-owned subtree
  non-atomically — an interrupted *install* (not upgrade) can leave a partial tree that a re-run
  restores.
