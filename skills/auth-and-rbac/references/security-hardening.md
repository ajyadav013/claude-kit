# Security Hardening Patterns

Additional security layers beyond core authentication and authorization.

## Login Rate Limiting

### Redis-Based Rate Limiter

Prevent brute-force attacks by tracking failed login attempts per email.

```python
# Example pattern from production rate limiting implementation

class LoginRateLimiter:
    """Redis-backed login rate limiter.
    
    Tracks failed login attempts per email. After MAX_FAILURES within
    WINDOW_SECONDS, the email is blocked for LOCKOUT_SECONDS.
    """
    
    MAX_FAILURES = 5
    WINDOW_SECONDS = 300  # 5 minutes
    LOCKOUT_SECONDS = 900  # 15 minutes
    
    def __init__(self, redis):
        self.redis = redis
    
    async def is_blocked(self, email: str) -> bool:
        """Check if email is currently blocked due to too many failures."""
        key = f"login_block:{email}"
        blocked = await self.redis.get(key)
        return bool(blocked)
    
    async def record_failure(self, email: str) -> None:
        """Record a failed login attempt."""
        key = f"login_failures:{email}"
        failures = await self.redis.incr(key)
        
        if failures == 1:
            # Set expiry on first failure
            await self.redis.expire(key, self.WINDOW_SECONDS)
        
        if failures >= self.MAX_FAILURES:
            # Block the email
            block_key = f"login_block:{email}"
            await self.redis.set(block_key, "1", ex=self.LOCKOUT_SECONDS)
    
    async def clear_failures(self, email: str) -> None:
        """Clear failure count after successful login."""
        await self.redis.delete(f"login_failures:{email}")
        await self.redis.delete(f"login_block:{email}")
```

**Usage in login flow:**
```python
# Example pattern from production login flow

# Check rate limit before attempting auth
if await self.rate_limiter.is_blocked(email):
    raise HTTPException(
        status_code=HTTP_429_TOO_MANY_REQUESTS,
        detail="Too many failed login attempts. Please try again later.",
    )

# ... (fetch user, verify password)

if not user or not await verify_password(password, user.password_hash):
    await self.rate_limiter.record_failure(email)
    raise HTTPException(
        status_code=HTTP_401_UNAUTHORIZED,
        detail="Invalid email or password",
    )

# Clear failures on successful login
await self.rate_limiter.clear_failures(email)
```

**Key points:**
- Uses Redis for distributed rate limiting (works across multiple app instances)
- Failure count expires after 5 minutes if threshold not reached
- Block duration is separate from failure window
- Always clear failures on successful login
- Return same error message for invalid email or password (don't leak email existence)

### Endpoint Rate Limiter

General-purpose rate limiter for API endpoints (registration, password reset, etc.).

```python
# Example pattern from production rate limiting implementation

class EndpointRateLimiter:
    """Rate limit arbitrary endpoints by IP or identifier."""
    
    def __init__(self, redis, max_requests: int = 10, window_seconds: int = 60):
        self.redis = redis
        self.max_requests = max_requests
        self.window_seconds = window_seconds
    
    async def check_and_increment(self, key: str) -> bool:
        """Check if rate limit is exceeded, then increment counter.
        
        Returns True if allowed, False if rate limit exceeded.
        """
        count = await self.redis.incr(key)
        if count == 1:
            await self.redis.expire(key, self.window_seconds)
        return count <= self.max_requests
```

**Usage as dependency:**
```python
# Example pattern from production registration endpoint

rate_limiter = EndpointRateLimiter(redis, max_requests=5, window_seconds=300)

@router.post("/register")
async def register(
    request: Request,
    data: RegisterRequest,
):
    # Rate limit by IP
    ip = request.client.host
    if not await rate_limiter.check_and_increment(f"register:{ip}"):
        raise HTTPException(
            status_code=HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many registration attempts. Please try again later.",
        )
    # ... (register user)
```

## Password Expiry

Force password rotation after a configurable period.

```python
# Example pattern from production password policy

async def is_password_expired(
    session: AsyncSession,
    user_id: UUID,
    password_changed_at: datetime | None,
) -> bool:
    """Check if user's password has expired.
    
    Returns True if the password is older than PASSWORD_MAX_AGE_DAYS.
    """
    if not settings.PASSWORD_EXPIRY_ENABLED:
        return False
    
    if not password_changed_at:
        # No password_changed_at record → assume expired
        return True
    
    age_days = (datetime.now(timezone.utc) - password_changed_at).days
    return age_days >= settings.PASSWORD_MAX_AGE_DAYS  # e.g., 90
```

**Usage in login flow:**
```python
# Example pattern from production login flow

password_expired = await is_password_expired(
    self.session, user.id, user.password_changed_at
)
if password_expired:
    await self.rate_limiter.clear_failures(email)
    # Return special response indicating password reset required
    return LoginResponse(
        password_expired=True,
        message="Your password has expired. Please reset it.",
    )

# ... (proceed with MFA / session creation)
```

**Key points:**
- Configurable via `PASSWORD_EXPIRY_ENABLED` and `PASSWORD_MAX_AGE_DAYS`
- Store `password_changed_at` timestamp on user table
- Update `password_changed_at` on password reset and change
- Clear rate limit failures to allow password reset flow
- Don't create session if password expired; require reset first

## Account Lockout

Temporarily or permanently lock accounts (admin action, suspicious activity, etc.).

```python
# Database field on User model
class User(Base):
    # ... (other fields)
    locked_until: datetime | None = None  # None = not locked, datetime = locked until
```

**Check during login:**
```python
# Example pattern from production login flow

if user.locked_until and user.locked_until > datetime.now(timezone.utc):
    raise HTTPException(
        status_code=HTTP_429_TOO_MANY_REQUESTS,
        detail="Account is temporarily locked. Try again later.",
    )
```

**Admin endpoint to lock/unlock:**
```python
@router.post("/admin/users/{user_id}/lock")
async def lock_user(
    user_id: UUID,
    data: LockUserRequest,
    session: dict = Depends(require_sys_admin),
):
    """Lock a user account until a specified time or indefinitely."""
    await user_dao.update_user(user_id, {
        "locked_until": data.locked_until,  # datetime or None to unlock
    })
    return {"message": "User account locked"}
```

**Key points:**
- `locked_until = None` → account not locked
- `locked_until = datetime` → locked until that time (temporary)
- `locked_until = datetime.max` → locked indefinitely (manual unlock required)
- Check happens early in login flow (before password verification)
- Admins can lock/unlock accounts via API

## Session Fingerprinting

Detect session hijacking by validating client fingerprint on every request.

```python
# Example pattern from production fingerprinting implementation

def compute_session_fingerprint(request: Request) -> str:
    """Compute a fingerprint from IP and User-Agent.
    
    Returns a stable hash that changes if IP or User-Agent changes.
    """
    ip = request.client.host
    # Handle X-Forwarded-For if behind proxy
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        ip = forwarded.split(",")[0].strip()
    
    user_agent = request.headers.get("user-agent", "")
    
    # Hash IP + UA
    fingerprint = hashlib.sha256(f"{ip}|{user_agent}".encode()).hexdigest()
    return fingerprint
```

**Store on session creation:**
```python
# Example pattern from production login flow

fingerprint = compute_session_fingerprint(request)
session_data = {
    "user": user_dict,
    "_fingerprint": fingerprint,
}
await redis.set(f"sess:{session_id}", encrypt_value(orjson.dumps(session_data)), ex=3600)
```

**Validate on every request (in require_auth dependency):**
```python
# Example pattern from production auth dependency

stored_fp = session.get("_fingerprint")
if stored_fp:
    current_fp = compute_session_fingerprint(request)
    if current_fp != stored_fp:
        # Fingerprint mismatch → delete session and reject
        await connection_handler.redis.delete(f"sess:{session_id}")
        raise HTTPException(
            status_code=HTTP_401_UNAUTHORIZED,
            detail="Session invalidated: client fingerprint mismatch",
        )
```

**Key points:**
- Fingerprint = hash(IP + User-Agent)
- Stored in session on creation
- Validated on every authenticated request
- Session deleted if mismatch (prevents hijacking)
- Works behind proxies (X-Forwarded-For support)
- Not bulletproof (shared IPs, NAT) but raises the bar significantly

## Request Signing with ECDSA

Optional high-security layer: client signs each request with ECDSA private key.

```python
# Example pattern from production request signing

def verify_request_signature(
    public_key_jwk: dict,
    signature_b64: str,
    method: str,
    path: str,
    body: bytes,
    timestamp: str,
) -> bool:
    """Verify ECDSA signature over request metadata.
    
    Args:
        public_key_jwk: Client's public key in JWK format (stored in session)
        signature_b64: Base64-encoded ECDSA signature
        method: HTTP method (GET, POST, etc.)
        path: Request path
        body: Raw request body bytes
        timestamp: ISO timestamp from x-request-timestamp header
    
    Returns:
        True if signature is valid and timestamp is recent.
    """
    # Check timestamp freshness (prevent replay)
    ts_dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    age = (datetime.now(timezone.utc) - ts_dt).total_seconds()
    if abs(age) > 60:  # Accept ±60s
        return False
    
    # Build signed message: method|path|body_hash|timestamp
    body_hash = hashlib.sha256(body).hexdigest()
    message = f"{method}|{path}|{body_hash}|{timestamp}"
    
    # Verify ECDSA signature
    # ... (ECDSA verification logic using public_key_jwk)
    
    return is_valid
```

**Usage (already shown in require_auth):**
```python
public_key_jwk = session.get("_public_key")
if public_key_jwk:
    sig = request.headers.get("x-request-signature")
    ts = request.headers.get("x-request-timestamp")
    if not sig or not ts:
        raise HTTPException(status_code=HTTP_401_UNAUTHORIZED, detail="Signature required")
    
    body = await request.body()
    if not verify_request_signature(public_key_jwk, sig, request.method, request.url.path, body, ts):
        # Delete session and reject
        await connection_handler.redis.delete(f"sess:{session_id}")
        raise HTTPException(status_code=HTTP_401_UNAUTHORIZED, detail="Invalid signature")
```

**Key points:**
- Client registers ECDSA public key during login/registration
- Public key stored in session (encrypted)
- Client signs `method|path|body_hash|timestamp` with private key
- Server verifies signature on every request
- Timestamp checked to prevent replay (±60s tolerance)
- Entirely optional; used for high-security contexts (financial, healthcare)
- Requires custom client SDK to handle signing

## Summary

These security hardening patterns complement the core auth-and-rbac conventions:

- **Login rate limiting** — Prevent brute-force attacks (Redis-backed, distributed)
- **Endpoint rate limiting** — Protect registration, password reset, etc.
- **Password expiry** — Force rotation after N days
- **Account lockout** — Admin-controlled temporary or permanent locks
- **Session fingerprinting** — Detect session hijacking via IP + User-Agent
- **Request signing (ECDSA)** — Optional high-security layer for tamper prevention

All patterns confirmed in production FastAPI services.
