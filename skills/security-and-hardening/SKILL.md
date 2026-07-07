---
name: security-and-hardening
description: Hardens code against vulnerabilities. Use when handling user input, auth, data storage, or integrations. Do NOT use for upfront STRIDE enumeration (use threat-model) or a live DAST scan (use zap-vapt-scanning).
---

# Security and Hardening

## Overview

Security-first development for any stack. Treat every external input as hostile, every secret as sacred, and every authorization check as mandatory — and in a multi-tenant system (if applicable), treat **every tenant-scoped query without proper scoping as a data breach**. Security isn't a phase; it's a constraint on every line that touches user data, auth, or external systems.

Companion rules: `.claude/rules/code-organization.md` (auth & dependency patterns), `.claude/rules/design-patterns.md` (service/repository boundaries), `.claude/rules/documentation.md` (security documentation). The `security-reviewer` agent (Phase 5.4 in `.claude/rules/mandatory-workflow.md`) enforces what this skill teaches.

This file carries the decision layer — boundaries, per-class rules, checklists, red flags. The code
patterns and deep-dive practices live in `references/` (linked per section below) and load on demand.

## When to Use

- Building anything that accepts user input
- Implementing authentication or authorization
- Storing or transmitting sensitive data
- Integrating with external APIs or services
- Adding file uploads, webhooks, or callbacks
- Handling PII
- Building an **LLM / AI feature** — prompts, chat, RAG, agents, or any call to a model (see *LLM / AI Feature Security* below)

## The Three-Tier Boundary System

### Always Do (No Exceptions)

- **Validate all external input** with typed schemas at the boundary (route handlers) — use the project's validation framework to enforce constraints, types, enums for constrained strings
- **Scope every tenant-restricted query appropriately** — filter by tenant/organization/account ID for multi-tenant systems
- **Parameterize all queries** — use the ORM's binding mechanism or prepared statements; never string interpolation with user input
- **Hash passwords with a strong algorithm** — argon2id, bcrypt, or scrypt; never MD5/SHA for new code
- **Keep async paths fully async** (if applicable) — async database sessions, async HTTP clients, async cache clients (blocking calls stall the event loop)
- **Set session cookies securely** — `HttpOnly=True`, `SameSite="lax"`, `Secure=True` in production
- **Restrict CORS** to an explicit origin allowlist
- **Rate-limit auth endpoints** (register, login, forgot/reset)
- **Run dependency audits** before every release

### Ask First (Requires Human Approval)

- Adding or changing authentication / session logic
- Storing new categories of sensitive data (PII)
- Adding new external service integrations
- Changing CORS origins or cookie/session settings
- Adding file upload handlers
- Modifying rate limiting or throttling
- Granting elevated roles (admin, superuser, etc.)

### Never Do

- **Never commit secrets** — config goes through environment variables or a secrets manager (gitignored)
- **Never log sensitive data** — no passwords, hashes, full session ids, tokens, or PII in logs
- **Never trust client-side validation** as a security boundary
- **Never run a query on a scoped model without the appropriate tenant filter** (multi-tenant systems)
- **Never use debug print statements** in app code, or render user input as raw HTML without sanitization
- **Never store auth tokens in browser localStorage** — sessions are cookie-based
- **Never disable TLS certificate verification on outbound calls** — no `verify=False`, `rejectUnauthorized: false`, `NODE_TLS_REJECT_UNAUTHORIZED=0`, or `curl -k` in app/CI code (see `references/owasp-top10-prevention.md` §Outbound TLS Verification)
- **Never accept cookie/session-authenticated state-changing requests without CSRF defense** (see `references/owasp-top10-prevention.md` §Cross-Site Request Forgery)
- **Never expose stack traces** or internal errors to clients

## OWASP Top 10 Prevention

One rule per class — the code patterns, language examples, and full defense discussion live in
[references/owasp-top10-prevention.md](references/owasp-top10-prevention.md):

- **Injection** — parameterize every query; never string-build SQL/commands from user input. Stronger:
  make the unsafe path *unrepresentable* — compile-time-constant query text + typed trusted/untrusted
  wrappers, with the raw string-accepting API banned by lint.
- **Broken authentication** — argon2id/bcrypt/scrypt for passwords; session cookies `HttpOnly` +
  `SameSite=Lax` + `Secure` in production.
- **XSS** — rely on framework auto-escaping; if HTML rendering is unavoidable, sanitize first
  (DOMPurify or equivalent).
- **Broken access control** — every endpoint authenticates *and* authorizes; scope every lookup to the
  caller's tenant — a bare lookup by id is an IDOR.
- **Security misconfiguration** — CORS from an origin allowlist (never `*` with credentials); security
  headers (`X-Content-Type-Options`, `X-Frame-Options`, HSTS, CSP) on every response.
- **Sensitive data exposure** — Read schemas exclude `password_hash`/tokens by construction; secrets
  come only from environment/settings, never source.
- **CSRF** — every cookie/session-authenticated mutation requires an anti-CSRF token compared in
  constant time; `SameSite` alone is a partial mitigation.
- **Outbound TLS** — verification stays on everywhere; a private/internal CA gets a CA bundle, never
  `verify=False` or its equivalents.
- **Continuous least-privilege** — permissions only accrete; run the decay loop (audit exercised
  permissions over a trailing window → revoke the unused → snapshot for rollback → repeat), with an
  exempt-list for break-glass access.

## Input Validation Patterns

Code patterns in [references/input-validation-and-uploads.md](references/input-validation-and-uploads.md):

- **Schema validation at the boundary** — typed schemas with constraints on every request body; the
  framework rejects invalid input (422) before your code runs.
- **File uploads** — allowlist content types, cap size, verify magic bytes when it matters; never
  trust the extension.
- **Archive extraction** — canonicalize-then-contain every entry path (defeats zip-slip and absolute
  paths), refuse symlinks/hardlinks in untrusted archives, cap uncompressed size and entry count
  (decompression bombs).
- **ReDoS** — use a linear-time regex engine for untrusted input; never compile a user-supplied
  pattern in a backtracking engine without an allowlist and a timeout/length cap.

## Triaging Dependency Audit Results

The full decision tree, plus SBOM generation, reproducible-build verification, and source-level
missing-patch detection, live in
[references/supply-chain-and-dependencies.md](references/supply-chain-and-dependencies.md):

- **Critical/high + reachable** → fix immediately (upgrade / patch / replace); unreachable or
  dev-only → fix soon, not a release blocker. Moderate → next cycle (prod) or backlog (dev-only).
  Low → regular update cadence.
- **No fix available** → workaround, replace the dependency, or allowlist **with a review date** —
  never a silent deferral.
- **A CVE audit is one supply-chain layer, not the whole stack** — pair it with the
  `dependency-verification` skill (pre-install name check), the `dependency-scanner` agent's
  integrity mode (post-resolve), an SBOM per release, and reproducible-build verification for what
  you publish.
- **Editing dependency manifests requires user approval** — the `dependency-scanner` recommends, the
  developer lane applies. Document any deferral with a reason and a review date.

## Rate Limiting (Cache-backed)

Apply rate limiting to authentication and public endpoints:

```python
# Example with Redis-backed rate limiting
@router.post("/v1/auth/login", response_model=...)
async def login(
    payload: LoginRequest,
    _: None = Depends(rate_limit("auth:login", max_calls=10, window_seconds=900)),  # 10 / 15 min
    db: AsyncSession = Depends(get_db_session),
) -> ...:
    ...
```

- Key unauthenticated endpoints by **client IP**; authenticated by **user id**.
- Cover `register`, `login`, `forgot-password`, `reset-password`.

## Secrets Management

```
.env files:
  ├── .env.example  → committed (placeholder values only)
  ├── .env          → NOT committed (real secrets)
  └── .env.*.local  → NOT committed

.gitignore must include: .env, .env.local, .env.*.local, *.pem, *.key
All config is read via the project's settings framework — never scattered environment reads.
```

```bash
# Before committing — check for staged secrets
git diff --cached | grep -iE "password|secret|api_key|token|SECRET_KEY|DATABASE_URL"
```

## LLM / AI Feature Security (OWASP LLM Top 10) — opt-in

Applies **only when your product builds an LLM/AI feature** — it sends user (or tool/RAG) input to a
model, or uses a model's output. This is a *different* threat class from the OWASP Top 10 above (which
the mandatory `security-reviewer` gate enforces). These LLM guardrails are **opt-in / advisory** — the
Security Clear gate does **not** block on them — but the threats are real, so treat the guardrails as
the default for any model-backed feature and *consciously* decide before skipping (see *Opt-in & bypass*).

> Distinct from `.claude/rules/agent-guardrails.md`, which secures the *Claude Code agent itself*. This
> section secures the LLM features **in the product you ship**. Reference implementations are
> tool-agnostic — e.g. **llm-guard** (Python: `scan_prompt` / `scan_output` + a PII *vault*),
> provider-native safety filters, or your own checks. The pattern matters more than the library.

### The guard architecture: scan input → model → scan output

A model is an untrusted, non-deterministic component — untrusted input goes in, untrusted output comes
out. Put a guardrail layer on **both sides** of every model call:

```
user / RAG / tool input ──▶ [INPUT guardrails] ──▶ model ──▶ [OUTPUT guardrails] ──▶ app uses it
```

The guardrail specifics — input screening (injection, secrets scan, PII vault, token budget,
canonicalisation), output handling (treat as untrusted, leak scan, SSRF allowlist, structured-output
validation), least-privilege for model-invoked tools, and the OWASP LLM Top 10 map — live in
[references/llm-guardrails.md](references/llm-guardrails.md).

### Opt-in & bypass (risk acceptance)
This layer is **advisory, not a hard gate** — you can ship without it. The `warn-llm-io` hook (when
enabled in your profile) reminds you when you edit model-calling code; it **never blocks**. To skip a
guardrail deliberately, record a one-line **risk acceptance** in the spec/PR — *what* you're skipping,
*why*, *who* accepted it, and a *review date* — so the decision is explicit and revisitable, not silent.

### Security implications of bypassing
| If you skip… | You accept the risk of… |
|---|---|
| Input injection screening | Prompt injection → data exfiltration, unauthorised tool/actions, jailbreaks |
| PII anonymisation | User PII sent to a third-party provider → privacy/compliance (e.g. GDPR) breach, provider-side retention |
| Output handling (treat as untrusted) | XSS / SSRF / SQL or code injection / RCE downstream from rendered or executed output |
| Token / length limits | Cost blow-ups and model-DoS from unbounded or adversarial inputs |
| Tool least-privilege | An injected prompt driving real, destructive actions through over-privileged tools |

## Security Review Checklist

```markdown
### Authentication
- [ ] Passwords hashed with a strong algorithm (argon2id, bcrypt, scrypt)
- [ ] Session cookies HttpOnly + SameSite=Lax + Secure(prod)
- [ ] Login + forgot/reset rate-limited
- [ ] Password-reset tokens expire

### Authorization & Tenancy
- [ ] Every endpoint uses the auth chain (authentication + authorization)
- [ ] EVERY tenant-scoped query filters by tenant/organization/account ID (multi-tenant systems)
- [ ] Users cannot reach another tenant's resources (no IDOR)
- [ ] Create schemas don't accept server-owned fields (id, tenant_id, etc.)

### Input
- [ ] All request bodies validated with typed schemas and constraints
- [ ] Queries parameterized (no string interpolation with user input)
- [ ] Frontend: no raw HTML rendering with user data

### Data & Logging
- [ ] No secrets in code or git history (environment variables / secrets manager)
- [ ] Read schemas exclude password_hash / tokens
- [ ] Logs never contain passwords, hashes, session ids, or PII

### Infrastructure
- [ ] CORS origins allowlist (no "*")
- [ ] Security headers set (X-Content-Type-Options, X-Frame-Options, HSTS, CSP)
- [ ] Dependency audits clean of Critical/High
- [ ] Error responses don't leak internals
- [ ] Cookie/session state-changing requests protected by an anti-CSRF token (not SameSite alone)
- [ ] No outbound TLS verification disabled (`verify=False` / `rejectUnauthorized:false` / `NODE_TLS_REJECT_UNAUTHORIZED=0` / `curl -k`); private CAs supplied via a CA bundle

### LLM / AI features (if any — see "LLM / AI Feature Security"; opt-in)
- [ ] Input screened for prompt injection; retrieved/tool content treated as data, not instructions
- [ ] No secrets sent to the model; PII anonymised before the model (restored via vault after)
- [ ] Model output treated as untrusted — never eval/render-raw/auto-run without validation
- [ ] Output scanned for leaked PII/secrets; emitted URLs allowlisted (SSRF); structured output validated
- [ ] Input/token limits bound cost & DoS; model-invoked tools are least-privilege
- [ ] Any skipped guardrail has a recorded risk acceptance (what / why / who / review date)
```

See `.claude/skills/_references/security-checklist.md` for the full pre-commit checklist.

## Common Rationalizations

| Rationalization | Reality |
|---|---|
| "This is an internal tool, security doesn't matter" | Internal tools get compromised. Attackers target the weakest link. |
| "We'll add security later" | Retrofitting is 10x harder. Add it now. |
| "No one would try to exploit this" | Automated scanners will find it. Obscurity is not security. |
| "The framework handles security" | Frameworks provide tools, not guarantees — raw queries and missing tenant filters still leak. |
| "It's just a prototype" | Prototypes become production. Security habits from day one. |

## Red Flags

- A query on a scoped model with no tenant/organization/account filter (multi-tenant systems)
- Raw SQL or string interpolation building queries; user input in system commands
- Secrets in source, config files, or commit history
- Endpoints missing authentication / authorization enforcement
- CORS origins set to `*`, or no rate limiting on auth endpoints
- Outbound TLS verification disabled (`verify=False`, `rejectUnauthorized: false`, `NODE_TLS_REJECT_UNAUTHORIZED=0`, `curl -k`), or a TLS-no-verify flag wired into a config
- Cookie/session-authenticated mutations with no CSRF token; `SameSite=None` cookies with no CSRF defense; a CSRF middleware that is defined but never enforced
- Logs that include passwords, tokens, or PII
- Blocking calls in async request paths (if async architecture)
- Stack traces or internal errors returned to clients
- Model output passed to eval/exec, rendered as raw HTML, or used to build SQL/shell without validation
- User PII or secrets sent to a model provider with no anonymisation; retrieved/tool content trusted as instructions

## Verification

After implementing security-relevant code:

- [ ] Run dependency audit — no Critical/High vulnerabilities
- [ ] No secrets in source or git history
- [ ] Every tenant-scoped query filters by tenant/organization/account ID (multi-tenant systems)
- [ ] All input validated via typed schemas at the boundary
- [ ] Auth + authz enforced on every protected endpoint
- [ ] Passwords hashed with strong algorithm; session cookies HttpOnly/SameSite/Secure
- [ ] Logs contain no secrets/PII; error responses don't expose internals
- [ ] Rate limiting active on auth endpoints
- [ ] Cookie/session mutations carry an enforced anti-CSRF token; outbound TLS verification never disabled

## References (deep-dive files, loaded on demand)

- [owasp-top10-prevention.md](references/owasp-top10-prevention.md) — per-class code patterns (injection incl. secure-by-construction, auth, XSS, access control, misconfiguration, data exposure, CSRF, outbound TLS) + continuous least-privilege pruning
- [input-validation-and-uploads.md](references/input-validation-and-uploads.md) — schema validation examples, file-upload safety, archive-extraction hardening (zip-slip/symlink), ReDoS defense
- [supply-chain-and-dependencies.md](references/supply-chain-and-dependencies.md) — CVE triage decision tree, SBOM generation, reproducible-build verification, source-level missing-patch detection
- [llm-guardrails.md](references/llm-guardrails.md) — input/output guardrail specifics, tool least-privilege, OWASP LLM Top 10 quick map
