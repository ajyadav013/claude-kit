---
name: modernization-and-migration
description: Migration patterns from legacy (Pydantic v1 + SQLAlchemy 1.4) to modern (Pydantic v2 + SQLAlchemy 2.0 Mapped) stack, plus shared-library extraction for duplicated core infrastructure. Use when modernizing legacy Python backends, planning Pydantic v1→v2 or SQLAlchemy 1.4→2.0 upgrades, migrating @validator to @field_validator, replacing declarative_base with DeclarativeBase, converting Column to Mapped/mapped_column, extracting shared internal libraries from copy-pasted infrastructure code (BaseDao/ConnectionHandler/routing), eliminating duplicated core/ directories across microservices, or establishing a golden reference service template.
---

# Modernization and Migration

Stack modernization patterns derived from contrasting legacy cohort (Pydantic v1 / SQLAlchemy 1.4) against modern cohort (Pydantic v2 / SQLAlchemy 2.0), plus shared-library extraction strategy.

## When to use

- Migrating Pydantic v1 to v2 (validator → field_validator, Config → model_config, BaseSettings import)
- Migrating SQLAlchemy 1.4 to 2.0 (declarative_base → DeclarativeBase, Column → Mapped/mapped_column, Query → select())
- Extracting duplicated core infrastructure (BaseDao, ConnectionHandler, routing utilities) into a shared internal library
- Establishing a golden reference template service for new microservices
- Auditing codebase consistency and identifying divergent copies of core utilities

## Core conventions

### Pydantic v1 → v2 Migration

**@validator → @field_validator**: Replace `@validator('field_name', pre=True)` with `@field_validator('field_name', mode='before')`. _(reference service)_

**Config class → model_config**: Replace inner `class Config: orm_mode = True` with `model_config = ConfigDict(from_attributes=True)`. _(reference service)_

**BaseSettings import move**: Change `from pydantic import BaseSettings` to `from pydantic_settings import BaseSettings`. Requires adding `pydantic-settings` to dependencies. _(reference service)_

**Validator decorator import**: Change `from pydantic import validator` to `from pydantic import field_validator`. _(reference service)_

**When to use**: All new services use Pydantic v2; legacy services remain on v1 until a dedicated migration sprint. Use the reference service as the golden pattern for v2.

### SQLAlchemy 1.4 → 2.0 Migration

**declarative_base → DeclarativeBase**: Replace `Base = declarative_base()` with `class Base(DeclarativeBase): pass`. _(reference service)_

**Column → Mapped/mapped_column**: Replace `id = Column(UUID(as_uuid=True), primary_key=True)` with `id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)`. _(reference service)_

**Optional types**: Use `Mapped[Optional[str]]` or `Mapped[str | None]` for nullable columns instead of `Column(..., nullable=True)`. _(reference service)_

**Query → select()**: Replace `session.query(Model).filter(...)` with `session.execute(select(Model).where(...))` + `.scalars().all()`. _(reference service)_

**Relationship type hints**: Add type annotation `users: Mapped[list["User"]] = relationship(...)` instead of untyped `users = relationship(...)`. _(reference service)_

**When to use**: All new services use SQLAlchemy 2.0; legacy services remain on 1.4 until migration. Use the reference service as the golden pattern for 2.0 Mapped style.

### Shared Internal Library Extraction

**Duplicated core files**: The following files are copy-pasted across multiple services with minor drift: `core/dao.py` (BaseDao: ~400 lines), `core/connection_handler.py` (ConnectionHandler), `app/routing.py` (CustomRequestRoute), `core/exceptions.py`, `core/decorators.py`. _(legacy services share ~90% identical code)_

**Extraction strategy**: Create an internal shared library package (e.g., `backend-common`) containing BaseDao, ConnectionHandler, routing utilities, and standardized exception classes. _(the cleanest reference service does not have duplicated core/ because it was built after this pattern was recognized)_

**Version the shared library**: Pin to semantic versioning (`backend-common==1.2.3`) so services can upgrade incrementally without forced coupling. _(prevents all-services-must-upgrade-at-once)_

**Lazy migration**: New services depend on the shared library from day 1; existing services migrate during refactors. Avoid a big-bang rewrite. _(pragmatic rollout)_

**What to extract**: BaseDao (CRUD + pagination), ConnectionHandler (session/redis/event-emitter lifecycle), CustomRequestRoute (request ID injection), standard exceptions (NotFoundError, ValidationError), decorators (retry, circuit-breaker). _(observed in legacy services' core/)_

**What to keep service-local**: Domain DAOs (inherit from shared BaseDao), domain models, business logic, service-specific routing. _(only core infrastructure goes shared)_

### Golden Reference Template

**Reference service pattern**: Use the cleanest reference service as the canonical example for new services: Pydantic v2, SQLAlchemy 2.0 Mapped, async FastAPI, structured logging, connection lifecycle, RLS tenant isolation. _(the reference service is the cleanest modern codebase)_

**Project structure**: `app/database.py` (Base), `app/dao.py` (BaseDao), `app/connection.py` (ConnectionHandler), `domain/v1/entity/{models,serializers,dao,views}.py`. _(reference service pattern)_

**Avoid legacy patterns**: Do not copy legacy service patterns into new services; they use deprecated Pydantic v1 / SQLAlchemy 1.4 and have divergent core/ copies. _(anti-pattern)_

## Skeleton / example

```python
# Pydantic v1 (legacy services)
from pydantic import BaseModel, validator

class ShipmentSchema(BaseModel):
    contact_email: str
    
    @validator('contact_email', pre=True)
    def validate_email(cls, v):
        if not v or '@' not in v:
            raise ValueError('Invalid email')
        return v
    
    class Config:
        orm_mode = True

# Pydantic v2 (modern reference service)
from pydantic import BaseModel, ConfigDict, field_validator

class OrgOut(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    
    model_config = ConfigDict(from_attributes=True)
    
    @field_validator('slug')
    @classmethod
    def validate_slug(cls, v: str) -> str:
        if not re.match(r'^[a-z0-9][a-z0-9-]*[a-z0-9]$', v):
            raise ValueError('Invalid slug format')
        return v

# SQLAlchemy 1.4 (legacy services)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import Column, String, Integer

Base = declarative_base()

class Partner(Base):
    __tablename__ = 'partners'
    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)

# SQLAlchemy 2.0 (modern reference service)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import String

class Base(DeclarativeBase):
    pass

class Organization(Base):
    __tablename__ = 'organizations'
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    parent_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey('organizations.id'), nullable=True
    )

# Shared library extraction (before - duplicated across services)
# File: service_a/core/dao.py (~400 lines)
# File: service_b/core/dao.py (~400 lines, with drift)
# File: service_c/app/dao.py (~370 lines, variant)

# Shared library extraction (after - backend-common package)
# In backend-common/backend_common/dao.py:
class BaseDao:
    def __init__(self, session: AsyncSession, db_model):
        self.session = session
        self.db_model = db_model
    
    async def create(self, create_object_dict=None, **create_kwargs):
        orm_object = self.add_object(create_object_dict, **create_kwargs)
        await self._commit()
        return orm_object
    
    async def get_paginated_response(
        self, query: Select, page_size: int = 20, page_number: int = 1, ...
    ) -> tuple[list, dict]:
        # Standardized pagination across all services
        ...

# In service (e.g., myservice):
# requirements.txt: backend-common==1.2.3
from backend_common.dao import BaseDao
from backend_common.connection import ConnectionHandler

# Service-specific DAO inherits from shared BaseDao
class PartnerDao(BaseDao):
    def __init__(self, session: AsyncSession):
        super().__init__(session, Partner)
    
    # Domain-specific methods only
    async def get_active_partners_by_region(self, region: str):
        ...
```

## Anti-patterns to avoid

- **Mixing Pydantic v1 and v2 in the same service** — pick one version and be consistent; do not use `orm_mode` and `from_attributes` in the same codebase.
- **Using declarative_base() in new services** — new services must use DeclarativeBase (SQLAlchemy 2.0).
- **Copying core/ directory from legacy services** — legacy core/ is deprecated; extract to shared library or use the reference service pattern.
- **Big-bang shared library migration** — do not force all services to upgrade at once; allow incremental adoption.
- **Putting domain logic in shared library** — only core infrastructure (BaseDao, ConnectionHandler) goes shared; keep domain DAOs and models service-local.
- **Ignoring the reference service** — when creating new services, copy the reference service's structure (not legacy patterns).
- **Using Query API in new code** — SQLAlchemy 2.0 deprecates `session.query()`; use `select()` statements.

## References

- [pydantic-v1-to-v2.md](./references/pydantic-v1-to-v2.md) — Detailed Pydantic migration guide with before/after examples
- [sqlalchemy-14-to-20.md](./references/sqlalchemy-14-to-20.md) — SQLAlchemy migration patterns (declarative_base, Mapped, select)
- [shared-internal-library.md](./references/shared-internal-library.md) — Extraction strategy, what to share, version management
- [migration-best-practices.md](./references/migration-best-practices.md) — Step-by-step migration process, common pitfalls, testing strategy, rollback plans
- [repo-evidence.md](./references/repo-evidence.md) — Real file paths and code snippets proving each pattern
