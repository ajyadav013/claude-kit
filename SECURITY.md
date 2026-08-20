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

claude-kit installs **configuration only** — no application code, no Docker. Its hook scripts are
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
mechanically enforced by the Python state layer. Most underlying test/review verdicts remain
Agent-enforced or Externally verified, and accepted risk is Human-attested. A SHA-256 stored beside a
mutable ledger is a content-integrity check, not authenticated tamper evidence: a writer who controls
both can rewrite both. Hook-enforced guards require their runtime, and prose-only requirements are
Advisory. MCP permissions combine local policy with an external server; they are not a sandbox.

Release artifacts are built once in CI, smoke-tested from the exact wheel, hashed, attested, and then
promoted without rebuilding through PyPI Trusted Publishing. The publish workflow verifies the
downloaded PyPI files against the CI manifest and attaches the same files to the GitHub Release. See
[`docs/operations/release-recovery.md`](docs/operations/release-recovery.md) for a partial-publication
recovery procedure and [`docs/operations/github-repository-settings.md`](docs/operations/github-repository-settings.md)
for the repository controls that still require maintainer configuration.

## Learning capture (data handling)

Learning capture is **opt-in** (0.76.0): a background Claude job reads your session transcript and
changed files to record durable learnings under `.claude/agent-memory/` (a committed store) — so it
runs **only** when you explicitly choose a capture mode at `claude-kit init` (the "Learning capture"
question) or set `capture_mode` in a config file. Every non-interactive path stays off: the plugin
channel and `--defaults` install no capture hooks. The recall
half of the loop (reading your own `agent-memory/MEMORY.md` into context) has no such exposure and
stays on. **This opt-in applies to fresh installs**: a project initialized before 0.76.0 keeps the
capture mode recorded at its own init across upgrades (an upgrade never silently changes your
selection — it prints a notice when capture is on); check yours with `claude-kit privacy-report`
and re-run `init` or set `CLAUDE_KIT_NO_AUTOCAPTURE=1` to turn it off.

When enabled, the job skips secret-bearing files (`.env`, `*.pem`/`*.key`, `credentials.*`) and
redacts secret-shaped values (private keys, `AKIA…`, `sk_live_…`, Slack/GitHub tokens) before
anything reaches it, and it is instructed never to record secrets or personal data. These are
**best-effort** filters, not a guarantee — transcripts can still hold sensitive context, so review
new `agent-memory/` entries before committing. Disable at any time with
`CLAUDE_KIT_NO_AUTOCAPTURE=1` (or remove the capture entries from `.claude/settings.json`); bound
each run with `CLAUDE_KIT_CAPTURE_MAX_LINES` / `CLAUDE_KIT_CAPTURE_MAX_BYTES`.

Audit what an installed config actually accesses with **`claude-kit privacy-report`** — one line
per installed hook (what it reads, what it writes, whether it spawns a background job), plus
whether capture is on and how to turn it off.
