# PII Policy

Personally identifiable information (PII) is any data that identifies a person — names, emails,
phone numbers, addresses, government IDs, location, device IDs, health or financial details. Treat
it as a liability, not an asset: the safest PII is the data you never collected. Identify it early
and handle it under this policy for the whole task.

## Identify PII first

1. **Spot it at intake.** When a prompt or spec involves user data, name which fields are PII before
   designing anything. If unsure whether a field is PII, treat it as PII (see
   `rule://ambiguity-resolution`).
2. **Minimise collection.** Capture only the fields the goal actually needs; drop or aggregate the
   rest. Prefer a non-identifying token over the raw value where one will do.
3. **Mark the boundary.** Note where PII enters, where it is stored, and where it leaves — so every
   later step knows what it is handling.

## Handling rules

- **Never log PII.** No PII in application logs, console output, traces, metrics, analytics events,
  or error reports — redact or hash before anything is written out. Same bar as secrets
  (`rule://secrets-policy`).
- **Encrypt in transit and at rest.** PII moves only over encrypted transport and is stored only in
  the project's encrypted data store; no plaintext PII in flat files, tickets, or chat.
- **Enforce access controls.** Least privilege — only the components and roles that need a field may
  read it. No broad "read everything" access to PII stores.
- **Limit retention.** Keep PII only as long as the goal requires, then delete or anonymise it;
  never retain "just in case." Honour any deletion request.
- **Scrub fixtures and test data.** Use synthetic or anonymised data in tests, seeds, and demos —
  never real PII (`rule://production-data-policy`).
- **Scrub error reports.** Strip PII from stack traces, crash dumps, and bug reports before they
  leave the system or reach a third party.

## Rules

1. **When in doubt, redact.** Withholding a field is cheap; leaking one is not reversible — it may be
   cached, indexed, or shipped before anyone notices.
2. **Escalate exposure.** Any PII in a log, fixture, or external payload is at least **high** risk
   (`rule://risk-classification`) — stop, report it, and get a human decision
   (`rule://human-in-the-loop`).
3. **Don't move PII across boundaries** (new store, external service, lower environment) without
   explicit approval.

> Part of {{ provider.executable.cli }}'s organization capability layer. Cross-refs `rule://secrets-policy`,
> `rule://production-data-policy`, `rule://compliance-policy`. The
> `security-reviewer` and `policy-validator` agents enforce this at the gate.
