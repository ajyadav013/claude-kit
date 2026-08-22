# Security Policy

## Supported versions

claude-kit is pre-1.0. Only the latest released version (currently **0.83.0**) receives security fixes.

## Reporting a vulnerability

Please report security issues **privately** — do not open a public issue with exploit details.

- **Preferred:** GitHub **Private vulnerability reporting** on
  <https://github.com/ajyadav013/claude-kit> (the repo's **Security** tab → *Report a vulnerability*).
- Alternatively, open a minimal public issue asking a maintainer to open a private channel — without
  including the details of the vulnerability.

You can expect an acknowledgement within a few days. Please allow reasonable time for a fix to ship
before any public disclosure.

## Scope

claude-kit installs **configuration only** — no application code, no Docker. Its Claude Code and
Codex hook adapters are
best-effort **guardrails** (e.g. blocking `rm -rf`, reads of secret files, and direct pushes to
`main`/`master`) that **degrade to no-ops** when a required tool (such as `jq`) is absent. They are
convenience guards, **not a hardened security boundary**.

In scope: the scaffolder/CLI (`src/claude_kit/`), the guard hook scripts (`hooks/`), the catalog
(`catalog/`), and the installed configuration. Out of scope: vulnerabilities in *your own project's*
application code, and the behavior of third-party MCP servers the kit can wire up.

The Python installer treats the target repository as untrusted filesystem input. Project-relative
destinations are checked for traversal, absolute/drive/UNC forms, symlinks, junctions, and reparse
points; install/merge/force/upgrade use a schema-versioned rollback journal. A refusal is a security
result: remove the unsafe link or choose a regular project root rather than bypassing the check.
Mutation currently requires POSIX directory-descriptor and advisory-lock primitives. Native Windows
mutation fails closed because pathname rechecks alone cannot exclude a junction-swap race; use WSL
on a POSIX-semantics filesystem. The refusal occurs before the requested project mutation.

Pipeline lifecycle, gate order, transition type, commit/gate bindings, and evidence hashes are
mechanically enforced by the Python state layer under one `.ckit` control plane. A dual-runtime
install does not have separate Claude and Codex ledgers. Most underlying test/review verdicts remain
Agent-enforced or Externally verified, and accepted risk is Human-attested. A SHA-256 stored beside a
mutable ledger is a content-integrity check, not authenticated tamper evidence: a writer who controls
both can rewrite both. Hook-enforced guards require their runtime, and prose-only requirements are
Advisory. MCP permissions combine local policy with an external server; they are not a sandbox.

Provider trust remains external to the kit. Review generated project hooks and MCP configuration
before trusting a checkout; Codex requires project trust before non-managed hooks run. Installing a
static plugin and scaffolding the same project may expose a logical skill from two sources. `ckit
doctor` checks project-local manifests and, when a native host can return a readable JSON inventory,
warns about an enabled installed `claude-kit` plugin alongside the scaffold. It reports when that
registry check is unavailable rather than claiming absence. Claude and Codex permission/sandbox
models are not equivalent: Codex Preview keeps semantic permission intent in instructions while the
host's sandbox and approval policy remain authoritative.

The opt-in Preview command `ckit pipeline run --provider claude|codex` is the one exception to the
otherwise configuration-only operating model: after capability preflight, it may launch the
selected native host CLI as a bounded subprocess, with argv construction that never uses a shell
and the stage prompt supplied on stdin. The child receives only core process settings, kit settings,
and the selected host's authentication/configuration variables; unrelated GitHub, deployment,
database, and cloud credentials are filtered out. A provider whose required boundary is not
attested stops before spawn. The bundled Codex adapter has one narrow exception: an exact
compatibility-pinned CLI may run a passive read-only, nondelegating role only after a fail-closed
local probe confirms that command, hook, plugin, MCP, browser, app, and delegation surfaces are
disabled. That role receives only a bounded, sensitive-path-filtered projection of tracked text.
All Codex shell, write, delegation, browser, MCP, and external-effect roles still stop before spawn
without independent descendant containment.
Successful launches run in a run-owned worktree, persist bounded result metadata under
`.ckit/artifacts/dispatch/`, and never perform an automatic main-checkout merge. Provider
configuration and application inputs must be committed in `HEAD` before launch; the runner fails
closed rather than create a worker with missing or dirty context.
Task/context text and native-host output can be sensitive; protect the `.ckit` artifact directory
and inspect the preserved worktree before explicitly merging it. A human stop is an authorization
boundary, not an error to bypass.

Release artifacts are built once in CI, smoke-tested from the exact wheel, hashed, attested, and then
promoted without rebuilding through PyPI Trusted Publishing. The publish workflow verifies the
downloaded PyPI files against the CI manifest and attaches the same files to the GitHub Release. See
[`docs/operations/release-recovery.md`](docs/operations/release-recovery.md) for a partial-publication
recovery procedure and [`docs/operations/github-repository-settings.md`](docs/operations/github-repository-settings.md)
for the repository controls that still require maintainer configuration.

## Learning capture (data handling)

Learning capture is **opt-in** (0.76.0): a background selected-host job reads available host context
and changed files to record durable learnings under `.ckit/agent-memory/` (a committed store) — so it
runs **only** when you explicitly choose a capture mode at `ckit init` (the "Learning capture"
question) or set `capture_mode` in a config file. Every non-interactive path stays off: the plugin
channel and `--defaults` install no capture hooks. The recall
half of the loop (reading your own `agent-memory/MEMORY.md` into context) has no such exposure and
stays on. **This opt-in applies to fresh installs**: a project initialized before 0.76.0 keeps the
capture mode recorded at its own init across upgrades (an upgrade never silently changes your
selection — it prints a notice when capture is on); check yours with `ckit privacy-report`
and re-run `init` or set `CKIT_NO_AUTOCAPTURE=1` to turn it off.

When enabled, the job skips secret-bearing files (`.env`, `*.pem`/`*.key`, `credentials.*`) and
redacts secret-shaped values (private keys, `AKIA…`, `sk_live_…`, Slack/GitHub tokens) before
anything reaches it, and it is instructed never to record secrets or personal data. For Codex, a
coordinator supplies only that bounded filtered diff to a read-only, tool-disabled classifier in a
private directory; strict JSON returns to a trusted contained writer, and the model never receives a
workspace write capability. These are **best-effort** filters, not a guarantee — Claude transcripts
and the Codex filtered diff can still hold sensitive context, so review new `agent-memory/` entries
before committing. Disable at any time with
`CKIT_NO_AUTOCAPTURE=1`; bound each run with `CKIT_CAPTURE_MAX_LINES` /
`CKIT_CAPTURE_MAX_BYTES`. The matching `CLAUDE_KIT_*` names remain accepted during the documented
compatibility window, but new automation should use `CKIT_*`.

Codex capture uses the changed-path set and a provider background task rather than depending on a
Claude transcript. Historical transcript catch-up is degraded, and automatic Codex ticket telemetry
is unsupported; the projection emits explicit no-op behavior rather than invoking the `claude`
executable. These limitations are part of the [runtime support contract](docs/runtime-support.md).

Audit what an installed config actually accesses with **`ckit privacy-report`** — one line
per installed hook (what it reads, what it writes, whether it spawns a background job), plus
whether capture is on and how to turn it off.
