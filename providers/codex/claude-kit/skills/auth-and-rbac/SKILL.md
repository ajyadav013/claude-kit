---
name: auth-and-rbac
description: FastAPI auth patterns — session/JWT chains, argon2id hashing, pyotp TOTP/Email OTP, role-based access control, x-user-data gateway forwarding. Use when building auth dependencies, MFA, or role hierarchies.
---

# Auth and RBAC

FastAPI authentication and authorization patterns derived from production identity services and multi-tenant backends.

## When to use

- Implementing session-based or JWT authentication in FastAPI
- Building role-based access control (RBAC) with hierarchical roles (sys_admin > org_admin > sub_org_admin > tenant_admin > member)
- Implementing multi-factor authentication (TOTP or Email OTP) with pyotp
- Designing auth dependency chains with `Depends(require_auth)` and role-specific guards
- Integrating with API gateways that forward identity via custom headers (x-user-data JSON)
- Hashing passwords with argon2id in async thread pool to avoid blocking the event loop
- Enforcing org/tenant access checks with materialized path hierarchies
- Issuing RS256 JWT tokens with key rotation and JWKS endpoint
- Implementing refresh token rotation for secure long-lived sessions
- Adding rate limiting to login endpoints to prevent brute-force attacks
- Enforcing password expiry policies and rotation tracking
- Implementing session fingerprinting to detect hijacking attempts

## Core conventions

### Authentication Dependency Chain

**Session-based auth chain**: `get_current_session` extracts session ID from cookie → validates in Redis → decrypts → `require_auth` verifies fingerprint + request signature → role dependencies (`require_sys_admin`, `require_org_admin_or_above`, `require_sub_org_admin_or_above`) enforce RBAC.

**JWT auth chain**: `get_current_user_jwt` extracts `Authorization: Bearer` header → decodes with PyJWT → verifies signature with RS256 public key → loads user from DB → returns session-shaped dict `{"user": {...}}` compatible with downstream dependencies.

**Helper extractors**: `get_caller_user_id(session)`, `get_caller_org_id(session)`, `get_caller_role(session)`, `is_sys_admin(session)` for inline role checks in endpoint logic.

**Fingerprint validation**: Store `_fingerprint` (IP + User-Agent hash) in session; on each request, recompute and compare — mismatch deletes session and returns 401.

**Request signing (optional)**: Store client ECDSA public key `_public_key` in session; require `x-request-signature` + `x-request-timestamp` headers; verify ECDSA signature over `method|path|body|timestamp`.

### Password Hashing (argon2id)

**Async hashing**: Use `argon2.PasswordHasher` with `time_cost=3, memory_cost=65536, parallelism=4, hash_len=32, salt_len=16`; wrap `ph.hash(password)` and `ph.verify(hash, password)` in `asyncio.to_thread()` to avoid blocking the event loop.

**Password rotation tracking**: Store hashed password history in `password_history` table; `check_password_reuse` queries the last N passwords and verifies new password doesn't match any via `verify_password`.

**Rehash check**: Call `ph.check_needs_rehash(hash)` on login; if params have changed, rehash and update DB.

### JWT Tokens (RS256)

**Token issuance**: Generate RS256 JWT with `pyjwt.encode(payload, private_key, algorithm='RS256', headers={'kid': key_id})`; include `sub` (user_id), `email`, `role`, `organization_id`, `exp`, `iat`, `iss`, `aud` in payload.

**Refresh tokens**: Issue opaque UUID refresh tokens; store `{user_id, issued_at}` in Redis `refresh_token:{uuid}` with expiry; on refresh, delete old token (rotation), validate user is still active, issue new pair.

**JWKS endpoint**: Expose `/.well-known/jwks.json` with active public keys as JWK Set; include `kid`, `kty`, `use`, `alg`, `n`, `e` for each key.

**Key rotation**: Store private keys encrypted at rest (Fernet); mark old keys as inactive; new tokens use latest active key; verification accepts any active key by `kid`.

**Token verification flow**: Extract `kid` from unverified header → fetch signing key from DB → decode with `pyjwt.decode(token, public_key, algorithms=['RS256'], audience=..., issuer=...)` → validate claims → check revocation (optional).

### MFA with pyotp

**TOTP setup**: Generate secret with `pyotp.random_base32(length=32)` → create QR URI with `pyotp.totp.TOTP(secret).provisioning_uri(name=user.email, issuer_name="AppName")` → return to client once.

**TOTP verification**: Verify code with `pyotp.TOTP(secret).verify(code, valid_window=1)` (accepts ±30s drift).

**Email OTP**: Generate 6-digit code, store in Redis `email_otp:{user_id}` with TTL=300s and attempt counter; verify code + attempt count; implement resend cooldown (60s).

**Backup codes**: Generate 10 random 8-char alphanumeric codes; hash each with SHA-256; store hashes; on use, verify one-time then mark as used.

**MFA enforcement**: Check org-level MFA policy table; if user role or org requires MFA and user has no active enrollments, block login with 403 and message "MFA enrollment required".

**MFA pending session**: On login with MFA, create temp `mfa_pending:{session_token}` in Redis (TTL=300s) with `{user_id, mfa_methods: ['TOTP', 'EMAIL_OTP'], type: 'mfa_pending'}` → return `{mfa_required: true, session_token, methods}` → client submits code → verify → upgrade to full session.

### Role-Based Access Control

**Role hierarchy**: `sys_admin` (platform superuser) > `org_admin` (org tree root admin) > `sub_org_admin` (subtree admin) > `tenant_admin` (single org/tenant) > `member` (read-only or limited scope).

**Role dependency pattern**: Create FastAPI dependencies that accept `session: dict = Depends(require_auth)` and check `session.get("user", {}).get("role")` — raise 403 if insufficient role.

**Hierarchical org access checks**: `assert_org_access_async(session, target_org_id, connection_handler)` — `sys_admin` always passes; `org_admin` checks root path prefix match; `sub_org_admin` checks subtree prefix match; `tenant_admin`/`member` require exact org_id match.

**Org path pattern**: Store org hierarchy as materialized path `/root/parent/child/`; admins can manage orgs in their subtree by path prefix comparison.

**Role enum**: Define `class Role(str, Enum): L1 = "L1"; L2 = "L2"; ADMIN = "ADMIN"` for domain-specific roles; store as string column with enum constraint.

### Choosing an authorization model & OAuth 2.0 delegation

Everything above assumes RBAC. That is usually right, but treat the authorization model as a decision, not a default — and know when to delegate identity to an external provider instead of owning credentials at all.

**The three models**:

- **RBAC (roles → permissions)** — users hold roles; roles bundle permission sets (admin = full CRUD, editor = read+write, member = read-only). Easiest to audit and administer; the right default for org/team products where a small, stable set of permission tiers answers most access questions.
- **ABAC (attribute predicates)** — decisions are policy functions over attributes of the subject, resource, and context: "the author may edit their own draft", "department matches", "within business hours", "resource not archived". Reach for it when access depends on ownership, tenancy, time, or resource state — conditions a static role cannot express. More expressive, harder to audit.
- **ACL (per-object grant lists)** — each resource carries its own principal→rights list, the document-sharing / filesystem model. The natural fit for sharing-centric products (docs, files, folders); maximally precise, but management cost scales with resources × users, so it needs tooling.

**Decision heuristics**:

- Permission tiers are few, stable, and org-wide → RBAC (this skill's role dependencies and hierarchy checks are exactly this).
- Rules keep referencing who owns the resource, which tenant it belongs to, what state it is in, or when the request happens → ABAC predicates alongside your roles.
- Users grant each other access object-by-object → ACL rows on those resources.

**The hybrid most systems actually run**: RBAC for coarse tiers plus ABAC-style ownership checks in business logic (`if resource.owner_id != caller_user_id and not is_sys_admin(session): 403`). Name it explicitly — "RBAC + ownership" — so reviewers treat both layers as intentional, and enforce it at every depth (route guard, service-level ownership check, query scoping to the caller's rows); relying on the route guard alone is the classic IDOR root cause.

**Migration pressure signals**:

- **Role explosion** — compound roles multiplying (`editor_finance_emea_readonly`) means your rules are really attribute predicates; move those conditions into ABAC checks instead of minting more roles.
- **Per-resource sharing requests** — users wanting to grant specific people access to specific objects cannot be expressed as a role tier; those objects need ACL entries.

**OAuth 2.0 authorization-code flow** — for social login ("Login with Google/GitHub") or calling a third-party API on the user's behalf:

1. Your app redirects the browser to the provider's authorization server (`client_id`, `redirect_uri`, requested scopes, `state`).
2. The user authenticates and consents at the provider — your system never sees their password.
3. The provider redirects back to your `redirect_uri` with a short-lived, single-use authorization code.
4. Your backend exchanges code + client secret for tokens in a server-to-server call.
5. Your backend verifies the returned identity, then links or creates the local user row.

**Why the code indirection**: browser redirects are observable (URLs land in history, proxies, logs, referrers), so nothing in a redirect may be a usable credential. An intercepted code is worthless without the client secret held server-side. Never use the legacy implicit flow, which returns the access token directly in the URL fragment.

**PKCE for public clients**: SPAs and mobile apps cannot hold a client secret; use authorization-code + PKCE, where a per-request code verifier/challenge pair replaces the secret in the exchange.

**Callback CSRF protection**: generate a random `state` value per authorization request, bind it to the initiating session, and reject any callback whose `state` does not match — otherwise an attacker can splice their own authorization code into a victim's login.

**What to persist**: the provider's stable subject identifier linked to your own user row (`provider` + `provider_subject_id` columns); match returning users on that pair, not on email, which can change or be reassigned at the provider.

**The provider's access token is not your session**: it is scoped to the provider's API, has a lifetime you do not control, and your services cannot validate it. After linking identity, issue your own session or JWT via the chains above; store the provider token (encrypted at rest) only if you actually call the provider's API on the user's behalf.

**Authentication vs delegation**: OAuth 2.0 by itself only delegates authorization — permission to call the provider's API. Logging users in is OpenID Connect's job: it layers a signed ID token of identity claims on the same code flow. For social login, request `openid email profile` scopes and verify the ID token (signature, `iss`, `aud`, `exp`, nonce) — never infer identity from mere possession of an access token.

**After identity is established**: nothing downstream changes — session creation, fingerprinting, refresh-token rotation, and the role dependencies all follow the session/JWT conventions earlier in this skill; the IdP only replaces the password-verification step.

**Trade-off to state in the design doc**: delegation sheds password-storage liability for those users but adds a hard dependency on the provider's availability and account policies; decide up front whether such accounts are IdP-only or may fall back to a local password.

### API Gateway User Identity Forwarding

**x-user-data header pattern**: API gateway extracts authenticated user from session/JWT, serializes `{email, username, userId, role?, organization_id?}` as JSON, forwards as `x-user-data` header to downstream services.

**Backend parsing**: Use FastAPI dependency `get_user_identity(request: Request)` that parses `request.headers.get("x-user-data")`, JSON-decodes, extracts `email` or `username` or `userId`, falls back to `"system"` if missing/malformed.

**Trust boundary**: Downstream services trust the gateway has already authenticated the user; header is read-only identity, not a re-verification token.

**Client-side auth**: For direct client-to-backend flows (no gateway), use OAuth2PasswordBearer + `Depends(get_current_client)` → `verify_token(token)` decodes JWT, extracts `client_id`, fetches secret from DB, verifies signature.

## Skeleton / example

```python
# Session-based auth chain
from fastapi import Depends, HTTPException, Request
from starlette.status import HTTP_401_UNAUTHORIZED, HTTP_403_FORBIDDEN

async def get_current_session(
    request: Request,
    connection_handler: ConnectionHandler = Depends(get_connection_handler),
) -> dict[str, object]:
    session_id = request.cookies.get(settings.SESSION_COOKIE_NAME)
    if not session_id:
        raise HTTPException(status_code=HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    raw_data = await connection_handler.redis.get(f"sess:{session_id}")
    if not raw_data:
        raise HTTPException(status_code=HTTP_401_UNAUTHORIZED, detail="Session expired")
    return orjson.loads(decrypt_value(raw_data))

async def require_auth(
    request: Request,
    connection_handler: ConnectionHandler = Depends(get_connection_handler),
) -> dict[str, object]:
    session = await get_current_session(request, connection_handler)
    # Fingerprint check
    stored_fp = session.get("_fingerprint")
    if stored_fp:
        current_fp = compute_session_fingerprint(request)
        if current_fp != stored_fp:
            await connection_handler.redis.delete(f"sess:{session_id}")
            raise HTTPException(status_code=HTTP_401_UNAUTHORIZED, detail="Fingerprint mismatch")
    # Request signature check (optional)
    public_key = session.get("_public_key")
    if public_key:
        sig = request.headers.get("x-request-signature")
        ts = request.headers.get("x-request-timestamp")
        if not sig or not ts:
            raise HTTPException(status_code=HTTP_401_UNAUTHORIZED, detail="Signature required")
        if not verify_request_signature(public_key, sig, request.method, request.url.path, body, ts):
            raise HTTPException(status_code=HTTP_401_UNAUTHORIZED, detail="Invalid signature")
    return session

async def require_sys_admin(
    session: dict = Depends(require_auth),
) -> dict:
    if session.get("user", {}).get("role") != "sys_admin":
        raise HTTPException(status_code=HTTP_403_FORBIDDEN, detail="Sys admin required")
    return session

# JWT auth chain
async def get_current_user_jwt(
    request: Request,
    connection_handler: ConnectionHandler = Depends(get_connection_handler),
) -> dict[str, object]:
    auth_header = request.headers.get("authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=HTTP_401_UNAUTHORIZED, detail="Missing Bearer token")
    token = auth_header[7:]
    payload = await token_helper.verify_access_token(token)  # RS256 verification
    user = await user_dao.get_by_id(payload["sub"])
    if not user or not user.active:
        raise HTTPException(status_code=HTTP_401_UNAUTHORIZED, detail="User inactive")
    return {"user": UserOut.model_validate(user).model_dump(mode="json")}

# Password hashing
from argon2 import PasswordHasher
import asyncio

ph = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4, hash_len=32, salt_len=16)

async def hash_password(password: str) -> str:
    return await asyncio.to_thread(ph.hash, password)

async def verify_password(password: str, password_hash: str) -> bool:
    try:
        return await asyncio.to_thread(ph.verify, password_hash, password)
    except VerifyMismatchError:
        return False

# JWT token issuance
import jwt as pyjwt
from datetime import datetime, timedelta, timezone

async def issue_tokens(user: User) -> TokenResponse:
    signing_key = await key_dao.get_active_key()
    payload = {
        "sub": str(user.id),
        "email": user.email,
        "role": user.role,
        "organization_id": str(user.organization_id) if user.organization_id else None,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=15),
        "iat": datetime.now(timezone.utc),
        "iss": settings.JWT_ISSUER,
        "aud": settings.JWT_AUDIENCE,
    }
    access_token = pyjwt.encode(
        payload,
        decrypt_value(signing_key.private_key),
        algorithm="RS256",
        headers={"kid": str(signing_key.id)},
    )
    refresh_token = str(uuid.uuid4())
    await redis.set(
        f"refresh_token:{refresh_token}",
        orjson.dumps({"user_id": str(user.id), "issued_at": datetime.now(timezone.utc).isoformat()}),
        ex=604800,  # 7 days
    )
    return TokenResponse(access_token=access_token, refresh_token=refresh_token, token_type="bearer")

# MFA TOTP setup
import pyotp

async def setup_totp(user_id: UUID) -> TOTPSetupResponse:
    secret = pyotp.random_base32(length=32)
    qr_uri = pyotp.totp.TOTP(secret).provisioning_uri(name=user.email, issuer_name="AppName")
    backup_codes = [secrets.token_urlsafe(6) for _ in range(10)]
    # Store encrypted secret + hashed backup codes in DB
    return TOTPSetupResponse(secret=secret, qr_uri=qr_uri, backup_codes=backup_codes)

async def verify_totp(secret: str, code: str) -> bool:
    totp = pyotp.TOTP(secret)
    return totp.verify(code, valid_window=1)

# Hierarchical org access
async def assert_org_access_async(
    session: dict,
    target_org_id: UUID,
    connection_handler: ConnectionHandler,
) -> None:
    if is_sys_admin(session):
        return
    role = get_caller_role(session)
    caller_org_id = get_caller_org_id(session)
    if role in ("tenant_admin", "member"):
        if caller_org_id != target_org_id:
            raise HTTPException(status_code=HTTP_403_FORBIDDEN, detail="Access denied")
        return
    caller_org = await org_dao.get_by_id(caller_org_id)
    target_org = await org_dao.get_by_id(target_org_id)
    if role == "org_admin":
        # Check root path prefix match
        root_path = _get_root_path(caller_org.path)
        if not target_org.path.startswith(root_path):
            raise HTTPException(status_code=HTTP_403_FORBIDDEN, detail="Access denied")
    elif role == "sub_org_admin":
        # Check subtree prefix match
        if not target_org.path.startswith(caller_org.path):
            raise HTTPException(status_code=HTTP_403_FORBIDDEN, detail="Access denied")

# API gateway identity forwarding
def get_user_identity(request: Request) -> str:
    """Extract user identity from x-user-data JSON header forwarded by gateway."""
    header = request.headers.get("x-user-data")
    if not header:
        return "system"
    try:
        data = json.loads(header)
        return data.get("email") or data.get("username") or data.get("userId") or "system"
    except (json.JSONDecodeError, TypeError):
        logger.warning("Failed to parse x-user-data header")
        return "system"

# Client-side JWT auth
from fastapi.security import OAuth2PasswordBearer

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

async def verify_token(token: str) -> TokenData:
    # Decode without verification to get client_id
    unverified = jwt.decode(token, options={"verify_signature": False})
    client_id = unverified.get("sub")
    # Fetch secret from DB
    client_cred = await client_cred_service.fetch_client_cred_by_client_code(client_id)
    # Verify signature
    payload = jwt.decode(token, client_cred.client_secret_key, algorithms=["HS256"])
    return TokenData(client_id=payload["sub"])

async def get_current_client(token: str = Depends(oauth2_scheme)) -> TokenData:
    return await verify_token(token)
```

## Anti-patterns to avoid

- **Blocking the event loop with sync argon2** — always wrap `ph.hash()` and `ph.verify()` in `asyncio.to_thread()`.
- **Using HS256 for multi-service JWT** — use RS256 with public/private keys; HS256 requires sharing secrets across services.
- **Storing plaintext TOTP secrets** — encrypt secrets at rest with Fernet or similar; decrypt only when needed.
- **Allowing MFA bypass for admins** — MFA should apply to privileged roles first; admins are higher-value targets.
- **Not rotating refresh tokens** — delete old refresh token when issuing a new pair to prevent reuse attacks.
- **Trusting x-user-data header from untrusted sources** — only accept this header from an authenticated API gateway on a private network; never expose endpoints with this pattern to the public internet.
- **Hardcoding role strings in business logic** — use helper functions (`is_sys_admin`, `get_caller_role`) or FastAPI dependencies for centralized role checks.
- **Forgetting to check user.active on token refresh** — always validate user is still active before issuing new tokens; prevents revoked users from refreshing.
- **Using JWT `kid` without validation** — always fetch signing key by `kid` and verify it exists before decoding; prevents key confusion attacks.
- **Mixing session-based and JWT auth in one endpoint** — pick one auth strategy per endpoint; use `get_current_user_jwt` OR `require_auth`, not both.
- **Skipping rate limiting on login endpoints** — implement Redis-backed login rate limiting to prevent brute-force attacks.
- **Not checking account lockout early** — verify `user.locked_until` before password verification to avoid timing leaks.
- **Returning different errors for "user not found" vs "wrong password"** — always return the same error message to avoid email enumeration.

## References

- [auth-dependencies.md](./references/auth-dependencies.md) — Session and JWT auth dependency chains
- [rbac-and-permissions.md](./references/rbac-and-permissions.md) — Role hierarchies, org access checks, RBAC patterns
- [tokens-and-hashing.md](./references/tokens-and-hashing.md) — JWT RS256, argon2id, TOTP/Email OTP with pyotp
- [security-hardening.md](./references/security-hardening.md) — Rate limiting, password expiry, account lockout, session fingerprinting
- [repo-evidence.md](./references/repo-evidence.md) — Real file paths and snippets from source repos
- [htn-design-an-authentication-system.md](./references/htn-design-an-authentication-system.md) · [htn-serialization-deserialization-authentication-and-authorizati.md](./references/htn-serialization-deserialization-authentication-and-authorizati.md) — Digested source articles behind the authz-model (RBAC/ABAC/ACL) and OAuth 2.0 delegation section
