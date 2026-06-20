# SQLAlchemy 1.4 vs 2.0 Migration Guide

Side-by-side comparison of model and query idioms across SQLAlchemy 1.4 and 2.0 as observed in production Python/FastAPI services.

> Confirmed against: [SQLAlchemy 2.0 Documentation - ORM Declarative Models](https://docs.sqlalchemy.org/en/20/orm/declarative_tables.html)

## Version usage patterns

| Version | Characteristics | Examples |
|---------|----------------|----------|
| 1.4 | Uses `declarative_base`, `Column`, no typing | Older services, legacy codebases |
| 2.0 | Uses `DeclarativeBase`, `Mapped[T]`, `mapped_column` | Modern services, new projects, analytics systems |

## Model declaration

### 1.4 style

```python
from sqlalchemy import Column, Integer, String, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship

Base = declarative_base()

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    email = Column(String(255), unique=True, nullable=False)
    name = Column(String(100), nullable=True)
    org_id = Column(Integer, ForeignKey("organizations.id"), nullable=False)

    organization = relationship("Organization", back_populates="users")
```

**Characteristics:**
- `declarative_base()` function returns a base class
- `Column(...)` for columns
- NO type hints
- Relationships are untyped strings

### 2.0 style

```python
from typing import Optional
from sqlalchemy import String, Integer, ForeignKey
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

class Base(DeclarativeBase):
    pass

class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    org_id: Mapped[int] = mapped_column(Integer, ForeignKey("organizations.id"), nullable=False)

    organization: Mapped["Organization"] = relationship(back_populates="users")
```

**Characteristics:**
- `DeclarativeBase` class is subclassed (no function call)
- `Mapped[T]` type annotations for all columns
- `mapped_column(...)` instead of `Column(...)`
- `Mapped[Optional[T]]` for nullable columns, `Mapped[T]` for non-nullable
- Relationships are `Mapped["RelatedModel"]` (forward references as strings)

## Nullable columns

### 1.4

```python
name = Column(String(100), nullable=True)   # Nullable
email = Column(String(255), nullable=False) # Non-nullable
```

Nullability is purely runtime; no type-checker support.

### 2.0

```python
from typing import Optional

name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
email: Mapped[str] = mapped_column(String(255), nullable=False)
```

`Mapped[Optional[T]]` signals nullable to the type checker. The `nullable=True` argument is still required at runtime.

## Primary keys and defaults

### 1.4

```python
id = Column(Integer, primary_key=True, autoincrement=True)
created_at = Column(DateTime, server_default=text("CURRENT_TIMESTAMP"))
```

### 2.0

```python
from datetime import datetime
from sqlalchemy import text

id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
created_at: Mapped[datetime] = mapped_column(
    DateTime(timezone=True),
    nullable=False,
    server_default=text("CURRENT_TIMESTAMP")
)
```

## UUID primary keys

### 1.4

```python
from sqlalchemy.dialects.postgresql import UUID
import uuid

id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
```

### 2.0 style

```python
import uuid
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import UUID

id: Mapped[uuid.UUID] = mapped_column(
    UUID(as_uuid=True),
    primary_key=True,
    default=uuid.uuid4,
    server_default=text("gen_random_uuid()")
)
```

**Note:** `server_default=text("gen_random_uuid()")` ensures the database generates the UUID if the application doesn't provide one.

## Relationships

### 1.4

```python
from sqlalchemy.orm import relationship

class Organization(Base):
    __tablename__ = "organizations"
    id = Column(Integer, primary_key=True)
    users = relationship("User", back_populates="organization")

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    org_id = Column(Integer, ForeignKey("organizations.id"))
    organization = relationship("Organization", back_populates="users")
```

### 2.0

```python
from sqlalchemy.orm import relationship, Mapped

class Organization(Base):
    __tablename__ = "organizations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    users: Mapped[list["User"]] = relationship(back_populates="organization")

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    org_id: Mapped[int] = mapped_column(Integer, ForeignKey("organizations.id"))
    organization: Mapped["Organization"] = relationship(back_populates="users")
```

**Key changes:**
- One-to-many: `Mapped[list["User"]]`
- Many-to-one: `Mapped["Organization"]`
- Forward references remain strings (`"User"`, `"Organization"`)

## Lazy loading (2.0 only)

```python
users: Mapped[list["User"]] = relationship(back_populates="organization", lazy="select")
```

**Lazy options:**
- `"select"` (default): load on attribute access (N+1 queries)
- `"joined"`: eager load via JOIN
- `"subquery"`: eager load via subquery
- `"selectin"`: eager load via SELECT IN (recommended for collections)
- `"noload"`: never load (attribute is always None)

## Mixins (2.0 style)

```python
from sqlalchemy.orm import declared_attr

class CreatedAtMixin:
    @declared_attr
    def created_at(cls) -> Mapped[datetime]:
        return mapped_column(
            DateTime(timezone=True),
            nullable=False,
            server_default=text("CURRENT_TIMESTAMP"),
        )

class User(Base, CreatedAtMixin):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
```

The `@declared_attr` decorator is required for mixin properties that reference the concrete class.

## Custom types (production example)

```python
from sqlalchemy import TypeDecorator, CHAR
from sqlalchemy.dialects.postgresql import UUID
import uuid

class GUID(TypeDecorator):
    """Platform-independent GUID type. Uses PostgreSQL's UUID if available, else CHAR(32)."""
    impl = CHAR
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == 'postgresql':
            return dialect.type_descriptor(UUID())
        else:
            return dialect.type_descriptor(CHAR(32))

    def process_bind_param(self, value, dialect):
        if value is None:
            return value
        elif dialect.name == 'postgresql':
            return str(value)
        else:
            if not isinstance(value, uuid.UUID):
                return uuid.UUID(value).hex
            else:
                return value.hex

    def process_result_value(self, value, dialect):
        if value is None:
            return value
        else:
            if not isinstance(value, uuid.UUID):
                return uuid.UUID(value)
            else:
                return value
```

Usage:

```python
id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=uuid.uuid4)
```

## Query syntax (both versions)

Both 1.4 and 2.0 support the same query syntax (SQLAlchemy 2.0 style):

```python
from sqlalchemy import select

# Select all
query = select(User)

# Filter
query = select(User).where(User.email == "alice@example.com")

# Join
query = select(User).join(User.organization).where(Organization.name == "Acme")

# Order by
query = select(User).order_by(User.created_at.desc())

# Limit/offset
query = select(User).limit(10).offset(20)

# Execute
result = await session.execute(query)
users = result.scalars().all()
```

**Note:** The `Query` API (`session.query(User)`) is deprecated in 2.0 but still works. All new code should use `select(...)`.

## Migration checklist (1.4 → 2.0)

1. Replace `declarative_base()` with `class Base(DeclarativeBase): pass`
2. Replace `Column(...)` with `mapped_column(...)`
3. Add `Mapped[T]` / `Mapped[Optional[T]]` type annotations to all columns
4. Add `Mapped["RelatedModel"]` / `Mapped[list["RelatedModel"]]` to relationships
5. Replace `session.query(Model)` with `select(Model)`
6. Ensure all queries use `session.execute(select(...))` instead of `session.query(...)`
7. Test lazy loading behavior (2.0 defaults are stricter)

## Common pitfalls

1. **Forgot `Optional`**: `Mapped[str]` with `nullable=True` will raise at runtime. Use `Mapped[Optional[str]]`.
2. **Forgot string quotes on forward references**: `Mapped[User]` (undefined) vs `Mapped["User"]` (forward ref).
3. **Mixed 1.4 and 2.0 syntax**: Do NOT mix `Column` and `mapped_column` in the same model.
4. **Lazy loading in async**: SQLAlchemy async does NOT support implicit lazy loading. Use `selectinload` / `joinedload` or set `lazy="raise"` to catch violations.
