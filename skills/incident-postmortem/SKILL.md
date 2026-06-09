---
name: incident-postmortem
description: Write a blameless postmortem after a production incident. Use when an incident is resolved and needs a root-cause writeup, when conducting an RCA, or when the user says "postmortem", "RCA", "writeup the incident", or "what went wrong". Produces a timeline, 5-whys root cause, contributing factors, and tracked action items.
---

# Incident Postmortem (blameless)

Turn a resolved incident into durable learning. **Blameless** means the writeup attacks the system and process, never a person — "the deploy lacked a migration gate," not "X forgot the migration." Blame kills the honest reporting that prevents the next outage.

## When to Use

- An incident (SEV1–SEV3) is resolved and needs a writeup.
- A near-miss worth capturing.
- The user asks for an RCA / postmortem / "what went wrong."

Pairs with the `incident-responder` agent (it runs the incident; this documents it afterward).

## Process

1. **Reconstruct the timeline** from the incident log (`docs/incidents/...`), git history, deploy records, and the project's structured logs and error-tracking / monitoring tooling. Use UTC; include detection, each action, mitigation, and resolution.
2. **Find the root cause with 5 Whys** — keep asking "why" past the proximate trigger to the systemic cause. Usually it lands on a missing guardrail/test/alert, not a typo.
3. **Separate trigger from cause.** The trigger is what set it off; the root cause is why the system allowed it.
4. **List contributing factors** — what made it worse or slower to detect/fix (no alert, noisy logs, unclear ownership).
5. **Action items** — each concrete, owned, dated, and ideally a *systemic* fix (a test, an alert, a hook, a gate) so this class of incident can't recur silently. File them to the backlog.
6. **Promote the lesson** — add a durable entry to `.claude/agent-memory/gotchas/` via `remember` if it's a reusable pitfall (e.g., "migrations must be a separate gated step in prod").

## Template — `docs/incidents/{date}-{slug}-postmortem.md`

```markdown
# Postmortem: {title}
**Date:** {date} · **Severity:** SEV{n} · **Duration:** {detect→resolve} · **Author:** {who}

## Summary
{2–3 sentences: what broke, who was affected, how it was fixed.}

## Impact
- Users/tenants affected: {scope} · Duration: {time} · Data: {none/at-risk/lost}
- SLA/SLO breached: {which}

## Timeline (UTC)
| Time | Event |
|------|-------|
| {ts} | {detection — how we found out} |
| {ts} | {mitigation} |
| {ts} | {resolved} |

## Root Cause (5 Whys)
1. Why did it break? …
2. Why? …  3. Why? …  4. Why? …  5. (systemic) …

**Trigger:** {what set it off}  ·  **Root cause:** {why the system allowed it}

## Contributing Factors
- {slow detection / missing alert / unclear ownership / …}

## What Went Well / Poorly
- Well: {fast rollback, good logs}
- Poorly: {no alert, noisy signal}

## Action Items
| # | Action (systemic fix preferred) | Owner | Due | Type |
|---|---------------------------------|-------|-----|------|
| 1 | Add alert for {symptom} | | | detect |
| 2 | Add {test/hook/gate} so this can't recur silently | | | prevent |
```

## Rules

1. **Blameless** — systems and processes, never individuals.
2. **Every postmortem ends in tracked action items**; a writeup with no follow-ups is theater.
3. Prefer **systemic** fixes (alert, test, hook, gate) over "be more careful."
4. Keep it honest about detection/response gaps — that's where the value is.

> Adapted from a portfolio project's incident skill; generalized to be stack-agnostic for claude-kit.
