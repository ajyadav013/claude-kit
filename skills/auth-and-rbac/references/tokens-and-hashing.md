# Tokens and Hashing

Password hashing, JWT token operations, and multi-factor authentication patterns.

## Password Hashing with argon2id

### Async Thread Pool Wrapper

Argon2 is CPU-intensive; must run in thread pool to avoid blocking the event loop.

```python
# Example pattern from production FastAPI service

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
import asyncio

# Initialize once at module level
ph = PasswordHasher(
    time_cost=3,         # Number of iterations
    memory_cost=65536,   # Memory in KiB (64 MiB)
    parallelism=4,       # Number of parallel threads
    hash_len=32,         # Output hash length
    salt_len=16,         # Salt length
)

async def hash_password(password: str) -> str:
    """Hash a password with argon2id in a background thread."""
    return await asyncio.to_thread(ph.hash, password)

async def verify_password(password: str, password_hash: str) -> bool:
    """Verify a password against an argon2id hash in a background thread."""
    try:
        return await asyncio.to_thread(ph.verify, password_hash, password)
    except VerifyMismatchError:
        return False

async def check_needs_rehash(password_hash: str) -> bool:
    """Check if a hash needs to be rehashed with current parameters."""
    return await asyncio.to_thread(ph.check_needs_rehash, password_hash)
```

**Key points:**
- `asyncio.to_thread()` runs blocking operation in thread pool executor
- Single global `PasswordHasher` instance (thread-safe)
- `verify` throws `VerifyMismatchError` on mismatch; catch and return False
- `check_needs_rehash` detects if params have changed (for automatic upgrades on login)

### Password Rotation Tracking

Prevent password reuse by storing hash history.

```python
# Example pattern from production password policy implementation

# Migration: create password_history table
CREATE TABLE password_history (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    password_hash TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    INDEX idx_user_created (user_id, created_at DESC)
);

async def record_password_change(session: AsyncSession, user_id: UUID, password_hash: str) -> None:
    """Record a password hash in history."""
    history = PasswordHistory(user_id=user_id, password_hash=password_hash)
    session.add(history)
    await session.flush()

async def check_password_reuse(
    session: AsyncSession, 
    user_id: UUID, 
    new_password: str
) -> bool:
    """Check if new password matches any of the last N passwords.
    
    Returns True if password is reused (disallowed).
    """
    stmt = (
        select(PasswordHistory.password_hash)
        .where(PasswordHistory.user_id == user_id)
        .order_by(PasswordHistory.created_at.desc())
        .limit(settings.PASSWORD_HISTORY_COUNT)  # e.g., 5
    )
    result = await session.execute(stmt)
    past_hashes = [row[0] for row in result]
    
    for old_hash in past_hashes:
        if await verify_password(new_password, old_hash):
            return True  # Reused
    return False  # Not reused
```

**Usage in password change flow:**
```python
# Example pattern from production password reset flow

if settings.PASSWORD_ROTATION_ENABLED:
    reused = await check_password_reuse(self.session, user.id, new_password)
    if reused:
        raise HTTPException(
            status_code=HTTP_400_BAD_REQUEST,
            detail="Cannot reuse a recent password",
        )

new_hash = await hash_password(new_password)
await self.user_dao.update_user(user.id, {"password_hash": new_hash, "password_changed_at": datetime.now(timezone.utc)})

if settings.PASSWORD_ROTATION_ENABLED:
    await record_password_change(self.session, user.id, new_hash)
```

## JWT RS256 Tokens

### Token Issuance

Generate signed access token + opaque refresh token.

```python
# Example pattern from production JWT token service

import jwt as pyjwt
from datetime import datetime, timedelta, timezone
from app.common.encryption import decrypt_value

async def create_token_pair(self, user: User) -> TokenResponse:
    """Create access token (RS256 JWT) + refresh token (opaque UUID)."""
    
    # Fetch active signing key from DB
    signing_key = await self.key_dao.get_active_key()
    if not signing_key:
        raise HTTPException(status_code=HTTP_500_INTERNAL_SERVER_ERROR, detail="No signing key available")
    
    # Build JWT payload
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user.id),
        "email": user.email,
        "role": user.role,
        "organization_id": str(user.organization_id) if user.organization_id else None,
        "exp": now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),  # 15 minutes
        "iat": now,
        "iss": settings.JWT_ISSUER,
        "aud": settings.JWT_AUDIENCE,
    }
    
    # Decrypt private key (stored encrypted in DB)
    private_key_pem = decrypt_value(signing_key.private_key)
    
    # Sign with RS256
    access_token = pyjwt.encode(
        payload,
        private_key_pem,
        algorithm="RS256",
        headers={"kid": str(signing_key.id)},  # Key ID for JWKS lookup
    )
    
    # Create opaque refresh token
    refresh_token = str(uuid.uuid4())
    refresh_data = {
        "user_id": str(user.id),
        "issued_at": now.isoformat(),
    }
    await self.redis.set(
        f"refresh_token:{refresh_token}",
        orjson.dumps(refresh_data).decode(),
        ex=settings.REFRESH_TOKEN_EXPIRE_SECONDS,  # 7 days
    )
    
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )
```

**Key points:**
- Private key stored encrypted in `jwt_signing_keys` table, decrypted on use
- `kid` (Key ID) in JWT header allows key rotation (multiple active keys)
- Refresh token is opaque UUID in Redis, not a JWT
- Access token short-lived (15 min), refresh token long-lived (7 days)

### Token Verification

Decode and validate JWT access token.

```python
# Example pattern from production JWT token service

async def verify_access_token(self, token: str) -> dict[str, object]:
    """Decode and validate a JWT access token.
    
    Checks signature, expiry, issuer, audience.
    """
    try:
        # Extract kid from header without verifying signature
        unverified_header = pyjwt.get_unverified_header(token)
    except pyjwt.exceptions.DecodeError:
        raise HTTPException(status_code=HTTP_401_UNAUTHORIZED, detail="invalid_token")
    
    kid = unverified_header.get("kid")
    if not kid:
        raise HTTPException(status_code=HTTP_401_UNAUTHORIZED, detail="missing_kid")
    
    # Fetch signing key by kid
    signing_key = await self.key_dao.get_by_id(uuid.UUID(kid))
    if not signing_key:
        raise HTTPException(status_code=HTTP_401_UNAUTHORIZED, detail="unknown_signing_key")
    
    try:
        # Verify signature and decode
        payload = pyjwt.decode(
            token,
            signing_key.public_key,
            algorithms=["RS256"],
            audience=settings.JWT_AUDIENCE,
            issuer=settings.JWT_ISSUER,
        )
    except pyjwt.ExpiredSignatureError:
        raise HTTPException(status_code=HTTP_401_UNAUTHORIZED, detail="token_expired")
    except pyjwt.InvalidAudienceError:
        raise HTTPException(status_code=HTTP_401_UNAUTHORIZED, detail="invalid_audience")
    except pyjwt.InvalidIssuerError:
        raise HTTPException(status_code=HTTP_401_UNAUTHORIZED, detail="invalid_issuer")
    except pyjwt.InvalidSignatureError:
        raise HTTPException(status_code=HTTP_401_UNAUTHORIZED, detail="invalid_signature")
    except Exception:
        raise HTTPException(status_code=HTTP_401_UNAUTHORIZED, detail="invalid_token")
    
    return payload
```

**Key points:**
- Must extract `kid` first (unverified) to know which key to use
- Public key stored in DB as PEM string
- PyJWT validates signature, expiry, issuer, audience automatically
- Returns decoded payload dict with user claims

### Refresh Token Flow

```python
# Example pattern from production JWT token service

async def refresh_tokens(self, refresh_token: str) -> TokenResponse:
    """Validate a refresh token and issue a new token pair.
    
    The old refresh token is deleted (rotated) to prevent reuse.
    """
    key = f"refresh_token:{refresh_token}"
    raw = await self.redis.get(key)
    if not raw:
        raise HTTPException(status_code=HTTP_401_UNAUTHORIZED, detail="invalid_refresh_token")
    
    data = orjson.loads(raw)
    user_id = data.get("user_id")
    user = await self.user_dao.get_by_id(user_id)
    if not user or not user.active:
        await self.redis.delete(key)
        raise HTTPException(status_code=HTTP_401_UNAUTHORIZED, detail="invalid_refresh_token")
    
    # Delete old refresh token (rotation)
    await self.redis.delete(key)
    
    logger.info("auth.jwt.refreshed", user_id=str(user.id))
    return await self.create_token_pair(user)  # Issue new pair
```

**Key points:**
- Always validate user is still active before issuing new tokens
- Delete old refresh token immediately (single-use)
- Returns new access token + new refresh token (both rotated)

### JWKS Endpoint

```python
# Example pattern from production JWT token service

@router.get("/.well-known/jwks.json", response_model=JWKSResponse)
async def get_jwks(
    connection_handler: ConnectionHandler = Depends(get_connection_handler),
):
    """Public JWKS endpoint for token verification.
    
    Returns all active public keys as JWK Set.
    """
    helper = TokenHelper(connection_handler)
    keys = await helper.get_public_keys()
    jwks = {"keys": [k.model_dump(exclude_none=True) for k in keys]}
    return jwks

# JWK format:
{
  "keys": [
    {
      "kid": "a1b2c3d4-...",
      "kty": "RSA",
      "use": "sig",
      "alg": "RS256",
      "n": "base64-encoded-modulus...",
      "e": "AQAB"
    }
  ]
}
```

## Multi-Factor Authentication

### TOTP Setup with pyotp

```python
# Example pattern from production MFA implementation

import pyotp
import secrets

async def setup_totp(self, user_id: uuid.UUID) -> TOTPSetupResponse:
    """Generate a new TOTP secret and backup codes for enrolment."""
    user = await self.user_dao.get_by_id(user_id)
    if not user:
        raise HTTPException(status_code=HTTP_404_NOT_FOUND, detail="User not found")
    
    # Generate secret
    secret = pyotp.random_base32(length=32)
    
    # Generate backup codes
    backup_codes = [secrets.token_urlsafe(6) for _ in range(10)]  # 10 codes
    
    # Create QR code URI
    qr_uri = pyotp.totp.TOTP(secret).provisioning_uri(
        name=user.email,
        issuer_name="AppName",
    )
    
    # Store encrypted secret + hashed backup codes in DB
    enrollment = MFAEnrollment(
        user_id=user_id,
        mfa_type=MFAType.TOTP,
        secret=encrypt_value(secret),  # Encrypt secret at rest
        backup_codes=orjson.dumps([hashlib.sha256(code.encode()).hexdigest() for code in backup_codes]).decode(),
        verified=False,
    )
    self.session.add(enrollment)
    await self.session.flush()
    
    return TOTPSetupResponse(
        secret=secret,  # Show once
        qr_uri=qr_uri,  # Show once
        backup_codes=backup_codes,  # Show once
    )
```

**Key points:**
- Secret is 32-char base32 (256 bits of entropy)
- `provisioning_uri` generates `otpauth://totp/AppName:user@example.com?secret=...&issuer=AppName`
- Secret stored encrypted in DB
- Backup codes hashed with SHA-256 (one-way, verify by re-hashing)
- `verified=False` until user submits first code

### TOTP Verification

```python
# Example pattern from production MFA implementation

async def verify_totp_code(self, enrollment_id: uuid.UUID, code: str) -> bool:
    """Verify a TOTP code against an enrollment."""
    enrollment = await self.mfa_dao.get_by_id(enrollment_id)
    if not enrollment or enrollment.mfa_type != MFAType.TOTP:
        raise HTTPException(status_code=HTTP_404_NOT_FOUND, detail="Enrollment not found")
    
    secret = decrypt_value(enrollment.secret)
    totp = pyotp.TOTP(secret)
    
    # Verify with ±1 window (30s before, current, 30s after)
    if not totp.verify(code, valid_window=1):
        return False
    
    # Mark as verified on first successful verification
    if not enrollment.verified:
        enrollment.verified = True
        enrollment.verified_at = datetime.now(timezone.utc)
        await self.session.flush()
    
    return True
```

**Key points:**
- `valid_window=1` accepts codes from previous/current/next 30s window (tolerates clock drift)
- Enrollment marked `verified=True` on first successful code
- Returns boolean; caller decides whether to raise 401

### Email OTP

```python
# Example pattern from production MFA implementation (inferred pattern)

async def send_email_otp(self, user_id: uuid.UUID) -> None:
    """Generate and send 6-digit OTP via email."""
    # Check resend cooldown
    cooldown_key = f"email_otp_cooldown:{user_id}"
    if await self.redis.get(cooldown_key):
        raise HTTPException(status_code=HTTP_429_TOO_MANY_REQUESTS, detail="Wait before resending OTP")
    
    # Generate 6-digit code
    code = f"{secrets.randbelow(1000000):06d}"
    
    # Store in Redis with TTL and attempt counter
    otp_key = f"email_otp:{user_id}"
    await self.redis.set(
        otp_key,
        orjson.dumps({"code": code, "attempts": 0}).decode(),
        ex=300,  # 5 minutes
    )
    
    # Set resend cooldown
    await self.redis.set(cooldown_key, "1", ex=60)  # 60 seconds
    
    # Send email
    user = await self.user_dao.get_by_id(user_id)
    email_provider = get_email_provider()
    await email_provider.send_otp(user.email, code)

async def verify_email_otp(self, user_id: uuid.UUID, code: str) -> bool:
    """Verify email OTP and check attempt limit."""
    otp_key = f"email_otp:{user_id}"
    raw = await self.redis.get(otp_key)
    if not raw:
        raise HTTPException(status_code=HTTP_401_UNAUTHORIZED, detail="OTP expired or not found")
    
    data = orjson.loads(raw)
    stored_code = data["code"]
    attempts = data["attempts"]
    
    if attempts >= 3:
        await self.redis.delete(otp_key)
        raise HTTPException(status_code=HTTP_429_TOO_MANY_REQUESTS, detail="Too many attempts")
    
    if code != stored_code:
        # Increment attempts
        data["attempts"] += 1
        await self.redis.set(otp_key, orjson.dumps(data).decode(), ex=300, xx=True)
        return False
    
    # Success - delete OTP
    await self.redis.delete(otp_key)
    return True
```

**Key points:**
- 6-digit numeric code (000000-999999)
- TTL = 300s (5 minutes)
- Max 3 attempts per OTP
- Resend cooldown = 60s
- Deleted on successful verification or max attempts

### Backup Codes

```python
# Example pattern from production MFA implementation (inferred pattern)

def _generate_backup_codes() -> list[str]:
    """Generate 10 random 8-character alphanumeric backup codes."""
    return [secrets.token_urlsafe(6) for _ in range(10)]  # 8 chars each

async def verify_backup_code(self, enrollment_id: uuid.UUID, code: str) -> bool:
    """Verify a backup code (one-time use)."""
    enrollment = await self.mfa_dao.get_by_id(enrollment_id)
    if not enrollment:
        raise HTTPException(status_code=HTTP_404_NOT_FOUND, detail="Enrollment not found")
    
    # Backup codes stored as SHA-256 hashes
    stored_hashes = orjson.loads(enrollment.backup_codes)
    code_hash = hashlib.sha256(code.encode()).hexdigest()
    
    if code_hash not in stored_hashes:
        return False
    
    # Remove used code
    stored_hashes.remove(code_hash)
    enrollment.backup_codes = orjson.dumps(stored_hashes).decode()
    await self.session.flush()
    
    return True
```

**Key points:**
- Codes are URL-safe base64 (alphanumeric + `-_`)
- Stored as SHA-256 hashes (one-way)
- One-time use: removed from list on verification
- User should regenerate when running low

### MFA Enforcement Policy

```python
# Example pattern from production MFA implementation (check_mfa_enforcement excerpt)

async def check_mfa_enforcement(
    self, 
    user_id: uuid.UUID, 
    user_role: str, 
    organization_id: uuid.UUID | None
) -> bool:
    """Check if MFA is required for this user.
    
    Returns True if MFA enrollment is mandatory.
    """
    # Check organization-level policy
    if organization_id:
        org_policy = await self.get_org_mfa_policy(organization_id)
        if org_policy and org_policy.enforce_mfa:
            # Check if user's role is in required_roles
            if org_policy.required_roles and user_role in org_policy.required_roles:
                return True
            # Or if enforce_mfa applies to all roles
            if not org_policy.required_roles:
                return True
    
    # Check global policy
    if settings.GLOBAL_MFA_ENFORCEMENT:
        return True
    
    return False
```

**Usage in login flow:**
```python
# Example pattern from production login flow

enforcement = await mfa_helper.check_mfa_enforcement(user.id, user.role, user.organization_id)
active_enrollments = await mfa_dao.get_active_by_user(user.id)

if not active_enrollments and enforcement:
    # User has no MFA but policy requires it
    raise HTTPException(
        status_code=HTTP_403_FORBIDDEN,
        detail="MFA enrollment required. Please set up MFA before logging in.",
    )
```

**Key points:**
- Organization-level policies can enforce MFA for specific roles
- Global policy can enforce MFA for all users
- Blocks login if enforcement is active and user has no enrollments
- Admins should be required to enroll first
