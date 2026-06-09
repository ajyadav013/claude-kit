---
name: prototype-to-production
description: Use when a founder, operator, or PM has a working prototype or throwaway script that "just works" and wants it hardened into a production-safe feature — adding input validation, authn/authz, error handling, logging, rate limits, and tests, with a mandatory review gate before anything is called production-ready. Identify risks → harden → test → review → ship.
---

# Prototype to Production

Take a prototype or quick script that works on a happy path and harden it into a feature safe to put
in front of real users and real data — without the requester needing to write the hardening code.

**Risk tier:** **high** by default (prototype → production is a high-risk transition); **restricted**
if it touches auth, payments, secrets, production data, PII, or migrations. See
`.claude/rules/risk-classification.md`.

## When to use
Someone has a working-but-unsafe prototype — "this CSV upload script we run by hand should be an admin
feature" — and wants it productionized through the normal pipeline instead of shipped as-is.

## Who should use it
Founders, operators, PMs. Engineers can use it too, but may prefer `/security-and-hardening` directly.

## Required inputs
The prototype/script and what it does. Helpful: who will use it, what data it touches, and how it runs today.

## Ordered questions to ask
1. Who are the **real users** and how do they reach this (internal-only, customers, public)?
2. What **data** does it read/write, and how **sensitive** is it (PII, secrets, production data)?
3. What happens on **bad input or failure** today — and what *should* happen?
4. What **access controls** exist (who is allowed to run it) vs. what's needed?
5. Any **limits** needed (rate, size, volume) and what must it **log/audit**?

## Agents to delegate to
`founder-prototype-agent` (frame the prototype + its gaps) → `risk-classifier` (tier it) →
`security-reviewer` (define hardening: validation, authn/authz, rate limits, secrets) →
`orchestrator` (run the build lane: `developer`, `sdlc-code-reviewer`, `tester`). Use
`/security-and-hardening` and `/test-driven-development` under the hood; respect
`.claude/rules/prototype-boundaries.md` and prototype-to-task-conversion concepts.

## Quality gates
Prototype risks enumerated; input validation, authn/authz, error handling, logging, and rate limits
added; tests cover the unsafe paths; secrets removed from code (`.claude/rules/secrets-policy.md`);
**human review recorded before production readiness**; the engineering pipeline's own gates then apply.

## Expected outputs
Risk inventory · users + data-sensitivity assessment · hardening plan (validation · authn/authz · errors ·
logging · rate limits) · risk tier · the explicit pre-production review checkpoint. Then (after review) a
hardened, tested implementation via the pipeline.

## Stop conditions
Stop and ask if it touches production data/PII/secrets without a clear policy, the prototype's behavior is
ambiguous, hardening would change intended behavior, or it exceeds the active autonomy level
(`.claude/rules/autonomy-levels.md`).

## Example
```
/prototype-to-production Turn our internal CSV upload script into an admin feature
→ asks: who uploads? what's in the CSV (PII)? what limits? what audit trail?
→ risk inventory: no authz, no validation, secrets in script, no rate limit; tier: high
→ hardening plan → routes to security-reviewer → developer + tester lanes
→ STOPS for review before it's marked production-ready
```
