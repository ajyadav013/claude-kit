# SQLAlchemy 1.4 to 2.0 Migration

Concrete migration patterns for upgrading from SQLAlchemy 1.4 to 2.0, derived from contrasting legacy services against modern reference services.

## Key Breaking Changes

### 1. `declarative_base()` → `DeclarativeBase`

**Before (SQLAlchemy 1.4 - legacy service example):**
```python
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()
```

**After (SQLAlchemy 2.0 - reference service):**
```python
from sqlalchemy.orm import DeclarativeBase

class Base(DeclarativeBase):
    """Root declarative base class for all ORM models."""
    pass
```

**Migration steps:**
1. Replace `from sqlalchemy.ext.declarative import declarative_base` with `from sqlalchemy.orm import DeclarativeBase`
2. Replace `Base = declarative_base()` with `class Base(DeclarativeBase): pass`
3. Update all model classes to inherit from the new `Base` (no code change needed, but clearer type)

**Example patterns:**
- Legacy: `core/sqlalchemy.py` line 6 (`Base = declarative_base()`)
- Modern: `app/database.py` lines 8-12 (`class Base(DeclarativeBase)`)

### 2. `Column` → `Mapped` / `mapped_column`

**Before (SQLAlchemy 1.4 - typical legacy pattern):**
```python
from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, Text
from sqlalchemy.dialects.postgresql import UUID

class Organization(Base):
    __tablename__ = 'organizations'
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    slug = Column(String(255), nullable=False, index=True)
    description = Column(Text, nullable=True)
    active = Column(Boolean, default=True)
    parent_id = Column(UUID(as_uuid=True), ForeignKey('organizations.id'), nullable=True)
```

**After (SQLAlchemy 2.0 - reference service):**
```python
from sqlalchemy import Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from typing import Optional
import uuid

class Organization(Base):
    __tablename__ = 'organizations'
    
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    parent_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey('organizations.id'),
        nullable=True,
    )
```

**Migration steps:**
1. Import `Mapped` and `mapped_column` from `sqlalchemy.orm`
2. Import `Optional` from `typing` (or use `str | None` for Python 3.10+)
3. Replace `name = Column(...)` with `name: Mapped[type] = mapped_column(...)`
4. For nullable columns, use `Mapped[Optional[type]]` or `Mapped[type | None]`
5. For non-nullable columns, use `Mapped[type]`

**Type mapping:**
- `String(n)` → `Mapped[str]`
- `Integer` → `Mapped[int]`
- `Boolean` → `Mapped[bool]`
- `Text` → `Mapped[str]` (or `Mapped[Optional[str]]` if nullable)
- `UUID(as_uuid=True)` → `Mapped[uuid.UUID]`
- `DateTime` → `Mapped[datetime]`
- Nullable: `Mapped[Optional[str]]` or `Mapped[str | None]`

**Example patterns:**
- Reference: `app/identity/v1/organization/models.py` lines 21-48 (all columns use `Mapped` + `mapped_column`)
- Modern services use DeclarativeBase + Mapped pattern

### 3. `relationship()` Type Hints

**Before (SQLAlchemy 1.4):**
```python
from sqlalchemy.orm import relationship

class Organization(Base):
    __tablename__ = 'organizations'
    
    users = relationship('User', back_populates='organization')
    tenants = relationship('Tenant', back_populates='organization')
    children = relationship('Organization', back_populates='parent', lazy='raise')
```

**After (SQLAlchemy 2.0 - reference service):**
```python
from sqlalchemy.orm import Mapped, relationship

class Organization(Base):
    __tablename__ = 'organizations'
    
    users: Mapped[list["User"]] = relationship('User', back_populates='organization')
    tenants: Mapped[list["Tenant"]] = relationship('Tenant', back_populates='organization')
    children: Mapped[list["Organization"]] = relationship(
        'Organization',
        back_populates='parent',
        lazy='raise',
    )
```

**Migration steps:**
1. Add type annotation `Mapped[list["RelatedModel"]]` for one-to-many relationships
2. Add type annotation `Mapped["RelatedModel"]` for many-to-one relationships
3. Use forward references (quoted strings) for self-referential or not-yet-defined models

**Example patterns:**
- Reference: `app/identity/v1/organization/models.py` lines 57-68 (typed relationships)

### 4. `session.query()` → `select()`

**Before (SQLAlchemy 1.4 - legacy pattern):**
```python
# Fetch all active organizations
orgs = session.query(Organization).filter(
    Organization.active == True
).order_by(Organization.name).all()

# Fetch by ID
org = session.query(Organization).filter(Organization.id == org_id).first()

# Join query
results = session.query(Tenant, Organization).join(
    Organization, Tenant.organization_id == Organization.id
).filter(Organization.active == True).all()
```

**After (SQLAlchemy 2.0 - reference service):**
```python
from sqlalchemy import select

# Fetch all active organizations
stmt = select(Organization).where(
    Organization.active == True
).order_by(Organization.name)
result = await session.execute(stmt)
orgs = result.scalars().all()

# Fetch by ID
stmt = select(Organization).where(Organization.id == org_id)
result = await session.execute(stmt)
org = result.scalar_one_or_none()

# Join query
stmt = select(Tenant, Organization).join(
    Organization, Tenant.organization_id == Organization.id
).where(Organization.active == True)
result = await session.execute(stmt)
results = result.all()
```

**Migration steps:**
1. Import `select` from `sqlalchemy`
2. Replace `session.query(Model)` with `select(Model)`
3. Replace `.filter(...)` with `.where(...)`
4. Replace `.order_by(...)` with `.order_by(...)` (unchanged)
5. Execute via `await session.execute(stmt)` (async) or `session.execute(stmt)` (sync)
6. Extract results:
   - `.all()` → `result.scalars().all()` (for single model queries)
   - `.first()` → `result.scalar_one_or_none()` or `result.scalars().first()`
   - `.one()` → `result.scalar_one()`

**Example patterns:**
- Reference: `app/dao.py` lines 180-185 (`select(self.db_model).where(...)`)
- Legacy services use mixed patterns (some `select()`, some legacy Query API)

### 5. BaseDao Modernization

**Before (SQLAlchemy 1.4 - legacy service example):**
```python
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

class BaseDao:
    def __init__(self, session: AsyncSession, db_model):
        self.session = session
        self.db_model = db_model
    
    async def get(
        self,
        query=None,
        query_filters: list[QueryFilter] = None,
        ...
    ):
        if query is None:
            query = select(self.db_model)
        # ... apply filters
        return (await self._execute_query(query)).unique().scalars().all()
```

**After (SQLAlchemy 2.0 - reference service):**
```python
from sqlalchemy import Select, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from typing import TypeVar
from app.database import Base

T = TypeVar('T', bound=Base)

class BaseDao:
    session: AsyncSession
    db_model: type
    
    def __init__(self, session: AsyncSession, db_model: type) -> None:
        self.session = session
        self.db_model = db_model
    
    async def get_by_filter(self, **kwargs) -> Sequence[Base]:
        stmt = select(self.db_model)
        for key, value in kwargs.items():
            if hasattr(self.db_model, key):
                stmt = stmt.where(getattr(self.db_model, key) == value)
        result = await self._execute_query(stmt)
        return result.scalars().all()
```

**Migration steps:**
1. Add type hints to `__init__` and methods
2. Use `Select` type hint for query parameters
3. Replace custom filter logic with `.where(...)` clauses
4. Use `result.scalars().all()` for extracting results

**Example patterns:**
- Legacy: `core/dao.py` lines 67-252 (legacy BaseDao with mixed 1.4/2.0 patterns)
- Reference: `app/dao.py` lines 20-293 (modern BaseDao, full 2.0 style)
- Legacy variant: `app/dao.py` lines 13-369 (legacy variant)

### 6. Async Session Usage

**Before (SQLAlchemy 1.4 - mixed patterns):**
```python
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

engine = create_async_engine(DATABASE_URL, echo=True)
async_session_factory = sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)

# Usage
async with async_session_factory() as session:
    result = await session.execute(select(User))
    users = result.scalars().all()
```

**After (SQLAlchemy 2.0 - reference service):**
```python
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

engine = create_async_engine(DATABASE_URL, echo=True)
async_session_factory = async_sessionmaker(
    engine, expire_on_commit=False
)

# Usage
async with async_session_factory() as session:
    result = await session.execute(select(User))
    users = result.scalars().all()
```

**Migration steps:**
1. Replace `sessionmaker` with `async_sessionmaker`
2. Remove `class_=AsyncSession` parameter (implicit in `async_sessionmaker`)
3. Keep `expire_on_commit=False` for FastAPI/async contexts

**Example patterns:**
- Reference: `app/connection.py` (uses async_sessionmaker)

## Migration Checklist

1. **Dependency update**:
   - Update `sqlalchemy` to `>=2.0` in requirements.txt
   - Verify `asyncpg` (for Postgres) or other drivers are compatible

2. **Code changes**:
   - [ ] Replace `declarative_base()` with `class Base(DeclarativeBase)`
   - [ ] Replace all `Column(...)` with `name: Mapped[type] = mapped_column(...)`
   - [ ] Add type hints to relationships: `Mapped[list["Model"]]`
   - [ ] Replace `session.query(Model)` with `select(Model)` + `session.execute()`
   - [ ] Replace `.filter(...)` with `.where(...)`
   - [ ] Replace `sessionmaker(..., class_=AsyncSession)` with `async_sessionmaker(...)`
   - [ ] Update result extraction: `.all()` → `result.scalars().all()`

3. **Testing**:
   - [ ] Run full test suite
   - [ ] Verify migrations still work with Alembic (may need Alembic upgrade)
   - [ ] Check lazy loading and relationship loading strategies
   - [ ] Verify pagination and filtering logic

## Common Gotchas

1. **`.scalars()` required for single-model queries**: Use `result.scalars().all()` instead of `result.all()` when querying a single model.

2. **Nullable columns require Optional**: `Mapped[str]` is non-nullable; use `Mapped[Optional[str]]` for nullable columns.

3. **Alembic compatibility**: Alembic < 1.8 may not fully support SQLAlchemy 2.0 `Mapped` style. Upgrade Alembic to >= 1.8.

4. **Type inference**: SQLAlchemy 2.0 infers column types from `Mapped[type]`, so `nullable=True` can be omitted if using `Optional`.

5. **`lazy='raise'` for explicit loading**: The reference service uses `lazy='raise'` on relationships to force explicit loading (prevents N+1 queries).

## Reference Service as the Authoritative Example

When migrating, use the reference service as the authoritative SQLAlchemy 2.0 example:
- `app/database.py` (DeclarativeBase)
- `app/dao.py` (modern BaseDao)
- `app/identity/v1/organization/models.py` (Mapped columns, relationships)
- `app/identity/v1/tenant/models.py` (additional examples)

All reference service models use `Mapped` + `mapped_column` and no legacy 1.4 patterns.
