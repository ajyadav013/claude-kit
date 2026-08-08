# Security Policy

## Supported versions

claude-kit is pre-1.0. Only the latest released version (currently **0.78.0**) receives security fixes.

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

## Learning capture (data handling)

Learning capture is **opt-in** (0.76.0): a background Claude job reads your session transcript and
changed files to record durable learnings under `.claude/agent-memory/` (a committed store) — so it
runs **only** when you explicitly choose a capture mode at `claude-kit init` (the "Learning capture"
question) or set `capture_mode` in a config file. Every non-interactive path stays off: the plugin
channel and the no-pip starter ship no capture hooks, and `--defaults` installs none. The recall
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
