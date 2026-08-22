# Dependency Injection Patterns

Deep pattern inventory for FastAPI dependency injection: `ConnectionHandler`, auth dependencies, and usage in route handlers.

## ConnectionManager singleton

### Purpose

Single source of truth for database engine and Redis client, initialized once on application startup.

### Implementation

```python
from asyncio import current_task
from typing import Optional, Callable
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_scoped_session,
    create_async_engine,
)
from sqlalchemy.orm import sessionmaker
from redis.asyncio import Redis
from config.settings import settings

class ConnectionManager:
    """Singleton that manages the async database engine and Redis client."""

    _instance: Optional["ConnectionManager"] = None
    _db_engine: AsyncEngine
    _db_session_factory: Callable[..., AsyncSession]
    _redis: Redis

    def __new__(cls) -> "ConnectionManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._db_engine, cls._instance._db_session_factory = cls._setup_db()
            cls._instance._redis = cls._setup_redis()
        return cls._instance

    def get_session_factory(self) -> Callable[..., AsyncSession]:
        """Return the async scoped session factory."""
        return self._db_session_factory

    def get_redis(self) -> Redis:
        """Return the shared Redis client."""
        return self._redis

    @staticmethod
    def _setup_db() -> tuple[AsyncEngine, Callable[..., AsyncSession]]:
        engine = create_async_engine(
            settings.DATABASE_URL,
            echo=settings.DB_ECHO,
            pool_pre_ping=True,
            pool_size=settings.DB_POOL_SIZE,
            max_overflow=settings.DB_MAX_OVERFLOW,
            pool_recycle=settings.DB_POOL_RECYCLE,
        )
        session_factory = async_scoped_session(
            sessionmaker(engine, expire_on_commit=False, class_=AsyncSession),
            scopefunc=current_task,
        )
        return engine, session_factory

    @staticmethod
    def _setup_redis() -> Redis:
        return Redis.from_url(settings.REDIS_URL, decode_responses=True)

    async def close_connections(self) -> None:
        """Dispose of the database engine and close the Redis client."""
        await self._db_engine.dispose()
        await self._redis.close()
```

**Key points**:
- **Singleton pattern**: `__new__` ensures only one instance exists
- **Scoped session factory**: `async_scoped_session` with `scopefunc=current_task` ensures one session per asyncio task
- **Pool configuration**: `pool_pre_ping=True` (test connection before use), `pool_size`, `max_overflow`, `pool_recycle` (recreate connections after N seconds to avoid stale connections)
- **Redis decode_responses=True**: auto-decode bytes to strings

## ConnectionHandler (per-request wrapper)

### Purpose

Lazily creates database session and provides access to Redis, with support for multi-tenancy (RLS, schema switching).

### Implementation

```python
from typing import Optional, AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncSession
from redis.asyncio import Redis
from sqlalchemy import text
from uuid import UUID

class ConnectionHandler:
    """Per-request wrapper providing lazy database session and Redis access."""

    _session: Optional[AsyncSession]
    _redis: Optional[Redis]
    _connection_manager: ConnectionManager

    def __init__(self) -> None:
        self._session = None
        self._redis = None
        self._connection_manager = ConnectionManager()

    @property
    def session(self) -> AsyncSession:
        """Lazily create and return the database session."""
        if not self._session:
            self._session = self._connection_manager.get_session_factory()()
        return self._session

    @property
    def redis(self) -> Redis:
        """Return the shared Redis client."""
        if not self._redis:
            self._redis = self._connection_manager.get_redis()
        return self._redis

    async def set_tenant_context(self, tenant_id: UUID) -> None:
        """Set PostgreSQL session variable for RLS filtering (legacy).
        
        Args:
            tenant_id: Tenant UUID to scope all subsequent queries.
        """
        await self.session.execute(
            text("SET LOCAL app.tenant_id = :tid"),
            {"tid": str(tenant_id)},
        )

    async def set_schema_context(self, schema_name: str) -> None:
        """Switch search_path to a tenant's dedicated schema.
        
        All subsequent queries resolve tenant-scoped tables from the
        tenant schema, falling back to public for shared tables.
        
        Args:
            schema_name: Full schema name (e.g. ``acme_payments``).
        """
        import re
        clean = schema_name.lower()
        if not re.match(r"^[a-z0-9][a-z0-9_]*$", clean):
            raise ValueError(f"Invalid schema name: {schema_name}")
        await self.session.execute(text(f"SET LOCAL search_path TO {clean}, public"))

    async def clear_schema_context(self) -> None:
        """Reset search_path to public schema only."""
        await self.session.execute(text("SET LOCAL search_path TO public"))

    async def clear_tenant_context(self) -> None:
        """Reset the RLS tenant context variable."""
        await self.session.execute(text("RESET app.tenant_id"))

    async def set_rls_bypass(self, *, enabled: bool = True) -> None:
        """Enable or disable RLS bypass for platform admin operations.
        
        Args:
            enabled: True to bypass RLS, False to restore normal filtering.
        """
        value = "true" if enabled else "false"
        await self.session.execute(
            text("SET LOCAL app.bypass_rls = :val"),
            {"val": value},
        )

    async def session_commit(self) -> None:
        """Commit the current session transaction."""
        await self.session.commit()

    async def close(self) -> None:
        """Close the session if open."""
        if self._session:
            await self._session.close()
```

**Key points**:
- **Lazy session creation**: session is only created when `handler.session` is accessed
- **Multi-tenancy support**: `set_tenant_context()` sets PostgreSQL session variable `app.tenant_id` for RLS policies; `set_schema_context()` switches `search_path` to a tenant schema
- **RLS bypass**: `set_rls_bypass(enabled=True)` for platform admin operations
- **Session lifecycle**: created per request, closed in finally block of dependency

### Dependency factory

```python
async def get_connection_handler() -> AsyncGenerator[ConnectionHandler, None]:
    """FastAPI dependency that yields a per-request ConnectionHandler.
    
    Ensures the database session is closed on teardown regardless
    of whether the request succeeded or raised an exception.
    
    Yields:
        A fresh ``ConnectionHandler`` for the current request.
    """
    handler = ConnectionHandler()
    try:
        yield handler
    finally:
        await handler.close()
```

**Usage in route**:

```python
from fastapi import Depends
from app.connection import ConnectionHandler, get_connection_handler

async def my_endpoint(
    connection_handler: ConnectionHandler = Depends(get_connection_handler),
):
    # Access session
    session = connection_handler.session
    result = await session.execute(select(User))
    
    # Access Redis
    await connection_handler.redis.set("key", "value")
    
    # Multi-tenancy: set tenant context
    await connection_handler.set_tenant_context(tenant_id)
    # All subsequent queries are scoped to this tenant
```

## Auth dependencies

### require_auth

```python
from fastapi import Header, HTTPException
from starlette.status import HTTP_401_UNAUTHORIZED
import jwt

async def require_auth(
    authorization: str = Header(..., alias="Authorization"),
) -> dict[str, object]:
    """Validate JWT access token and return session payload.
    
    Args:
        authorization: Bearer token from Authorization header.
    
    Returns:
        Decoded JWT payload with user_id, role, tenant_id, etc.
    
    Raises:
        HTTPException: 401 if token is missing, invalid, or expired.
    """
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=HTTP_401_UNAUTHORIZED, detail="Invalid token format")
    
    token = authorization.replace("Bearer ", "")
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=["HS256"])
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=HTTP_401_UNAUTHORIZED, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=HTTP_401_UNAUTHORIZED, detail="Invalid token")

def get_caller_user_id(session: dict[str, object]) -> UUID:
    """Extract user_id from auth session payload."""
    return UUID(session["user_id"])
```

**Usage**:

```python
async def my_endpoint(
    session: dict[str, object] = Depends(require_auth),
    connection_handler: ConnectionHandler = Depends(get_connection_handler),
):
    user_id = get_caller_user_id(session)
    # ... use user_id
```

### x-user-data header dependency

In some services, auth is via x-user-data JWT header instead of Authorization. The header is parsed in CustomRequestRoute and attached to `request.state.user_data`:

```python
# In CustomRequestRoute:
if x_user_data := request.headers.get("x-user-data"):
    x_user_data = orjson.loads(x_user_data)
    request.state.user_data = x_user_data
```

**Usage in route**:

```python
from fastapi import Request

async def my_endpoint(request: Request):
    user_data = request.state.user_data  # {"user_id": "...", "roleSlug": "admin", ...}
    user_id = user_data["user_id"]
    role = user_data["roleSlug"]
    # ...
```

Alternatively, define a dependency:

```python
from fastapi import Request, HTTPException
from starlette.status import HTTP_403_FORBIDDEN

async def get_user_data(request: Request) -> dict:
    """Extract x-user-data from request state."""
    if not hasattr(request.state, "user_data"):
        raise HTTPException(status_code=HTTP_403_FORBIDDEN, detail="Missing x-user-data")
    return request.state.user_data

async def my_endpoint(user_data: dict = Depends(get_user_data)):
    user_id = user_data["user_id"]
    # ...
```

### Role-based access dependencies

```python
from fastapi import HTTPException
from starlette.status import HTTP_403_FORBIDDEN

async def require_org_admin_or_above(
    session: dict[str, object] = Depends(require_auth),
) -> dict[str, object]:
    """Require user to have org_admin, platform_admin, or super_admin role."""
    role = session.get("role")
    if role not in ["org_admin", "platform_admin", "super_admin"]:
        raise HTTPException(status_code=HTTP_403_FORBIDDEN, detail="Insufficient permissions")
    return session

async def admin_endpoint(
    session: dict[str, object] = Depends(require_org_admin_or_above),
    connection_handler: ConnectionHandler = Depends(get_connection_handler),
):
    # Only org_admin+ can access this endpoint
    ...
```

## Dependency composition

FastAPI dependencies can be nested:

```python
async def get_current_tenant(
    session: dict[str, object] = Depends(require_auth),
    connection_handler: ConnectionHandler = Depends(get_connection_handler),
) -> Tenant:
    """Resolve current tenant from session."""
    tenant_id = UUID(session["tenant_id"])
    tenant = await TenantDAO(connection_handler.session).get_by_id(tenant_id)
    if not tenant:
        raise HTTPException(status_code=HTTP_404_NOT_FOUND, detail="Tenant not found")
    return tenant

async def my_endpoint(
    tenant: Tenant = Depends(get_current_tenant),
    connection_handler: ConnectionHandler = Depends(get_connection_handler),
):
    # tenant is already resolved and validated
    await connection_handler.set_schema_context(tenant.schema_name)
    # ... tenant-scoped queries
```

## DAO pattern (data access layer)

DAOs receive a session and encapsulate query logic. Most repos use a `BaseDao` pattern for standardized CRUD operations.

### BaseDao pattern

```python
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import Select, select, asc, desc, func
from typing import Any, TypeVar
from app.database import Base

T = TypeVar("T", bound=Base)

class BaseDao:
    """Generic async DAO with CRUD, pagination, and soft-delete support."""

    session: AsyncSession
    db_model: type

    def __init__(self, session: AsyncSession, db_model: type) -> None:
        self.session = session
        self.db_model = db_model

    async def _execute_query(self, query: Any) -> Any:
        """Execute a SQLAlchemy statement with automatic rollback on error."""
        try:
            result = await self.session.execute(query)
            return result
        except Exception:
            await self.session.rollback()
            raise

    async def create(self, create_object_dict: dict[str, Any] | None = None, **create_kwargs: Any) -> Base:
        """Create and commit a new ORM object."""
        kwargs = create_object_dict or create_kwargs
        orm_object = self.db_model(**kwargs)
        self.session.add(orm_object)
        await self.session.flush()
        await self.session.refresh(orm_object)
        return orm_object

    async def get_by_id(self, record_id: Any) -> Base | None:
        """Retrieve a single record by primary key."""
        result = await self._execute_query(
            select(self.db_model).where(self.db_model.id == record_id)
        )
        return result.scalar_one_or_none()

    async def update(self, record_id: Any, update_dict: dict[str, Any]) -> Base | None:
        """Update a record by ID and return the updated object."""
        obj = await self.get_by_id(record_id)
        if not obj:
            return None
        for key, value in update_dict.items():
            setattr(obj, key, value)
        await self.session.flush()
        await self.session.refresh(obj)
        return obj

    async def delete(self, record_id: Any) -> bool:
        """Hard-delete a record by ID."""
        obj = await self.get_by_id(record_id)
        if not obj:
            return False
        await self.session.delete(obj)
        await self.session.flush()
        return True

    async def get_paginated_response(
        self,
        query: Select,
        page: int = 1,
        page_size: int = 20,
        sort_by: str | None = None,
        sort_order: str = "asc",
    ) -> tuple[list[Base], dict[str, Any]]:
        """Execute a query with pagination, sorting, and total count.

        Args:
            query: Base SQLAlchemy select query.
            page: Page number (1-based).
            page_size: Items per page.
            sort_by: Column name to sort by (optional).
            sort_order: "asc" or "desc".

        Returns:
            Tuple of (result list, pagination info dict).
        """
        pagination_info: dict[str, Any] = {
            "page": page,
            "page_size": page_size,
            "total_records": 0,
            "total_pages": 0,
        }

        # Count total records
        count_query = select(func.count()).select_from(query.subquery())
        count_result = await self._execute_query(count_query)
        total_count = count_result.scalar() or 0
        pagination_info["total_records"] = total_count
        pagination_info["total_pages"] = (total_count + page_size - 1) // page_size

        # Apply sorting
        if sort_by:
            column = getattr(self.db_model, sort_by, None)
            if column is not None:
                query = query.order_by(desc(column) if sort_order == "desc" else asc(column))

        # Apply pagination
        offset = (page - 1) * page_size
        paginated_query = query.limit(page_size).offset(offset)
        query_result = await self._execute_query(paginated_query)
        result = list(query_result.scalars().all())

        return result, pagination_info
```

### Domain DAO example

```python
from sqlalchemy import select
from app.dao import BaseDao
from app.models import User

class UserDAO(BaseDao):
    def __init__(self, session: AsyncSession):
        super().__init__(session, User)

    async def get_by_email(self, email: str) -> User | None:
        result = await self._execute_query(
            select(User).where(User.email == email)
        )
        return result.scalar_one_or_none()

    async def list_active_users(self) -> list[User]:
        result = await self._execute_query(
            select(User).where(User.is_active == True)
        )
        return list(result.scalars().all())
```

**Usage in route**:

```python
async def list_users(
    page: int = 1,
    page_size: int = 20,
    connection_handler: ConnectionHandler = Depends(get_connection_handler),
) -> ResponseData:
    dao = UserDAO(connection_handler.session)
    query = select(User).where(User.is_active == True)
    results, pagination_info = await dao.get_paginated_response(query, page, page_size, sort_by="created_at")
    return ResponseData.ok(
        data=[u.model_dump() for u in results],
        message="Users listed",
        pagination=pagination_info,
    )
```

## No DI container

These repos do not use a DI container (e.g., dependency-injector, lagom). All dependencies are plain FastAPI `Depends` functions. This keeps the stack simple and testable.

## Testing with dependency overrides

FastAPI supports dependency overrides for testing:

```python
import pytest
from fastapi.testclient import TestClient
from app.application import get_app
from app.connection import get_connection_handler

@pytest.fixture
def mock_connection_handler():
    """Mock ConnectionHandler for testing."""
    class MockHandler:
        session = MagicMock()
        redis = MagicMock()
    return MockHandler()

@pytest.fixture
def client(mock_connection_handler):
    app = get_app()
    app.dependency_overrides[get_connection_handler] = lambda: mock_connection_handler
    return TestClient(app)

def test_list_users(client):
    response = client.get("/v1/users")
    assert response.status_code == 200
```

## Summary checklist

When implementing dependency injection:

- [ ] Create `ConnectionManager` singleton in `app/connection.py`
- [ ] Initialize `ConnectionManager()` in lifespan startup
- [ ] Close connections in lifespan shutdown (`await ConnectionManager().close_connections()`)
- [ ] Create `ConnectionHandler` with lazy `session` and `redis` properties
- [ ] Implement `get_connection_handler()` dependency factory with try/finally close
- [ ] Define auth dependency (`require_auth` or parse x-user-data in CustomRequestRoute)
- [ ] Inject `ConnectionHandler` via `Depends(get_connection_handler)` in routes
- [ ] Create `BaseDao` class in `app/dao.py` with CRUD and pagination methods
- [ ] Pass `connection_handler.session` to DAO constructors (domain DAOs inherit from `BaseDao`)
- [ ] Use `dao.get_paginated_response(query, page, page_size)` for paginated endpoints
- [ ] For multi-tenancy: call `set_tenant_context()` or `set_schema_context()` before queries
- [ ] For admin operations: use `set_rls_bypass(enabled=True)` if needed
- [ ] Use dependency composition for derived resources (current tenant, current user)
- [ ] Override dependencies in tests with `app.dependency_overrides[dep] = mock`
