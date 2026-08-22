# Example Patterns

Illustrative code examples demonstrating each modernization pattern.

## Pydantic v1 (Legacy Services)

### Legacy Service Example (Pydantic v1)

**@validator pattern:**
```
app/shipment/schemas.py:112
```
```python
from pydantic import BaseModel, Field, EmailStr, Json, validator

class ContactDetails(BaseModel):
    contact_name: str
    contact_email: EmailStr
    
    @validator('contact_email', pre=True)
    def validate_email(cls, v):
        # ... validation logic
        return v
    
    class Config:
        orm_mode = True
```

**BaseSettings import (Pydantic v1):**
```
config/docker_config.py:6
```
```python
from pydantic import BaseSettings

class Settings(BaseSettings):
    database_url: str
    redis_host: str
    # ... other settings
```

**constr/conint constraints:**
```
app/ewaybill/serializer.py:7
```
```python
from pydantic import BaseModel, Field, constr, conint

class EwaybillSchema(BaseModel):
    transaction_id: constr(min_length=1, max_length=15)
    vehicle_number: constr(regex=r'^[A-Z]{2}\d{2}[A-Z]{2}\d{4}$')
    distance: conint(ge=0, le=4000)
```

### Other Legacy Services (Pydantic v1)

Similar patterns observed across multiple legacy services with the same `@validator`, `class Config: orm_mode = True` patterns.

## Pydantic v2 (Modern Services)

### Reference Service (Pydantic v2)

**model_config = ConfigDict(from_attributes=True):**
```
app/identity/v1/organization/serializers.py:65
```
```python
from pydantic import BaseModel, ConfigDict, Field

class OrgOut(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    description: Optional[str] = None
    # ... other fields
    
    model_config = ConfigDict(from_attributes=True)
```

**Repeated in same file (lines 76, 93, 104):**
```python
class TenantBriefOut(BaseModel):
    # ...
    model_config = ConfigDict(from_attributes=True)

class OrgTreeNode(BaseModel):
    # ...
    model_config = ConfigDict(from_attributes=True)

class OrgAncestorOut(BaseModel):
    # ...
    model_config = ConfigDict(from_attributes=True)
```

**No @validator imports** — reference service uses modern Pydantic v2 throughout, no legacy patterns.

## SQLAlchemy 1.4 (Legacy Services)

### Legacy Service Example (SQLAlchemy 1.4)

**declarative_base pattern:**
```
core/sqlalchemy.py:6
```
```python
from sqlalchemy.orm import declarative_mixin, Mapped, declarative_base

Base = declarative_base()
```

**Column-based model:**
Legacy services use `Column(...)` pattern (SQLAlchemy 1.4), not `Mapped` (2.0).

### Other Legacy Services (SQLAlchemy 1.4)

Similar patterns observed across multiple legacy services.

## SQLAlchemy 2.0 (Modern Services)

### Reference Service (SQLAlchemy 2.0)

**DeclarativeBase:**
```
app/database.py:8-12
```
```python
from sqlalchemy.orm import DeclarativeBase

class Base(DeclarativeBase):
    """Root declarative base class for all ORM models."""
    pass
```

**Mapped columns:**
```
app/identity/v1/organization/models.py:21-48
```
```python
from sqlalchemy import Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
import uuid
from typing import Optional

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

**Typed relationships:**
```
app/identity/v1/organization/models.py:57-68
```
```python
from sqlalchemy.orm import Mapped, relationship

class Organization(Base):
    # ...
    users: Mapped[list["User"]] = relationship('User', back_populates='organization')
    tenants: Mapped[list["Tenant"]] = relationship('Tenant', back_populates='organization')
    children: Mapped[list["Organization"]] = relationship(
        'Organization',
        back_populates='parent',
        lazy='raise',
    )
```

## Duplicated Core Infrastructure

### Legacy Service core/ directory

```
core/
  dao.py                    (~400 lines)
  connection_handler.py     (~80 lines)
  connection_manager.py     (~150 lines)
  decorators.py
  exceptions.py
  sqlalchemy.py
  system_lifecycle.py
  date_utils.py
  aiohttprequest.py
```

**BaseDao excerpt:**
```
core/dao.py:67-116
```
```python
class BaseDao:
    def __init__(self, session: AsyncSession, db_model):
        self.session = session
        self.db_model = db_model
    
    async def _flush(self):
        await self.session.flush()
    
    async def _commit(self):
        await self.session.commit()
    
    async def create(self, create_object_dict=None, **create_kwargs):
        orm_object = self.add_object(create_object_dict, **create_kwargs)
        await self._commit()
        return orm_object
    
    async def get_paginated_response(
        self, query, page_size: int = 10, page_number: int = 1, ...
    ):
        # ... pagination logic (~50 lines)
```

**ConnectionHandler excerpt:**
```
core/connection_handler.py:13-42
```
```python
class ConnectionHandler:
    def __init__(self, connection_manager=None, event_bridge=None):
        self._session: Optional[AsyncSession] = None
        self._redis_connection = None
        self._event_emitter = None
        self._connection_manager = connection_manager
        self._event_bridge = event_bridge
    
    @property
    def session(self):
        return self._session or self._get_session()
    
    async def close(self):
        if self._session:
            await self._session.close()
```

### Other Legacy Service core/ directory (near-identical copy)

```
core/
  dao.py                    (~400 lines, with drift)
  connection_handler.py     (same structure)
  connection_manager.py
  decorators.py
  exceptions.py
  sqlalchemy.py
  system_lifecycle.py
  date_utils.py
  aiohttprequest.py
```

**Diff confirms divergence:**
```bash
# Files differ (minor changes, proves copy-paste pattern)
```

### Variant app/ directory

```
app/
  dao.py                    (~370 lines, different variant)
  connection.py             (variant of ConnectionHandler)
  routing.py
  database.py
  lifetime.py
  utils.py
```

**BaseDao excerpt (variant with different pagination signature):**
```
app/dao.py:213-279
```
```python
class BaseDao:
    # ... similar structure but different method signatures
    async def get_paginated_response(
        self,
        query: Select,
        page_size: int,
        page_number: int,
        sort_by: str = None,
        order_by: str = None,
        count_field=None,  # Different signature
    ):
        # ... variant pagination logic
```

### Reference Service (no duplicated core/ directory)

```
app/
  dao.py                    (~290 lines, modern BaseDao with SQLAlchemy 2.0)
  connection.py             (ConnectionHandler, service-local)
  routing.py                (CustomRequestRoute, service-local)
  database.py               (DeclarativeBase)
  lifetime.py
  utils.py
```

**Reference Service BaseDao (clean, no duplication):**
```
app/dao.py:20-93
```
```python
from typing import TypeVar
from app.database import Base

T = TypeVar('T', bound=Base)

class BaseDao:
    """Generic async DAO with CRUD, pagination, and soft-delete support."""
    
    session: AsyncSession
    db_model: type
    
    def __init__(self, session: AsyncSession, db_model: type) -> None:
        self.session = session
        self.db_model = db_model
    
    async def create(
        self, create_object_dict: Optional[Dict[str, Any]] = None, **create_kwargs: Any
    ) -> Base:
        orm_object = self.add_object(create_object_dict, **create_kwargs)
        await self._commit()
        return orm_object
    
    async def get_paginated_response(
        self,
        query: Select,
        page_size: int = 20,
        page_number: int = 1,
        sort_by: str | None = None,
        order_by: str | None = None,
    ) -> tuple[list[Base], dict[str, Any]]:
        # ... modern pagination with type hints
```

**Reference Service modern approach:**
- No `core/` directory (infrastructure lives in `app/`)
- SQLAlchemy 2.0 `Mapped` + `mapped_column`
- Pydantic v2 `model_config = ConfigDict(from_attributes=True)`
- Type hints throughout
- Service-local infrastructure (not shared, but also not duplicated)

## Summary of Patterns

| Service Type | Pydantic | SQLAlchemy | Duplicated core/ | Lines of BaseDao |
|---------|----------|------------|------------------|------------------|
| legacy-a | v1 | 1.4 | Yes | ~400 |
| legacy-b | v1 | 1.4 | Yes | ~400 (with drift) |
| legacy-c | v1 | 1.4 | Yes (variant) | ~370 |
| reference | v2 | 2.0 | No | ~290 (modern) |

**Observed duplication:**
- Multiple legacy services have similar `core/dao.py`, `core/connection_handler.py`, `core/connection_manager.py`
- Some services have nearly identical copies (diff confirms divergence)
- Some have variants with different signatures
- The reference service avoided this by being built after the pattern was recognized

**Recommendation:** Extract to a shared library to eliminate duplication.
