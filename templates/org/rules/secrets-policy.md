# Secrets Policy

Secrets are never code. API keys, passwords, tokens, private keys, connection strings, and signing
material must never be read into context, printed, logged, committed, or pasted into a chat. This rule
makes "just make it work with my key" safe — credentials stay out of the repo and out of the model.

## Never do

1. **Read or open** a secret-bearing file (`.env`, key files, credential dumps) to "see what's there".
2. **Print or log** a secret value — not in output, not in a debug line, not in an error message.
3. **Commit or push** a secret — config files, fixtures, and history all count.
4. **Hardcode** a credential inline instead of referencing an environment variable or secret manager.
5. **Echo a secret back** to the user or any external service.

## Do instead

- **Reference, don't embed.** Read secrets from environment variables or the project's secret manager
  at runtime; the code names the variable, never the value.
- **Keep a `.env.example`** with placeholder keys (no real values) so others know what to provide.
- **Gitignore real secret files** (`.env` and friends); only the example is tracked.
- **Rotate immediately on exposure.** If a secret is ever printed, logged, or committed, treat it as
  compromised: rotate it, then purge it from history — do not just delete the line.
- **Ask before touching** anything that looks secret-bearing; stop and escalate rather than guess.

## Enforcement

- The **protect-secrets** hook blocks reads of secret-bearing paths; the **guard-commit-secrets** hook
  blocks commits that contain credential patterns. Do not work around either — if one trips, stop.
- The **secret-scanner** agent audits a change for leaked credentials before delivery; a finding is at
  least **high** risk and blocks the security gate.

> Part of claude-kit's organization capability layer. Cross-refs `.claude/rules/agent-guardrails.md`
> (privilege/guardrail trips), `.claude/rules/pii-policy.md` (personal data handling), and
> `.claude/rules/compliance-policy.md` (regulatory obligations on exposure).
