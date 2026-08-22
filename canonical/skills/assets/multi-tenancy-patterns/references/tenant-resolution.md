# Tenant Resolution

How to resolve the current tenant from request context across different input sources.

## Resolution Priority

The canonical resolution order from production services:

1. **`X-Tenant-ID` header** — explicit tenant override (used by admin tools, cross-tenant APIs)
2. **JWT claim `tenant_id`** — tenant scoped at token issuance (service-to-service auth)
3. **Session `active_tenant_id`** — user's currently selected tenant (web app session)

Return `None` if none of the sources yields a valid tenant ID.

## Implementation Pattern

```python
async def _resolve_tenant_id(
    request: Request,
    session: dict[str, object],
) -> tuple[UUID, str] | None:
    """Determine tenant_id from header, JWT, or session.
    
    Returns:
        Tuple of (tenant_id, resolution_method) or None if no
        tenant could be resolved.
    """
    # Priority 1: explicit header
    header_val = request.headers.get("X-Tenant-ID")
    if header_val:
        try:
            return UUID(header_val), "header"
        except ValueError:
            raise HTTPException(
                status_code=HTTP_400_BAD_REQUEST,
                detail="Invalid X-Tenant-ID header value",
            )

    # Priority 2: JWT claim
    if hasattr(request.state, "token_payload"):
        jwt_tid = request.state.token_payload.get("tenant_id")
        if jwt_tid:
            return UUID(str(jwt_tid)), "jwt"

    # Priority 3: session active_tenant_id
    user_data = session.get("user", {})
    active_tid = (
        user_data.get("active_tenant_id") if isinstance(user_data, dict) else None
    )
    if active_tid:
        return UUID(str(active_tid)), "session"

    return None
```

## Tenant Context Dataclass

After resolution, populate an immutable context object:

```python
@dataclass(frozen=True)
class TenantContext:
    tenant_id: UUID
    tenant_slug: str
    tenant_name: str
    lifecycle_state: str
    organization_id: UUID
    org_path: str             # Hierarchical path for org-admin access checks
    user_id: UUID
    platform_role: str        # "sys_admin" | "org_admin" | "tenant_admin" | "member"
    tenant_roles: list[str]   # Tenant-specific roles for the user
    resolved_via: str         # "header" | "jwt" | "session"
```

## FastAPI Dependency Injection

```python
async def get_tenant_context(
    request: Request,
    session: dict[str, object] = Depends(require_auth),
    connection_handler: ConnectionHandler = Depends(get_connection_handler),
) -> TenantContext:
    """Resolve and validate tenant context for the current request.
    
    Resolution priority: X-Tenant-ID header > JWT claim > session
    active_tenant_id. Validates that the tenant exists, is active,
    and the user has access.
    
    Raises:
        HTTPException: 400 if no tenant could be resolved.
        HTTPException: 403 if tenant is suspended or user lacks access.
        HTTPException: 404 if tenant does not exist or is deleted.
    """
    result = await _resolve_tenant_id(request, session)
    if result is None:
        raise HTTPException(
            status_code=HTTP_400_BAD_REQUEST,
            detail="Tenant context required but not resolved",
        )

    tenant_id, resolved_via = result

    # Fetch tenant from DB
    tenant = await db.execute(
        select(Tenant).where(Tenant.id == tenant_id, Tenant.is_deleted.is_(False))
    ).scalar_one_or_none()

    if tenant is None:
        raise HTTPException(status_code=HTTP_404_NOT_FOUND, detail="Tenant not found")

    # Check lifecycle state
    if tenant.lifecycle_state == "suspended":
        raise HTTPException(
            status_code=HTTP_403_FORBIDDEN,
            detail=f"Tenant is suspended: {tenant.lifecycle_reason}",
        )
    if tenant.lifecycle_state not in ("active", "provisioning"):
        raise HTTPException(
            status_code=HTTP_403_FORBIDDEN,
            detail=f"Tenant is not accessible (state: {tenant.lifecycle_state})",
        )

    # Validate user access (see access checks below)
    # ...

    # Set RLS context
    if tenant.schema_name:
        await connection_handler.set_schema_context(tenant.schema_name)
    else:
        await connection_handler.set_tenant_context(tenant_id)

    return TenantContext(
        tenant_id=tenant.id,
        tenant_slug=tenant.slug,
        # ... populate other fields
        resolved_via=resolved_via,
    )
```

## Access Checks

After resolving the tenant, validate that the user has permission to access it:

### sys_admin

Platform super-admin. Can access all tenants. No checks needed.

### org_admin

Manages an entire organization tree. Validate that the tenant's org path starts with the admin's org root:

```python
if user_role == "org_admin":
    caller_org = await org_dao.get_by_id(user_data.get("organization_id"))
    tenant_org = await org_dao.get_by_id(tenant.organization_id)
    
    root = caller_org.path.strip("/").split("/")[0]
    root_path = f"/{root}/"
    if not tenant_org.path.startswith(root_path):
        raise HTTPException(
            status_code=HTTP_403_FORBIDDEN,
            detail="You do not have access to this tenant",
        )
```

### sub_org_admin

Manages a sub-organization. Validate that the tenant's org path starts with the admin's org path:

```python
if user_role == "sub_org_admin":
    caller_org = await org_dao.get_by_id(user_data.get("organization_id"))
    tenant_org = await org_dao.get_by_id(tenant.organization_id)
    
    if not tenant_org.path.startswith(caller_org.path):
        raise HTTPException(
            status_code=HTTP_403_FORBIDDEN,
            detail="You do not have access to this tenant",
        )
```

### tenant_admin / member

Must have an explicit `UserTenantMapping` row:

```python
if user_role in ("tenant_admin", "member"):
    mapping = await db.execute(
        select(UserTenantMapping).where(
            UserTenantMapping.user_id == user_id,
            UserTenantMapping.tenant_id == tenant_id,
        )
    ).scalar_one_or_none()
    
    if mapping is None:
        raise HTTPException(
            status_code=HTTP_403_FORBIDDEN,
            detail="You do not have access to this tenant",
        )
```

## x-user-data Header (Runtime Services)

In addition to tenant resolution, production runtime services often carry enriched user/tenant metadata in a custom header:

```
x-user-data: {"tenant_id": "<uuid>", "user_id": "<uuid>", "roles": [...]}
```

This is set by the API gateway after auth and consumed by downstream services. Not a replacement for validation, but useful for audit logs and service-to-service context propagation.

## Schema vs. RLS Context

- **Schema-based isolation**: If `tenant.schema_name` is present, call `set_schema_context(schema_name)` which runs `SET LOCAL search_path TO {schema}, public`.
- **RLS-based isolation**: Otherwise, call `set_tenant_context(tenant_id)` which runs `SET LOCAL app.tenant_id = :tid`.

Some production services migrated from RLS to per-tenant schemas in later versions; both patterns are shown in production codebases.

## Optional Tenant Context

For endpoints that optionally scope by tenant (e.g., platform admin dashboards that can filter by tenant):

```python
async def get_optional_tenant_context(
    request: Request,
    session: dict[str, object] = Depends(require_auth),
    connection_handler: ConnectionHandler = Depends(get_connection_handler),
) -> TenantContext | None:
    """Resolve tenant context if available, return None otherwise."""
    try:
        return await get_tenant_context(request, session, connection_handler)
    except HTTPException:
        return None
```

## Logging

Always log the resolution method for audit and debugging:

```python
logger.info(
    "tenant_context.resolved",
    tenant_id=str(tenant.id),
    resolved_via=resolved_via,  # "header" | "jwt" | "session"
)
```
