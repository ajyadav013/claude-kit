# Authentication Dependencies

FastAPI dependency injection patterns for session-based and JWT authentication.

## Session-Based Auth Chain

### get_current_session

Extracts session ID from cookie, validates in Redis, decrypts payload.

```python
# Example pattern from production FastAPI service

async def get_current_session(
    request: Request,
    connection_handler: ConnectionHandler = Depends(get_connection_handler),
) -> dict[str, object]:
    """Extract and decrypt the session from the request cookie."""
    session_id = request.cookies.get(settings.SESSION_COOKIE_NAME)
    if not session_id:
        raise HTTPException(status_code=HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    
    raw_data = await connection_handler.redis.get(f"sess:{session_id}")
    if not raw_data:
        raise HTTPException(status_code=HTTP_401_UNAUTHORIZED, detail="Session expired or invalid")
    
    from app.common.encryption import decrypt_value
    try:
        return orjson.loads(decrypt_value(raw_data))
    except Exception:
        # Fallback for unencrypted legacy sessions
        try:
            return orjson.loads(raw_data)
        except Exception:
            await connection_handler.redis.delete(f"sess:{session_id}")
            raise HTTPException(status_code=HTTP_401_UNAUTHORIZED, detail="Session corrupt or invalid")
```

**Key points:**
- Session ID stored in HTTP-only cookie
- Session data stored in Redis as `sess:{session_id}`
- Encrypted at rest with Fernet, fallback to plaintext for legacy sessions
- Returns decrypted session dict containing `{"user": {...}, "_fingerprint": "...", "_public_key": {...}?}`

### require_auth

Validates session, verifies fingerprint, checks request signature if enabled.

```python
# Example pattern from production FastAPI service

async def require_auth(
    request: Request,
    connection_handler: ConnectionHandler = Depends(get_connection_handler),
) -> dict[str, object]:
    """Validate the session and verify fingerprint and request signature."""
    session = await get_current_session(request, connection_handler)
    user = session.get("user")
    if not user:
        raise HTTPException(status_code=HTTP_401_UNAUTHORIZED, detail="Invalid session")
    
    # Fingerprint validation (IP + User-Agent hash)
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
    
    # Request signature validation (optional ECDSA)
    public_key_jwk = session.get("_public_key")
    if public_key_jwk:
        sig = request.headers.get("x-request-signature")
        ts = request.headers.get("x-request-timestamp")
        if not sig or not ts:
            raise HTTPException(status_code=HTTP_401_UNAUTHORIZED, detail="Request signature required")
        
        from app.common.request_signing import verify_request_signature
        body = await request.body()
        if not verify_request_signature(public_key_jwk, sig, request.method, request.url.path, body, ts):
            session_id = request.cookies.get(settings.SESSION_COOKIE_NAME)
            if session_id:
                await connection_handler.redis.delete(f"sess:{session_id}")
            raise HTTPException(status_code=HTTP_401_UNAUTHORIZED, detail="Invalid request signature")
    
    return session
```

**Key points:**
- Fingerprint = hash of IP + User-Agent; prevents session hijacking
- Request signature = ECDSA signature over method|path|body|timestamp; prevents replay/tampering
- Both are optional security layers; fingerprint is common, request signing for high-security contexts
- Session deleted on mismatch to force re-authentication

### Role Dependencies

```python
# Example pattern from production FastAPI service

async def require_sys_admin(
    session: dict[str, object] = Depends(require_auth),
) -> dict[str, object]:
    """Require the caller to have the sys_admin role."""
    user = session.get("user", {})
    if user.get("role") != "sys_admin":
        raise HTTPException(status_code=HTTP_403_FORBIDDEN, detail="Sys admin access required")
    return session

async def require_org_admin_or_above(
    session: dict[str, object] = Depends(require_auth),
) -> dict[str, object]:
    """Require the caller to be sys_admin or org_admin."""
    user = session.get("user", {})
    if user.get("role") not in ("sys_admin", "org_admin"):
        raise HTTPException(status_code=HTTP_403_FORBIDDEN, detail="Organization admin access required")
    return session

async def require_sub_org_admin_or_above(
    session: dict = Depends(require_auth),
) -> dict:
    """Allow sys_admin, org_admin, or sub_org_admin."""
    user = session.get("user", {})
    if user.get("role") not in ("sys_admin", "org_admin", "sub_org_admin"):
        raise HTTPException(status_code=HTTP_403_FORBIDDEN, detail="Sub-org admin access required")
    return session
```

**Usage in routes:**
```python
@router.post("/admin/create-org")
async def create_org(
    data: CreateOrgRequest,
    session: dict = Depends(require_sys_admin),  # Enforces sys_admin role
):
    # Only sys_admins reach this point
    ...
```

## JWT Auth Chain

### get_current_user_jwt

Extracts JWT from Authorization header, verifies RS256 signature, loads user.

```python
# Example pattern from production FastAPI service

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
    payload = await helper.verify_access_token(token)  # RS256 verification + expiry check
    
    from app.identity.user.dao import UserDao
    user_dao = UserDao(connection_handler.session)
    user = await user_dao.get_by_id(payload["sub"])
    if not user or not user.active:
        raise HTTPException(status_code=HTTP_401_UNAUTHORIZED, detail="User not found or inactive")
    
    from app.identity.user.serializers import UserOut
    user_data = UserOut.model_validate(user).model_dump(mode="json")
    return {"user": user_data}  # Session-compatible shape
```

**Key points:**
- Returns same session shape as cookie-based auth → can use `Depends(require_sys_admin)` downstream
- Verifies signature with RS256 public key (fetched by `kid` from JWT header)
- Checks expiry, issuer, audience in `verify_access_token`
- Always fetches fresh user from DB to catch role changes / deactivations

## API Gateway Identity Forwarding

### x-user-data Header

Gateway forwards authenticated user as JSON header; backend parses for identity.

```python
# Example pattern from production API gateway integration

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

**Usage:**
```python
@router.put("/insights/{insight_id}")
async def update_insight(
    insight_id: str,
    data: InsightUpdate,
    user: str = Depends(get_user_identity),
):
    # user = email or username from gateway
    await log_audit(insight_id, user, "updated")
    ...
```

**Key points:**
- Gateway has already authenticated the user (via session/JWT/OAuth)
- Backend trusts the header (only works if gateway is on a private network)
- Falls back to "system" for background jobs / cron / service-to-service calls
- Read-only identity extraction; no re-verification

## Client-Side JWT Auth

### OAuth2PasswordBearer + DB Secret Lookup

For services that accept client credentials directly (no gateway).

```python
# Example pattern from production service-to-service auth

from fastapi.security import OAuth2PasswordBearer

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

async def verify_token(token: str):
    # Decode without verification to extract client_id
    unverified_payload = jwt.decode(token, options={"verify_signature": False})
    client_id: str = unverified_payload.get("sub")
    if client_id is None:
        raise HTTPException(status_code=HTTP_401_UNAUTHORIZED, detail="Could not validate credentials")
    
    # Fetch secret from DB (per-client secret)
    connection_handler = ConnectionHandler()
    client_cred_service = ClientCredService(connection_handler=connection_handler)
    client_cred = await client_cred_service.fetch_client_cred_by_client_code(client_id)
    
    # Verify signature with per-client secret
    payload = jwt.decode(token, client_cred.client_secret_key, algorithms=["HS256"])
    user_id: str = payload.get("sub")
    if user_id is None:
        raise HTTPException(status_code=HTTP_401_UNAUTHORIZED, detail="Could not validate credentials")
    
    return TokenData(client_id=client_id)

async def get_current_client(token: str = Depends(oauth2_scheme)):
    return await verify_token(token)
```

**Usage:**
```python
@router.post("/ingest")
async def ingest_data(
    data: IngestRequest,
    client: TokenData = Depends(get_current_client),
):
    # client.client_id is authenticated
    ...
```

**Key points:**
- Uses HS256 (symmetric) with per-client secrets stored in DB
- Each client has unique secret → token only valid for that client
- Must decode twice: once unverified to get client_id, then verified with fetched secret
- Suitable for service-to-service auth where each client is provisioned with unique credentials
