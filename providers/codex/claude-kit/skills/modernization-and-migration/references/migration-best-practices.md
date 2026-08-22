# Migration Best Practices and Common Pitfalls

Practical guidance for executing Pydantic v1→v2 and SQLAlchemy 1.4→2.0 migrations safely, derived from comparing legacy services against modern reference services.

## Pre-Migration Preparation

### 1. Audit Current Dependencies

**Check your current versions:**
```bash
pip freeze | grep -E "pydantic|sqlalchemy|alembic"
```

**Expected legacy cohort versions:**
- `pydantic==1.10.x`
- `sqlalchemy==1.4.x`
- `alembic==1.7.x` or lower

**Target modern versions:**
- `pydantic>=2.0,<3.0`
- `pydantic-settings>=2.0` (NEW dependency)
- `sqlalchemy>=2.0,<3.0`
- `alembic>=1.8` (required for SQLAlchemy 2.0 Mapped support)

### 2. Establish Test Coverage Baseline

**Before starting migration:**
```bash
# Run full test suite to establish baseline
pytest --cov=. --cov-report=html

# Document current test coverage percentage
# Target: >80% coverage before migration
```

**Why:** Migrations introduce subtle breakages that only tests catch. Without strong coverage, you'll discover issues in production.

### 3. Create a Compatibility Matrix

**Document what needs upgrading:**
| Service | Pydantic | SQLAlchemy | Alembic | Status |
|---------|----------|------------|---------|--------|
| service-a | 1.10.7 | 1.4.47 | 1.7.5 | Legacy |
| service-b | 1.10.7 | 1.4.47 | 1.7.5 | Legacy |
| service-c | 1.10.7 | 1.4.47 | 1.7.5 | Legacy |
| reference | 2.5.0 | 2.0.23 | 1.12.1 | Modern |

## Migration Strategy

### Option 1: Incremental Service-by-Service (Recommended)

**Approach:**
1. Start with a low-traffic service
2. Complete full migration (Pydantic + SQLAlchemy)
3. Deploy to staging, monitor for 1 week
4. Deploy to production, monitor for 1 week
5. Repeat for next service

**Pros:**
- Risk isolated to one service
- Learn migration pitfalls early
- Can roll back easily

**Cons:**
- Slower overall timeline
- Services on different versions

**Best for:** Large organizations with 10+ microservices

### Option 2: Feature-Branch Parallel Migration

**Approach:**
1. Create migration feature branch
2. Update dependencies in requirements.txt
3. Migrate all code in branch
4. Run full test suite
5. Merge when all tests pass

**Pros:**
- Faster timeline
- All changes in one PR
- Clear before/after comparison

**Cons:**
- Higher risk
- Harder to debug failures
- Large changeset to review

**Best for:** Smaller services with <20 domain modules

### Option 3: Big-Bang Multi-Service Migration (NOT Recommended)

**Approach:**
Upgrade all services at once.

**Why NOT recommended:**
- High risk of production breakage
- Difficult to isolate root cause of failures
- No rollback path if issues discovered after deployment
- Requires coordinated multi-service deployment

**Only use if:** You have comprehensive integration tests and a strong rollback plan.

## Step-by-Step Migration Process

### Phase 1: Pydantic v1 → v2

**Step 1: Install pydantic-settings**
```bash
# Add to requirements.txt
pydantic-settings>=2.0,<3.0
```

**Step 2: Update imports (automated with regex)**
```python
# Find all BaseSettings imports
rg "from pydantic import.*BaseSettings" --files-with-matches

# Replace with pydantic_settings import
# Before: from pydantic import BaseSettings
# After:  from pydantic_settings import BaseSettings, SettingsConfigDict
```

**Step 3: Migrate validators (semi-automated)**
```python
# Find all @validator decorators
rg "@validator" --files-with-matches

# Manual replacement required:
# Before: @validator('field_name', pre=True)
# After:  @field_validator('field_name', mode='before')
#         @classmethod
```

**Step 4: Migrate Config classes (semi-automated)**
```python
# Find all inner Config classes
rg "class Config:" --context 5

# Manual replacement:
# Before: class Config: orm_mode = True
# After:  model_config = ConfigDict(from_attributes=True)
```

**Step 5: Run tests after each file**
```bash
# Migrate one file at a time, test immediately
pytest tests/test_schemas.py -v
```

### Phase 2: SQLAlchemy 1.4 → 2.0

**Step 1: Update Base declaration**
```python
# File: app/database.py or core/sqlalchemy.py
# Before:
from sqlalchemy.ext.declarative import declarative_base
Base = declarative_base()

# After:
from sqlalchemy.orm import DeclarativeBase

class Base(DeclarativeBase):
    """Root declarative base for all ORM models."""
    pass
```

**Step 2: Migrate model columns (most time-consuming)**
```python
# Find all model files
rg "class.*\(Base\)" --files-with-matches

# For each model file, replace Column with Mapped:
# Before: id = Column(UUID(as_uuid=True), primary_key=True)
# After:  id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)

# Add imports:
from sqlalchemy.orm import Mapped, mapped_column
from typing import Optional
import uuid
```

**Step 3: Migrate relationships**
```python
# Add type hints to relationships:
# Before: users = relationship('User', back_populates='organization')
# After:  users: Mapped[list["User"]] = relationship('User', back_populates='organization')
```

**Step 4: Migrate DAO queries (BaseDao and domain DAOs)**
```python
# Find all session.query() calls
rg "session\.query\(" --files-with-matches

# Replace with select() + execute():
# Before: orgs = session.query(Organization).filter(Organization.active == True).all()
# After:  stmt = select(Organization).where(Organization.active == True)
#         result = await session.execute(stmt)
#         orgs = result.scalars().all()
```

**Step 5: Update Alembic**
```bash
# Upgrade Alembic to 1.8+ for SQLAlchemy 2.0 support
pip install "alembic>=1.8,<2.0"

# Regenerate migrations (optional, if Alembic complains)
alembic revision --autogenerate -m "Regenerate after SQLAlchemy 2.0 migration"
```

**Step 6: Test migrations**
```bash
# Test Alembic migrations work
alembic upgrade head
alembic downgrade -1
alembic upgrade head

# Run full test suite
pytest --cov=. -v
```

## Common Pitfalls and Solutions

### Pitfall 1: Mixing Pydantic v1 and v2 Patterns

**Problem:**
```python
# WRONG: Mixed v1 and v2
class UserOut(BaseModel):
    id: uuid.UUID
    email: str
    
    @validator('email', pre=True)  # v1 pattern
    def validate_email(cls, v):
        return v.lower()
    
    model_config = ConfigDict(from_attributes=True)  # v2 pattern
```

**Solution:**
Pick one version and be consistent:
```python
# CORRECT: Pure v2
class UserOut(BaseModel):
    id: uuid.UUID
    email: str
    
    @field_validator('email', mode='before')
    @classmethod
    def validate_email(cls, v: str) -> str:
        return v.lower()
    
    model_config = ConfigDict(from_attributes=True)
```

### Pitfall 2: Forgetting @classmethod on field_validator

**Problem:**
```python
# WRONG: Missing @classmethod
@field_validator('email')
def validate_email(cls, v: str) -> str:  # RuntimeError at startup
    return v.lower()
```

**Solution:**
```python
# CORRECT: Add @classmethod
@field_validator('email')
@classmethod
def validate_email(cls, v: str) -> str:
    return v.lower()
```

### Pitfall 3: Wrong Result Extraction from select() Queries

**Problem:**
```python
# WRONG: Missing .scalars()
stmt = select(Organization).where(Organization.active == True)
result = await session.execute(stmt)
orgs = result.all()  # Returns Row objects, not Organization instances!
```

**Solution:**
```python
# CORRECT: Use .scalars().all()
stmt = select(Organization).where(Organization.active == True)
result = await session.execute(stmt)
orgs = result.scalars().all()  # Returns Organization instances
```

### Pitfall 4: Nullable Columns Without Optional

**Problem:**
```python
# WRONG: Mapped[str] but column is nullable
description: Mapped[str] = mapped_column(Text, nullable=True)
# SQLAlchemy type checker will complain
```

**Solution:**
```python
# CORRECT: Use Mapped[Optional[str]] or Mapped[str | None]
description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
# OR (Python 3.10+)
description: Mapped[str | None] = mapped_column(Text, nullable=True)
```

### Pitfall 5: Alembic Not Detecting Mapped Changes

**Problem:**
After migrating Column → Mapped, `alembic revision --autogenerate` shows no changes, but runtime fails.

**Solution:**
Alembic < 1.8 doesn't understand Mapped syntax. Upgrade Alembic:
```bash
pip install "alembic>=1.8"
```

### Pitfall 6: Using .dict() Instead of .model_dump()

**Problem:**
```python
# WRONG: .dict() is deprecated in Pydantic v2
user_dict = user_schema.dict()  # DeprecationWarning
```

**Solution:**
```python
# CORRECT: Use .model_dump() in v2
user_dict = user_schema.model_dump()
```

### Pitfall 7: Lazy Loading Breaks with async

**Problem:**
```python
# WRONG: Accessing relationship without explicit loading
org = await session.execute(select(Organization).where(Organization.id == org_id))
org = org.scalar_one()
users = org.users  # LazyLoadError: greenlet_spawn has not been patched
```

**Solution:**
Use explicit loading (selectinload, joinedload) or set `lazy='raise'`:
```python
# Option 1: Explicit loading
from sqlalchemy.orm import selectinload

stmt = select(Organization).where(Organization.id == org_id).options(
    selectinload(Organization.users)
)
result = await session.execute(stmt)
org = result.scalar_one()
users = org.users  # Now loaded

# Option 2: Force explicit loading (reference service pattern)
class Organization(Base):
    users: Mapped[list["User"]] = relationship(
        'User', 
        back_populates='organization',
        lazy='raise',  # Forces explicit loading
    )
```

## Testing Strategy

### Unit Tests

**Before migration:**
```python
# Ensure all schemas and models are covered
pytest tests/test_schemas.py tests/test_models.py -v --cov
```

**During migration:**
```python
# Test each migrated file immediately
pytest tests/test_schemas.py::TestUserSchema -v
```

**After migration:**
```python
# Full test suite must pass
pytest --cov=. --cov-report=html -v
# Target: same or higher coverage than pre-migration baseline
```

### Integration Tests

**Database interactions:**
```python
# Test CRUD operations
async def test_create_organization():
    org = await org_dao.create(name="Test Org", slug="test-org")
    assert org.id is not None
    assert org.name == "Test Org"

# Test pagination
async def test_paginated_organizations():
    orgs, meta = await org_dao.get_paginated_response(
        select(Organization), page_size=10, page_number=1
    )
    assert len(orgs) <= 10
    assert "total" in meta
```

**API endpoint tests:**
```python
# Test FastAPI endpoints with new schemas
def test_create_organization_api(client):
    response = client.post("/v1/organizations", json={
        "name": "Test Org",
        "slug": "test-org",
    })
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Test Org"
```

## Rollback Plan

### If Migration Fails in Production

**Immediate rollback:**
```bash
# 1. Revert to previous Docker image or Git commit
git revert <migration-commit-sha>

# 2. Redeploy previous version
kubectl rollout undo deployment/service-name

# 3. Verify service health
curl https://service.example.com/health
```

**Database migrations:**
```bash
# If Alembic migrations were applied, downgrade
alembic downgrade -1
```

### Preventing Rollback Scenarios

1. **Deploy to staging first** — catch issues before production
2. **Use feature flags** — gradual rollout of migrated code paths
3. **Monitor error rates** — alert on increased 5xx errors
4. **Canary deployment** — deploy to 10% of instances first

## Timeline and Effort Estimation

**Small service (5-10 domain modules):**
- Pydantic v1→v2: 2-3 days
- SQLAlchemy 1.4→2.0: 3-5 days
- Testing and fixes: 2-3 days
- **Total: 1-2 weeks**

**Medium service (10-20 domain modules):**
- Pydantic v1→v2: 4-5 days
- SQLAlchemy 1.4→2.0: 5-7 days
- Testing and fixes: 3-5 days
- **Total: 2-3 weeks**

**Large service (30-40 domain modules):**
- Pydantic v1→v2: 1 week
- SQLAlchemy 1.4→2.0: 2 weeks
- Testing and fixes: 1 week
- **Total: 4-6 weeks**

## Post-Migration Checklist

- [ ] All tests pass (unit + integration)
- [ ] Test coverage matches or exceeds pre-migration baseline
- [ ] Alembic migrations work (upgrade/downgrade)
- [ ] No deprecation warnings in logs
- [ ] API endpoints return correct data types
- [ ] ORM relationships load correctly
- [ ] Pagination works as expected
- [ ] Performance metrics unchanged (latency, throughput)
- [ ] Documentation updated (README, API docs)
- [ ] Dependencies pinned in requirements.txt
- [ ] Deployed to staging and monitored for 1 week
- [ ] Deployed to production with canary rollout

## Reference Service as the Golden Pattern

When in doubt during migration, refer to the reference service for the correct modern pattern:
- **Pydantic v2:** `app/identity/v1/organization/serializers.py`
- **SQLAlchemy 2.0:** `app/identity/v1/organization/models.py`
- **BaseDao:** `app/dao.py`
- **Settings:** `config/settings.py`

The reference service is the cleanest, most complete example for the modern stack.
