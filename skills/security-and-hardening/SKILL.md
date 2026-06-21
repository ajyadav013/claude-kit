---
name: security-and-hardening
description: Hardens code against vulnerabilities. Use when handling user input, authentication, data storage, or external integrations. Use when building any feature that accepts untrusted data, manages user sessions, or interacts with third-party services.
---

# Security and Hardening

## Overview

Security-first development for any stack. Treat every external input as hostile, every secret as sacred, and every authorization check as mandatory — and in a multi-tenant system (if applicable), treat **every tenant-scoped query without proper scoping as a data breach**. Security isn't a phase; it's a constraint on every line that touches user data, auth, or external systems.

Companion rules: `.claude/rules/code-organization.md` (auth & dependency patterns), `.claude/rules/design-patterns.md` (service/repository boundaries), `.claude/rules/documentation.md` (security documentation). The `security-reviewer` agent (Phase 5.4 in `.claude/rules/mandatory-workflow.md`) enforces what this skill teaches.

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
- **Never disable TLS certificate verification on outbound calls** — no `verify=False`, `rejectUnauthorized: false`, `NODE_TLS_REJECT_UNAUTHORIZED=0`, or `curl -k` in app/CI code (see *Outbound TLS Verification*)
- **Never accept cookie/session-authenticated state-changing requests without CSRF defense** (see *Cross-Site Request Forgery (CSRF)*)
- **Never expose stack traces** or internal errors to clients

## OWASP Top 10 Prevention

### 1. Injection (SQL / Command)

```python
# BAD — string-built SQL
stmt = text(f"SELECT * FROM users WHERE email = '{email}'")

# GOOD — ORM with bound params, async
stmt = select(User).where(User.email == email.lower())
result = await db.execute(stmt)
user = result.scalar_one_or_none()
```

```javascript
// BAD — string-built query (example for SQL-like ORMs)
const query = `SELECT * FROM users WHERE email = '${email}'`;

// GOOD — parameterized query
const user = await db.query('SELECT * FROM users WHERE email = $1', [email]);
```

### 2. Broken Authentication

```python
# Password hashing — argon2id
from argon2 import PasswordHasher

_ph = PasswordHasher()  # argon2id defaults

def hash_password(password: str) -> str:
    return _ph.hash(password)

def verify_password(password: str, password_hash: str) -> bool:
    from argon2.exceptions import VerifyMismatchError
    try:
        return _ph.verify(password_hash, password)
    except VerifyMismatchError:
        return False

# Session cookie (set on login) — flags from settings
response.set_cookie(
    key=settings.SESSION_COOKIE_NAME,
    value=session_id,
    httponly=True,
    samesite="lax",
    secure=not settings.DEBUG,      # Secure in production
    max_age=settings.SESSION_TTL_SECONDS,
)
```

### 3. Cross-Site Scripting (XSS) — frontend

```tsx
// BAD — renders user input as HTML
<div dangerouslySetInnerHTML={{ __html: userInput }} />

// GOOD — framework auto-escapes by default (React, Vue, Angular)
<div>{userInput}</div>

// If you MUST render HTML, sanitize first
import DOMPurify from "dompurify";
<div dangerouslySetInnerHTML={{ __html: DOMPurify.sanitize(userInput) }} />
```

### 4. Broken Access Control — authn + authz + tenant isolation

```python
@router.patch("/v1/tasks/{task_id}", response_model=TaskRead)
async def update_task(
    task_id: uuid.UUID,
    payload: TaskUpdate,
    current_user: User = Depends(require_auth),          # authenticated
    db: AsyncSession = Depends(get_db_session),
) -> TaskRead:
    # Tenant isolation: scope the lookup to the caller's org — never just by id
    stmt = select(Task).where(
        Task.id == task_id,
        Task.organization_id == current_user.organization_id,
    )
    task = (await db.execute(stmt)).scalar_one_or_none()
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "task not found")
    ...
```

```javascript
// Example for Node.js / Express-style backend
app.patch('/v1/tasks/:taskId', authenticate, async (req, res) => {
    const task = await db.tasks.findOne({
        id: req.params.taskId,
        organizationId: req.user.organizationId  // tenant scoping
    });
    if (!task) {
        return res.status(404).json({ error: 'task not found' });
    }
    ...
});
```

### 5. Security Misconfiguration

```python
# CORS — allowlist from settings, never "*" with credentials
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,   # e.g. ["http://localhost:3000"]
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Security headers (middleware)
response.headers["X-Content-Type-Options"] = "nosniff"
response.headers["X-Frame-Options"] = "DENY"
response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
# Strict-Transport-Security + Content-Security-Policy at the edge / in prod
```

### 6. Sensitive Data Exposure

```python
# Never expose password_hash / tokens — separate Read schema
class UserRead(UserBase):
    id: uuid.UUID
    organization_id: uuid.UUID
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)
    # password_hash deliberately absent

# Secrets only via environment or settings framework
from config.settings import settings
key = settings.SECRET_KEY   # never hardcoded
```

### 7. Cross-Site Request Forgery (CSRF)

CSRF applies to **cookie/session-authenticated** flows: the browser attaches the session cookie
automatically, so a malicious page can trigger a state-changing request on the user's behalf. Token-auth
APIs (Authorization header, read from JS) are not classically vulnerable — but anything that authenticates
via a cookie is.

`SameSite` cookies are a **partial** mitigation, not a complete one: `SameSite=Lax`/`Strict` helps, but
`SameSite=None` (required for legitimate cross-site/embedded use) re-opens the door, and `Lax` still
allows top-level GET navigations. For cookie/session flows, add an explicit anti-CSRF token.

```python
import secrets
# Synchronizer-token / double-submit-cookie pattern
# 1. Generate a cryptographically secure token (128+ bits), then expose it to the SPA in a
#    readable (non-HttpOnly) cookie or via a bootstrap endpoint.
token = secrets.token_hex(16)   # 32 hex chars = 128 bits, from a CSPRNG (never random/uuid4)
response.set_cookie("csrf_token", token, samesite="lax", secure=not settings.DEBUG)  # readable by JS

# 2. Require it back as a header on every state-changing request and compare (constant-time).
import hmac
async def require_csrf(request: Request) -> None:
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return                                            # safe methods are exempt
    cookie_tok = request.cookies.get("csrf_token", "")
    header_tok = request.headers.get("x-csrf-token", "")
    if not cookie_tok or not hmac.compare_digest(cookie_tok, header_tok):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "CSRF token missing or invalid")
```

```tsx
// Frontend: read the cookie and echo it as a header on mutations
const csrf = document.cookie.split("; ").find(c => c.startsWith("csrf_token="))?.split("=")[1];
const body = JSON.stringify({ /* ...your payload... */ });
await fetch("/v1/orders", { method: "POST", credentials: "include",
  headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf ?? "" }, body });
```

- Exempt only safe (read-only) methods; protect every cookie-authenticated POST/PUT/PATCH/DELETE.
- Combine with `SameSite` cookies (defense in depth) — don't rely on either alone.
- For GraphQL over cookies, a CSRF token (or an enforced preflight requirement) is still required —
  see `graphql-patterns`.

### 8. Outbound TLS Verification (don't disable it)

Disabling certificate verification on an outbound call turns HTTPS into "encrypted but unauthenticated" —
an active MITM can present any certificate and intercept or alter the traffic, including credentials and
tokens. This is **never** acceptable in app or CI code.

```python
# BAD — verification disabled (silently accepts any cert / MITM)
httpx.AsyncClient(verify=False)
requests.get(url, verify=False)

# GOOD — verify is on by default; for a private/internal CA, point at its bundle, don't disable
httpx.AsyncClient(verify="/etc/ssl/certs/internal-ca.pem")   # or REQUESTS_CA_BUNDLE / SSL_CERT_FILE env
httpx.AsyncClient()                                          # public CAs: defaults are correct
```

```javascript
// BAD — disables verification process-wide or per-agent
process.env.NODE_TLS_REJECT_UNAUTHORIZED = "0";
new https.Agent({ rejectUnauthorized: false });

// GOOD — keep verification on; supply the internal CA when needed
new https.Agent({ ca: fs.readFileSync("/etc/ssl/certs/internal-ca.pem") });
```

- **Self-signed dev certs:** add the CA to the trust store (or pass its bundle), never flip verification off.
- **Scripts/CI:** no `curl -k` / `wget --no-check-certificate` against endpoints you control — fix the cert.
- If a third party genuinely forces it, isolate that one client, document a **risk acceptance** (what /
  why / who / review date), and never make it the global default (`NODE_TLS_REJECT_UNAUTHORIZED=0` and
  `_tls_no_verify`-style flags disable verification for the **whole process**).

## Input Validation Patterns

### Schema Validation at Boundaries

Use the project's schema validation framework (e.g., Pydantic for Python, Zod/Yup for TypeScript, JSR-303 for Java):

```python
# Python example
from pydantic import BaseModel, EmailStr, Field, field_validator

class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=12, max_length=128)
    first_name: str = Field(min_length=1, max_length=100)

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        if not any(c.isupper() for c in v):
            raise ValueError("must contain an uppercase letter")
        if not any(c.isdigit() for c in v):
            raise ValueError("must contain a digit")
        return v
# The framework returns 422 automatically on validation failure.
```

```typescript
// TypeScript example with Zod
import { z } from 'zod';

const UserCreateSchema = z.object({
  email: z.string().email(),
  password: z.string().min(12).max(128).refine(
    (val) => /[A-Z]/.test(val) && /[0-9]/.test(val),
    { message: "must contain uppercase letter and digit" }
  ),
  firstName: z.string().min(1).max(100),
});
```

### File Upload Safety

```python
ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp"}
MAX_SIZE = 5 * 1024 * 1024  # 5 MB

def validate_upload(content_type: str, size: int) -> None:
    if content_type not in ALLOWED_TYPES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "file type not allowed")
    if size > MAX_SIZE:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "file too large (max 5MB)")
    # Don't trust the extension — verify magic bytes if it matters
```

## Triaging Dependency Audit Results

Not every finding is an emergency. Decision tree:

```
Vulnerability reported (dependency audit)
├── Severity: critical or high
│   ├── Is the vulnerable code path reachable in your app?
│   │   ├── YES --> Fix immediately (upgrade / patch / replace)
│   │   └── NO (dev-only dep, unused path) --> Fix soon, not a release blocker
│   └── Is a fix available?
│       ├── YES --> Upgrade to the patched version (flag major bumps as breaking)
│       └── NO --> Workaround, replace the dep, or allowlist with a review date
├── Severity: moderate
│   ├── Reachable in prod? --> Fix next release cycle
│   └── Dev-only? --> Track in backlog
└── Severity: low --> Fix during regular dependency updates
```

Editing dependency manifests requires user approval — the `dependency-scanner` recommends, the developer lane applies. Document any deferral with a reason and a review date.

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

### Input guardrails (before the prompt reaches the model)
- **Prompt-injection / jailbreak screening** — treat retrieved docs, tool results, and user text as
  data, never instructions; screen for "ignore previous instructions" / embedded commands before
  sending. (Pairs with `agent-guardrails.md` §1.)
- **Secrets scan** — never forward API keys, credentials, or internal tokens into a prompt.
- **PII anonymisation (vault pattern)** — mask PII (names, emails, cards) *before* the model sees it
  and restore it on the way out via the same vault, so the provider never receives raw PII.
- **Token / length budget** — cap input size to bound cost and prevent model-DoS.
- **Topic / content limits** — block disallowed topics or substrings where policy requires.
- **Canonicalise** — strip zero-width / invisible / homoglyph unicode used to smuggle instructions.

### Output guardrails (before the app uses the response)
- **Treat output as UNTRUSTED.** Never `eval`/`exec` it, render it as raw HTML, build SQL/shell from
  it, or auto-execute the tool/function calls it requests **without validation**. This is the existing
  no-eval-of-untrusted-data rule (OWASP A08) applied to model output — it stays a **Critical** at the
  security gate.
- **Leak scan** — check the response for leaked secrets/PII (de-anonymise via the vault).
- **URL / SSRF check** — validate any URL the model emits against an allowlist before fetching or
  showing it; block internal/private ranges.
- **Structured-output validation** — when you expect JSON/a schema, validate it; reject or repair on
  mismatch rather than trusting the shape.
- **Use-case checks** — relevance, refusal, toxicity/bias as your product requires.

### Least privilege for model-invoked tools
If the model can call tools/functions, give it the **minimum** set, require confirmation for
destructive/outward-facing actions, and scope credentials narrowly (mirrors `agent-guardrails.md` §3).

### OWASP LLM Top 10 — quick map
| Risk | Guardrail above |
|------|-----------------|
| LLM01 Prompt injection | input: injection screening; treat retrieved/tool content as data |
| LLM02 Insecure output handling | output: never eval / render-raw / auto-run unvalidated output |
| LLM04 Model DoS | input: token/length budget + rate limits |
| LLM06 Sensitive info disclosure | input PII vault + output leak scan; don't send secrets |
| LLM08 Excessive agency | least-privilege tools + human confirm for destructive actions |

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
