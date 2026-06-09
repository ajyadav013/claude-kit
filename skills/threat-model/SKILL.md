---
name: threat-model
description: Use when adding or changing a security-relevant feature (auth, sessions, payments, data access, file upload, external integrations, multi-tenant boundaries) and you need a structured threat model. Enumerates assets, entry points, and threats (STRIDE), rates them, and proposes mitigations + tests before implementation.
---

# Threat Model

Produce a focused, actionable threat model for a feature or change — what could go wrong, how likely
and how bad, and what to do about it — **before** the code is written.

**Risk tier:** high (security work — see `.claude/rules/risk-classification.md`).

## When to use
- New or changed auth/authorization, sessions, password/secret handling, payments, file upload,
  data export, webhooks/external callbacks, or a multi-tenant boundary.
- Before implementing anything in a sensitive area; pairs with the `security-and-hardening` and
  `security-verification` skills (this one is design-time; those are build/verify-time).

## Who should use it
Engineers and the `security-reviewer`/`owasp-reviewer` agents. PMs/founders can start it to surface
risk early, then hand off.

## Required inputs
The feature/spec (or a clear description), the data it touches, and who the actors are (anonymous,
authenticated user, admin, service).

## Ordered questions to ask
1. What are the **assets** worth protecting here (data, money, access, availability)?
2. What are the **entry points / trust boundaries** (endpoints, inputs, uploads, third parties)?
3. Who are the **actors**, and which are untrusted?
4. For each entry point, walk **STRIDE**: Spoofing · Tampering · Repudiation · Information disclosure ·
   Denial of service · Elevation of privilege.
5. For each credible threat: likelihood × impact → severity, and the **mitigation** + the **test** that
   proves it.

## Agents to delegate to
`security-reviewer` (+ `owasp-reviewer`, `secret-scanner`, `dependency-scanner`, `policy-validator`)
for deep review; `risk-classifier` to confirm the tier.

## Quality gates
Every credible high/critical threat has a named mitigation **and** a test; no entry point left
unanalyzed; secrets/PII handling explicitly addressed (`.claude/rules/secrets-policy.md` /
`pii-policy.md` when present).

## Expected outputs
A short threat-model doc: assets · entry points/trust boundaries · STRIDE table (threat · severity ·
mitigation · test) · residual risks to watch.

## Stop conditions
Stop and escalate if the design has an unmitigated critical threat, requires storing secrets/PII without
a clear control, or exceeds the active autonomy level.

## Example
```
/threat-model Add S3 presigned-URL upload for user avatars
→ assets: user files, bucket creds; entry: presign endpoint + client PUT; actors: authn user, anon
→ STRIDE: Tampering (oversized/again-after-expiry), Info disclosure (enumerable keys),
  EoP (writing outside user's prefix) → mitigations: size/content-type limit, per-user key prefix,
  short TTL, deny-list MIME; tests for each. Residual: client-side type spoofing → server re-check.
```
