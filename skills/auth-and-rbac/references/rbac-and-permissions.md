# RBAC and Permissions

Role-based access control patterns, hierarchical org access checks, and role enforcement.

## Role Hierarchy

### Platform Roles

Five-tier hierarchy with decreasing privilege levels:

1. **sys_admin** — Platform superuser, access to all orgs and tenants, can create other sys_admins
2. **org_admin** — Manages all orgs in a root organization tree (path prefix match)
3. **sub_org_admin** — Manages orgs in their subtree (path prefix match)
4. **tenant_admin** — Manages a single org/tenant (exact org_id match)
5. **member** — Read-only or limited scope within a single org (exact org_id match)

**Implementation:**
```python
# Example pattern from production FastAPI service

def get_caller_role(session: dict[str, object]) -> str:
    """Extract the caller's platform role from the session."""
    return session.get("user", {}).get("role", "member")

def is_sys_admin(session: dict[str, object]) -> bool:
    """Check whether the session belongs to a sys_admin."""
    return session.get("user", {}).get("role") == "sys_admin"

def get_caller_org_id(session: dict[str, object]) -> UUID | None:
    """Extract the caller's organization UUID from the session."""
    org_id = session.get("user", {}).get("organization_id")
    if org_id:
        return UUID(org_id) if isinstance(org_id, str) else org_id
    return None

def get_caller_user_id(session: dict[str, object]) -> UUID | None:
    """Extract the caller's user UUID from the session."""
    uid = session.get("user", {}).get("id")
    if uid:
        return UUID(uid) if isinstance(uid, str) else uid
    return None
```

## Hierarchical Org Access Checks

### Organization Path Structure

Organizations stored with materialized path: `/root/parent/child/`

```python
# Example org hierarchy:
# /acme/                      <- root org (org_admin of this can manage all under /acme/)
# /acme/retail/               <- sub-org
# /acme/retail/north/         <- leaf org
# /acme/retail/south/         <- leaf org
```

### Access Check Logic

```python
# Example pattern from production FastAPI service

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
        root_path = _get_root_path(caller_org.path)  # '/acme/retail/north/' -> '/acme/'
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


def _get_root_path(path: str) -> str:
    """Extract root segment from path. '/a/b/c/' -> '/a/'."""
    parts = path.strip("/").split("/")
    return f"/{parts[0]}/" if parts else path
```

**Key points:**
- sys_admin bypasses all checks
- org_admin can manage all orgs under their root (e.g., all `/acme/*`)
- sub_org_admin can manage only their subtree (e.g., `/acme/retail/*` but not `/acme/logistics/*`)
- tenant_admin and member have no hierarchy privileges, must exactly match org_id
- Returns 404 for sub_org_admin to avoid leaking org existence outside their tree

### Usage in Routes

```python
@router.put("/organizations/{org_id}/update")
async def update_organization(
    org_id: UUID,
    data: OrgUpdate,
    session: dict = Depends(require_org_admin_or_above),
    connection_handler: ConnectionHandler = Depends(get_connection_handler),
):
    # First check role dependency (sys_admin or org_admin)
    # Then check hierarchy access
    await assert_org_access_async(session, org_id, connection_handler)
    # Caller has access to this org
    ...
```

## Legacy Exact-Match Check (Backward Compatibility)

```python
# Example pattern from production FastAPI service

def assert_same_org(session: dict, target_org_id: UUID) -> None:
    """Sync org access check -- exact match only.
    
    Kept for backward compatibility. Use assert_org_access_async for
    hierarchy-aware checks including sub_org_admin.
    """
    if is_sys_admin(session):
        return
    caller_org_id = get_caller_org_id(session)
    if caller_org_id != target_org_id:
        raise HTTPException(
            status_code=HTTP_403_FORBIDDEN, detail="Access denied to this organization"
        )
```

**When to use:**
- Legacy endpoints that haven't migrated to hierarchy-aware checks
- Sync context where DB call is not feasible
- Simple services where only sys_admin and tenant_admin exist (no org_admin/sub_org_admin)

## Domain-Specific Role Enums

For domain-specific roles beyond platform roles.

```python
# Example pattern from production multi-level access service

import enum

class Role(str, enum.Enum):
    L1 = "L1"  # Level 1 access
    L2 = "L2"  # Level 2 access

class Member(Base):
    __tablename__ = "member"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String, nullable=False)
    name = Column(String, nullable=False)
    role = Column(String, nullable=False, default=Role.L1)
    
    __table_args__ = (UniqueConstraint("email", "role", name="uix_email_role"),)
```

**Key points:**
- Domain-specific roles are separate from platform roles (sys_admin, org_admin, etc.)
- Stored as string enum in DB with default
- Unique constraint on (email, role) allows same user to have multiple roles
- Check with `if member.role == Role.L2:` in business logic

## Role-Based Registration Restrictions

```python
# Example pattern from production registration flow

# Excerpt showing role-based registration rules
role = getattr(data, "role", "member") or "member"
org_id = getattr(data, "organization_id", None)

# org_admin and member require organization_id
if role in ("org_admin", "member") and not org_id:
    raise HTTPException(
        status_code=HTTP_400_BAD_REQUEST,
        detail="organization_id is required for org_admin and member roles",
    )

# Privileged roles cannot self-register
privileged_roles = ("org_admin", "sub_org_admin", "tenant_admin")
if role in privileged_roles and not caller_session:
    raise HTTPException(
        status_code=HTTP_403_FORBIDDEN,
        detail=f"Cannot self-register with role '{role}'; authentication required",
    )

# Only sys_admins can create sys_admins
if role == "sys_admin" and caller_session:
    caller_role = caller_session.get("user", {}).get("role")
    if caller_role != "sys_admin":
        raise HTTPException(
            status_code=HTTP_403_FORBIDDEN,
            detail="Only sys admins can create sys admin users",
        )
```

**Key points:**
- member and org_admin must be associated with an organization
- Privileged roles (org_admin, sub_org_admin, tenant_admin) require authenticated caller
- sys_admin role can only be created by another sys_admin
- Prevents privilege escalation via self-registration

## Permission-Based RBAC (Not Found)

**Note:** No evidence of fine-grained permission systems (e.g., `has_permission("users:write")`, `@requires_permission` decorators) was found in the examined repositories. All RBAC is role-based with hierarchical org access checks.

If fine-grained permissions are needed, consider:
- **FastAPI-Permissions** library for declarative permission checks
- **Casbin** for policy-based access control with role-permission mappings
- Custom permission table with many-to-many user-permission mapping + `Depends(require_permission("resource:action"))`

For now, this skill documents role-based access only, as that's the confirmed pattern in production.
