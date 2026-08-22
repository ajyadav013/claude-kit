# OWASP Top 10 Prevention — code patterns

Deep-dive reference for the `security-and-hardening` skill. Loaded on demand from SKILL.md —
the one-rule-per-class summary and the review checklist live there.

## 1. Injection (SQL / Command)

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

**Secure-by-construction (defense in depth beyond "use parameters").** "Always parameterize" relies on
every developer remembering, every time — one string-built query slips through review and you have an
injection. The stronger discipline is to make the unsafe path *unrepresentable*: ban the raw
string-accepting API in app code (via lint/type rules) and route construction through types that are
**provably safe by construction**.

- **Compile-time-constant query text.** Require the static part of a query (the SQL/command template) to
  be a *compile-time constant* the developer wrote — never a runtime-assembled string. Untrusted values
  can then only enter as bound parameters, so a literal like `"... WHERE id = " + userInput` won't even
  compile/lint. (Where the language supports it, an annotation/type such as a "trusted constant string"
  enforces this.)
- **Typed trust wrappers.** Wrap values in distinct types that encode their trust — a `TrustedString`
  the API accepts vs. an `UntrustedString` it rejects at the boundary — so "this came from the user"
  is carried in the type, not in a comment, and the compiler/linter rejects mixing them.
- This generalizes past SQL to every injection sink: shell/command construction, file paths, HTML, and
  template rendering. The same idea underlies framework "safe HTML" / "trusted types" wrappers.

> Stack-agnostic adaptation of secure-by-construction injection defense (compile-time-constant query
> text + typed trusted/untrusted wrappers, banning the raw string API outright) from the Apache-2.0
> [`google/safe-active-record`](https://github.com/google/safe-active-record) and
> [`google/mug`](https://github.com/google/mug) (`SafeSql`/`@CompileTimeConstant`). Re-derived in prose;
> not vendored.

## 2. Broken Authentication

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

## 3. Cross-Site Scripting (XSS) — frontend

```tsx
// BAD — renders user input as HTML
<div dangerouslySetInnerHTML={{ __html: userInput }} />

// GOOD — framework auto-escapes by default (React, Vue, Angular)
<div>{userInput}</div>

// If you MUST render HTML, sanitize first
import DOMPurify from "dompurify";
<div dangerouslySetInnerHTML={{ __html: DOMPurify.sanitize(userInput) }} />
```

## 4. Broken Access Control — authn + authz + tenant isolation

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

## 5. Security Misconfiguration

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

## 6. Sensitive Data Exposure

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

## 7. Cross-Site Request Forgery (CSRF)

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

## 8. Outbound TLS Verification (don't disable it)

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

## Continuous Least-Privilege (usage-based permission pruning)

Granting least privilege *up front* is necessary but not sufficient — permissions only ever accrete.
Roles, scopes, service accounts, API keys, and DB grants get a permission "just in case," the feature
ships, and the grant is never removed. Over months every principal drifts toward over-privilege, and the
blast radius of a compromised credential grows silently. Least privilege is not a one-time grant; it's a
**decay loop** that tightens over time.

- **Audit what was actually used.** For each principal, collect which granted permissions/scopes/roles
  were *exercised* over a trailing window (e.g. 60–90 days) from access logs / "last used" telemetry /
  audit trails — not what was *requested*.
- **Revoke the unused past a threshold.** Permissions unused for the whole window are removed
  automatically (or proposed for removal in a review). Schedule it to run **periodically**, not once.
- **Keep a fast, auditable rollback.** Snapshot each policy *before* pruning and version the history, so
  a false positive (a permission used only quarterly, say) is re-granted in seconds with a clear audit
  trail. Without a cheap undo, no one will trust automated pruning.
- **Maintain an exempt-list.** Break-glass roles, rarely-but-critically-used grants, and
  compliance-mandated permissions are explicitly excluded from auto-pruning — pruning must never be able
  to lock out emergency access.
- **Stack-agnostic.** The loop (measure usage → remove unused → snapshot for rollback → repeat) applies
  to cloud IAM, OAuth scopes, Kubernetes RBAC, database grants, and application roles alike. Pair it with
  the up-front least-privilege defaults in *Broken Access Control* above; this is the ongoing complement.

> Stack-agnostic adaptation of continuous, usage-based least-privilege (audit exercised permissions over
> a trailing window → auto-revoke the unused → versioned snapshots for safe rollback → exempt-list) from
> the Apache-2.0 [`Netflix/repokid`](https://github.com/Netflix/repokid). Re-derived in prose; not
> vendored — the decay loop generalizes beyond AWS IAM to any grant/scope/role system.
