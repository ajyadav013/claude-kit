# Example Patterns

Code examples illustrating authentication and RBAC conventions from production FastAPI services.

## Session-Based Auth Chain

### get_current_session

**Pattern:** Session extraction and validation

```python
async def get_current_session(
    request: Request,
    connection_handler: ConnectionHandler = Depends(get_connection_handler),
) -> dict[str, object]:
    """Extract and decrypt the session from the request cookie."""
    session_id = request.cookies.get(settings.SESSION_COOKIE_NAME)
    if not session_id:
        raise HTTPException(
            status_code=HTTP_401_UNAUTHORIZED, detail="Not authenticated"
        )

    raw_data = await connection_handler.redis.get(f"sess:{session_id}")
    if not raw_data:
        raise HTTPException(
            status_code=HTTP_401_UNAUTHORIZED, detail="Session expired or invalid"
        )

    from app.common.encryption import decrypt_value

    try:
        return orjson.loads(decrypt_value(raw_data))
    except Exception:
        try:
            return orjson.loads(raw_data)
        except Exception:
            await connection_handler.redis.delete(f"sess:{session_id}")
            raise HTTPException(
                status_code=HTTP_401_UNAUTHORIZED,
                detail="Session corrupt or invalid",
            )
```

### require_auth with fingerprint + request signature

**Pattern:** Session validation with security layers

```python
async def require_auth(
    request: Request,
    connection_handler: ConnectionHandler = Depends(get_connection_handler),
) -> dict[str, object]:
    """Validate the session and verify fingerprint and request signature."""
    session = await get_current_session(request, connection_handler)
    user = session.get("user")
    if not user:
        raise HTTPException(status_code=HTTP_401_UNAUTHORIZED, detail="Invalid session")

    stored_fp = session.get("_fingerprint")
    if stored_fp:
        from app.common.trusted_proxy import compute_session_fingerprint

        current_fp = compute_session_fingerprint(request)
        if current_fp != stored_fp:
            session_id = request.cookies.get(settings.SESSION_COOKIE_NAME)
            if session_id:
                await connection_handler.redis.delete(f"sess:{session_id}")
            raise HTTPException(
                status_code=HTTP_401_UNAUTHORIZED,
                detail="Session invalidated: client fingerprint mismatch",
            )

    public_key_jwk = session.get("_public_key")
    if public_key_jwk:
        sig = request.headers.get("x-request-signature")
        ts = request.headers.get("x-request-timestamp")
        if not sig or not ts:
            raise HTTPException(
                status_code=HTTP_401_UNAUTHORIZED,
                detail="Request signature required",
            )

        from app.common.request_signing import verify_request_signature

        body = await request.body()
        if not verify_request_signature(
            public_key_jwk, sig, request.method, request.url.path, body, ts
        ):
            # ... (delete session and raise 401)
```

### Role dependencies

**Pattern:** Role-based access control dependencies

```python
async def require_sys_admin(
    session: dict[str, object] = Depends(require_auth),
) -> dict[str, object]:
    """Require the caller to have the sys_admin role."""
    user = session.get("user", {})
    if user.get("role") != "sys_admin":
        raise HTTPException(
            status_code=HTTP_403_FORBIDDEN, detail="Sys admin access required"
        )
    return session


async def require_org_admin_or_above(
    session: dict[str, object] = Depends(require_auth),
) -> dict[str, object]:
    """Require the caller to be sys_admin or org_admin."""
    user = session.get("user", {})
    if user.get("role") not in ("sys_admin", "org_admin"):
        raise HTTPException(
            status_code=HTTP_403_FORBIDDEN, detail="Organization admin access required"
        )
    return session
```

## JWT Auth Chain

### get_current_user_jwt

**Pattern:** JWT-based authentication

```python
async def get_current_user_jwt(
    request: Request,
    connection_handler: ConnectionHandler = Depends(get_connection_handler),
) -> dict[str, object]:
    """Authenticate via JWT Authorization: Bearer header."""
    auth_header = request.headers.get("authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid Authorization header",
        )

    token = auth_header[7:]

    from app.identity.token.helpers import TokenHelper

    helper = TokenHelper(connection_handler)
    payload = await helper.verify_access_token(token)

    from app.identity.user.dao import UserDao

    user_dao = UserDao(connection_handler.session)
    user = await user_dao.get_by_id(payload["sub"])
    if not user or not user.active:
        raise HTTPException(
            status_code=HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
        )

    from app.identity.user.serializers import UserOut

    user_data = UserOut.model_validate(user).model_dump(mode="json")
    return {"user": user_data}
```

### JWT Verification

**Pattern:** Token verification with RS256

```python
async def verify_access_token(self, token: str) -> dict[str, object]:
    """Decode and validate a JWT access token."""
    try:
        unverified_header = pyjwt.get_unverified_header(token)
    except pyjwt.exceptions.DecodeError:
        raise HTTPException(
            status_code=HTTP_401_UNAUTHORIZED,
            detail="invalid_token",
        )

    kid = unverified_header.get("kid")
    if not kid:
        raise HTTPException(
            status_code=HTTP_401_UNAUTHORIZED,
            detail="missing_kid",
        )

    signing_key = await self.key_dao.get_by_id(uuid.UUID(kid))
    if not signing_key:
        raise HTTPException(
            status_code=HTTP_401_UNAUTHORIZED,
            detail="unknown_signing_key",
        )

    # ... (decode with pyjwt.decode, verify signature/expiry/issuer/audience)
```

## Password Hashing (argon2id)

**Pattern:** Async password hashing with argon2id

```python
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
import asyncio

ph = PasswordHasher(
    time_cost=3, memory_cost=65536, parallelism=4, hash_len=32, salt_len=16
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
```

**Usage in login:**

**Pattern:** Login flow with password verification

```python
async def login(self, email: str, password: str, ...):
    # ... (fetch user)
    
    if not user or not await verify_password(password, user.password_hash):
        await self.rate_limiter.record_failure(email)
        raise HTTPException(
            status_code=HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )
    
    # ... (check active, MFA, etc.)
```

## MFA with pyotp

### TOTP Setup

**Pattern:** TOTP enrollment with pyotp

```python
import pyotp

async def setup_totp(self, user_id: uuid.UUID) -> TOTPSetupResponse:
    """Generate a new TOTP secret and backup codes for enrolment."""
    user = await self.user_dao.get_by_id(user_id)
    if not user:
        raise HTTPException(status_code=HTTP_404_NOT_FOUND, detail="User not found")

    # ... (delete existing unverified enrollment)

    secret = pyotp.random_base32(length=32)
    backup_codes = _generate_backup_codes()
    qr_uri = pyotp.totp.TOTP(secret).provisioning_uri(
        name=user.email,
        issuer_name=_TOTP_ISSUER,
    )
    
    # ... (store encrypted secret in DB)
    
    return TOTPSetupResponse(secret=secret, qr_uri=qr_uri, backup_codes=backup_codes)
```

### TOTP Verification

**Pattern:** TOTP code verification

```python
async def verify_totp_enrollment(self, enrollment_id: uuid.UUID, code: str):
    # ... (fetch enrollment)
    
    secret = decrypt_value(enrollment.secret)
    totp = pyotp.TOTP(secret)
    if not totp.verify(code, valid_window=1):
        raise HTTPException(
            status_code=HTTP_401_UNAUTHORIZED, detail="Invalid TOTP code"
        )
    
    # ... (mark verified)
```

**Test example:**

**Pattern:** TOTP verification in tests

```python
import pyotp

# Test TOTP verification
totp = pyotp.TOTP(secret)
code = totp.now()
response = await client.post(
    f"/v1/mfa/totp/{enrollment_id}/verify",
    json={"code": code},
)
assert response.status_code == 200
```

## RBAC and Org Hierarchy

### Hierarchical Org Access Check

**Pattern:** Path-based hierarchical organization access control

```python
async def assert_org_access_async(
    session: dict,
    target_org_id: UUID,
    connection_handler: ConnectionHandler,
) -> None:
    """Async org access check with hierarchy support.
    
    - sys_admin: always passes
    - org_admin: target must be in the same root org tree (path prefix)
    - sub_org_admin: target must be in caller's subtree (path prefix)
    - tenant_admin / member: exact org_id match only
    """
    if is_sys_admin(session):
        return

    role = get_caller_role(session)
    caller_org_id = get_caller_org_id(session)

    if not caller_org_id:
        raise HTTPException(status_code=HTTP_403_FORBIDDEN, detail="Access denied")

    # For tenant_admin / member, no DB call needed -- exact match
    if role in ("tenant_admin", "member"):
        if caller_org_id != target_org_id:
            raise HTTPException(
                status_code=HTTP_403_FORBIDDEN,
                detail="Access denied to this organization",
            )
        return

    # For org_admin / sub_org_admin, fetch orgs and compare paths
    from app.identity.organization.dao import OrganizationDao

    dao = OrganizationDao(connection_handler.session)
    caller_org = await dao.get_by_id(caller_org_id)
    target_org = await dao.get_by_id(target_org_id)

    if not caller_org or not target_org:
        raise HTTPException(status_code=HTTP_403_FORBIDDEN, detail="Access denied")

    if role == "org_admin":
        # org_admin: target must share the same root path prefix
        root_path = _get_root_path(caller_org.path)
        if not target_org.path.startswith(root_path):
            raise HTTPException(status_code=HTTP_403_FORBIDDEN, detail="Access denied")
        return

    if role == "sub_org_admin":
        # sub_org_admin: target must be in caller's subtree
        if not target_org.path.startswith(caller_org.path):
            raise HTTPException(
                status_code=HTTP_404_NOT_FOUND, detail="Organization not found"
            )
        return

    raise HTTPException(status_code=HTTP_403_FORBIDDEN, detail="Access denied")
```

### Role Registration Restrictions

**Pattern:** Registration flow with role-based restrictions

```python
async def register(self, data: RegisterRequest, caller_session: dict | None = None, ...):
    # ... (check email uniqueness)

    role = getattr(data, "role", "member") or "member"
    org_id = getattr(data, "organization_id", None)

    if role in ("org_admin", "member") and not org_id:
        raise HTTPException(
            status_code=HTTP_400_BAD_REQUEST,
            detail="organization_id is required for org_admin and member roles",
        )

    privileged_roles = ("org_admin", "sub_org_admin", "tenant_admin")
    if role in privileged_roles and not caller_session:
        raise HTTPException(
            status_code=HTTP_403_FORBIDDEN,
            detail=f"Cannot self-register with role '{role}'; authentication required",
        )

    if role == "sys_admin" and caller_session:
        caller_role = caller_session.get("user", {}).get("role")
        if caller_role != "sys_admin":
            raise HTTPException(
                status_code=HTTP_403_FORBIDDEN,
                detail="Only sys admins can create sys admin users",
            )
    
    # ... (create user)
```

## API Gateway Identity Forwarding

**Pattern:** x-user-data header parsing

```python
def get_user_identity(request: Request) -> str:
    """Extract user email/name from the x-user-data JSON header.

    The gateway forwards this header on every authenticated request.
    Falls back to 'system' if the header is missing or unparseable.
    """
    header = request.headers.get("x-user-data")
    if not header:
        return "system"
    try:
        data = json.loads(header)
        return (
            data.get("email")
            or data.get("username")
            or data.get("userId")
            or "system"
        )
    except (json.JSONDecodeError, TypeError):
        logger.warning("Failed to parse x-user-data header")
        return "system"
```

**Usage in route:**

**Pattern:** Reading user identity from gateway header

```python
@router.get("/insights")
async def list_insights(
    request: Request,
    tenant: TenantContext = Depends(get_tenant),
):
    x_user_data = request.headers.get("x-user-data")
    if not x_user_data:
        raise ValueError("Missing x-user-data header")
    
    # ... (parse and use)
```

## Client-Side JWT Auth

**Pattern:** Client credential verification with database lookup

```python
from fastapi.security import OAuth2PasswordBearer
import jwt

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

async def verify_token(token: str):
    # Decode without verification to extract client_id
    unverified_payload = jwt.decode(token, options={"verify_signature": False})
    client_id: str = unverified_payload.get("sub")
    if client_id is None:
        raise HTTPException(...)

    # Fetch secret from DB
    connection_handler = ConnectionHandler()
    client_cred_service = ClientCredService(connection_handler=connection_handler)
    client_cred = await client_cred_service.fetch_client_cred_by_client_code(client_id)

    # Verify signature
    secret_key = client_cred.client_secret_key
    payload = jwt.decode(token, secret_key, algorithms=["HS256"])
    user_id: str = payload.get("sub")

    if user_id is None:
        raise HTTPException(...)

    return TokenData(client_id=client_id)

async def get_current_client(token: str = Depends(oauth2_scheme)):
    return await verify_token(token)
```

## Domain-Specific Role Enum

**Pattern:** Simple role enumeration for domain-specific access levels

```python
import enum

class Role(str, enum.Enum):
    L1 = "L1"
    L2 = "L2"


class Member(Base, CreatedatMixin, UpdatedatMixin, IsDeletedMixin):
    __tablename__ = "member"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, nullable=False)
    email = Column(String, nullable=False)
    name = Column(String, nullable=False)
    role = Column(String, nullable=False, default=Role.L1)

    __table_args__ = (UniqueConstraint("email", "role", name="uix_email_role"),)
```

## Summary

All patterns shown are extracted from production FastAPI services implementing comprehensive authentication and authorization. The examples illustrate session-based and JWT auth, argon2id password hashing, pyotp-based MFA, hierarchical RBAC, API gateway identity forwarding, and client credential verification.

All code snippets are illustrative patterns with sensitive details removed.
