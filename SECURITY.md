# Security Policy

## Supported versions

claude-kit is pre-1.0. Only the latest released version (currently **0.62.0**) receives security fixes.

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

Learning capture is **on by default**: a background Claude job reads your session transcript and
changed files to record durable learnings under `.claude/agent-memory/` (a committed store). It skips
secret-bearing files (`.env`, `*.pem`/`*.key`, `credentials.*`) and redacts secret-shaped values
(private keys, `AKIA…`, `sk_live_…`, Slack/GitHub tokens) before anything reaches the job, and the job
is instructed never to record secrets or personal data. These are **best-effort** filters, not a
guarantee — transcripts can still hold sensitive context, so review new `agent-memory/` entries before
committing. Disable with `CLAUDE_KIT_NO_AUTOCAPTURE=1`; bound each run with
`CLAUDE_KIT_CAPTURE_MAX_LINES` / `CLAUDE_KIT_CAPTURE_MAX_BYTES`.
