---
name: threat-model
description: Use when adding or changing a security-relevant feature (auth, sessions, payments, data access, file upload, external integrations, multi-tenant boundaries) and you need a structured threat model. Enumerates assets, entry points, and threats (STRIDE), rates them, and proposes mitigations + tests before implementation. Do NOT use to write or harden the secure code itself (use security-and-hardening) or to run a live vulnerability scan (use zap-vapt-scanning).
---

# Threat Model

Produce a focused, actionable threat model for a feature or change — what could go wrong, how likely
and how bad, and what to do about it — **before** the code is written.

**Risk tier:** high (security work — see `.claude/rules/risk-classification.md`).

## When to use
- New or changed auth/authorization, sessions, password/secret handling, payments, file upload,
  data export, webhooks/external callbacks, or a multi-tenant boundary.
- A new **LLM / AI feature** (prompts, chat, RAG, agents, or any model call) — also walk the LLM
  threat class (step 6 below).
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
6. **If the feature calls a model:** also walk the **LLM Top 10** — prompt injection (untrusted
   input/RAG/tool content treated as instructions), insecure output handling (output executed/rendered
   without validation → Info disclosure / EoP), sensitive-info disclosure (PII to the provider), model
   DoS (token/cost), excessive agency (over-privileged model tools). Apply the input/output guardrails
   in `.claude/skills/security-and-hardening/SKILL.md` → *LLM / AI Feature Security* (opt-in; state any
   bypass as a residual risk).

## Red-team the model feature (offensive verification)

The STRIDE/LLM walk above is *design-time* and *defensive* — it enumerates threats and names
mitigations. For an LLM/AI feature, pair it with an **offensive** pass that actually attacks the
deployed feature, because model-layer defenses are probabilistic: "we added an input filter" is a claim
until something tries to get past it.

- **Run multi-turn adversarial strategies, not just single-shot prompts.** The strong attacks are
  *conversational* — gradual escalation that never asks for the harmful thing directly (Crescendo),
  tree-of-attack search over rephrasings, role-play/persona framing, many-shot priming. A one-line
  "ignore your instructions" test proves almost nothing.
- **Cover the risk categories** your product cares about (prompt-injection / data exfiltration,
  jailbreak to disallowed content, PII leakage, unsafe tool invocation) — each with attack variants
  (encoding, obfuscation, indirect injection via retrieved/tool content).
- **Score with Attack Success Rate (ASR).** Make safety a *number* — the fraction of adversarial
  attempts that produced a policy violation — using a scorer (rule-based or LLM-judge, per `evals.md`
  §3) rather than eyeballing. Track ASR over time; it is the canonical metric for this failure class.
- **Make it continuous.** Red-teaming is not one-and-done — re-run on model/prompt/tool changes (wire it
  into the `evals.md` discipline; a rising ASR fails the gate).

This is a *verification* activity, so it runs after build alongside `security-verification` /
`zap-vapt-scanning` (which cover the non-model attack surface); this skill stays the design-time entry
point that decides *what* to red-team.

> Stack-agnostic adaptation of the operationalized GenAI red-teaming methodology (multi-turn attack
> strategies, scorer-driven evaluation, Attack Success Rate) in the MIT
> [`microsoft/PyRIT`](https://github.com/microsoft/PyRIT). Re-derived in prose; not vendored.

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
