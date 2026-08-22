# Shared Internal Library Extraction

Strategy for extracting duplicated core infrastructure into a shared internal library (e.g., `backend-common`).

## The Duplication Problem

Across multiple microservices, the following core infrastructure files are copy-pasted with minor drift:

**Duplicated files observed:**
- `core/dao.py` — BaseDao, RedisConnectionWrapper, RedisPipeline (~400 lines)
- `core/connection_handler.py` — ConnectionHandler managing session/redis/kafka lifecycle (~80 lines)
- `core/connection_manager.py` — ConnectionManager for DB pool setup (~150 lines)
- `app/routing.py` — CustomRequestRoute for request ID injection and logging (~100 lines)
- `core/exceptions.py` — Standard exceptions (NotFoundError, ValidationError, etc.)
- `core/decorators.py` — Retry, circuit-breaker, cache decorators

**Evidence of duplication:**
- service-a: `core/{dao.py, connection_handler.py, connection_manager.py, decorators.py, exceptions.py, sqlalchemy.py, system_lifecycle.py, date_utils.py, aiohttprequest.py}`
- service-b: `core/{dao.py, connection_handler.py, connection_manager.py, decorators.py, exceptions.py, sqlalchemy.py, system_lifecycle.py, date_utils.py, aiohttprequest.py}`
- service-c: `app/{dao.py, connection.py, routing.py, database.py, lifetime.py, utils.py}`
- And multiple other services

**Drift observed:**
- Some services have nearly identical `core/dao.py` but with minor differences
- Some have variant `app/dao.py` with different method signatures
- Each service maintains its own version, so bug fixes and improvements don't propagate

**Why the reference service doesn't have duplicated core/:**
The cleanest reference service was built after this duplication problem was recognized, so it uses a cleaner app/ structure without a duplicated core/ directory.

## Extraction Strategy

### 1. Create Shared Library Package

**Package name:** `backend-common` (or similar)

**Structure:**
```
backend-common/
├── pyproject.toml          # Semantic versioning: 1.0.0, 1.1.0, 2.0.0, ...
├── README.md
├── backend_common/
│   ├── __init__.py
│   ├── dao.py              # BaseDao, RedisConnectionWrapper, RedisPipeline
│   ├── connection.py       # ConnectionHandler
│   ├── pool.py             # ConnectionManager
│   ├── routing.py          # CustomRequestRoute
│   ├── exceptions.py       # Standard exception classes
│   ├── decorators.py       # retry, circuit_breaker, cache
│   ├── date_utils.py       # Date utility functions
│   └── http.py             # Async HTTP request wrappers
└── tests/
    └── ...
```

### 2. What to Extract (Core Infrastructure)

**Must extract:**
- `BaseDao` — CRUD operations, pagination, bulk insert/update, soft-delete support
- `RedisConnectionWrapper` — Read-only/read-write connection separation, key tracking
- `RedisPipeline` — Redis pipeline wrapper
- `ConnectionHandler` — Lifecycle management for session/redis/kafka connections
- `ConnectionManager` — DB pool creation and configuration
- `CustomRequestRoute` — Request ID injection, structured logging
- Standard exceptions — `NotFoundError`, `ValidationError`, `UnauthorizedError`, etc.
- Decorators — `@retry`, `@circuit_breaker`, `@cache` (if standardized)

**Examples from legacy services:**
```python
# backend_common/dao.py
class BaseDao:
    def __init__(self, session: AsyncSession, db_model):
        self.session = session
        self.db_model = db_model
    
    async def create(self, create_object_dict=None, **create_kwargs):
        ...
    
    async def get_paginated_response(
        self, query: Select, page_size: int = 20, page_number: int = 1, ...
    ) -> tuple[list, dict]:
        ...
    
    async def bulk_insert(self, create_objects_list: List[Dict]) -> List:
        ...

class RedisConnectionWrapper:
    def __init__(self, read_only_pool=None, read_write_pool=None):
        ...
    
    async def get(self, key):
        ...
    
    async def set(self, key, value, ex=None):
        ...

# backend_common/connection.py
class ConnectionHandler:
    def __init__(self, connection_manager=None, event_bridge=None):
        self._session = None
        self._redis_connection = None
        self._event_emitter = None
    
    @property
    def session(self):
        return self._session or self._get_session()
    
    async def close(self):
        if self._session:
            await self._session.close()

# backend_common/routing.py
class CustomRequestRoute(APIRoute):
    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get('X-Request-ID') or str(uuid.uuid4())
        # ... structured logging with request_id
        response = await call_next(request)
        response.headers['X-Request-ID'] = request_id
        return response
```

### 3. What to Keep Service-Local (Domain Layer)

**Do NOT extract:**
- Domain-specific DAOs (e.g., `PartnerDao`, `ShipmentDao`, `TenantDao`)
- Domain models (e.g., `Partner`, `Shipment`, `Tenant`)
- Business logic and services
- API routers and views
- Domain-specific serializers/schemas
- Migration files

**Why:**
- Domain logic varies per service
- Services evolve independently
- Shared library should only contain reusable infrastructure

### 4. Versioning and Adoption

**Semantic versioning:**
- `1.0.0` — Initial stable release (BaseDao, ConnectionHandler, routing)
- `1.1.0` — Add new feature (e.g., soft-delete support in BaseDao)
- `1.2.0` — Add Redis cluster support
- `2.0.0` — Breaking change (e.g., SQLAlchemy 2.0 migration, requires code changes)

**Incremental adoption:**
- **Phase 1**: Publish `backend-common==1.0.0` with BaseDao, ConnectionHandler, routing
- **Phase 2**: New services adopt from day 1 (add `backend-common==1.0.0` to requirements.txt)
- **Phase 3**: Existing services migrate during refactors (not forced upgrade)
- **Phase 4**: Retire legacy core/ directories after all services migrate

**Example requirements.txt:**
```
# New service (immediate adoption)
backend-common==1.2.3
fastapi==0.104.1
sqlalchemy[asyncio]==2.0.23
pydantic==2.5.0
...

# Legacy service (gradual migration)
# backend-common==1.2.3  # TODO: Migrate core/ to shared library
fastapi==0.95.0
sqlalchemy==1.4.47
pydantic==1.10.7
...
```

### 5. Migration Path for Existing Services

**Step 1: Install shared library**
```bash
pip install backend-common==1.0.0
```

**Step 2: Replace imports**
```python
# Before (service-local)
from core.dao import BaseDao
from core.connection_handler import ConnectionHandler
from app.routing import CustomRequestRoute

# After (shared library)
from backend_common.dao import BaseDao
from backend_common.connection import ConnectionHandler
from backend_common.routing import CustomRequestRoute
```

**Step 3: Update service-specific DAOs**
```python
# Before
from core.dao import BaseDao

class PartnerDao(BaseDao):
    def __init__(self, session: AsyncSession):
        super().__init__(session, Partner)

# After
from backend_common.dao import BaseDao

class PartnerDao(BaseDao):
    def __init__(self, session: AsyncSession):
        super().__init__(session, Partner)
    
    # Service-specific methods only
    async def get_active_partners_by_region(self, region: str):
        ...
```

**Step 4: Remove duplicated core/ files**
```bash
# After migration and testing, remove local copies
rm -rf core/dao.py core/connection_handler.py app/routing.py
```

**Step 5: Pin version and test**
```bash
# Run full test suite
pytest

# Update requirements.txt with pinned version
echo "backend-common==1.0.0" >> requirements.txt
```

### 6. Handling Divergent Versions

**Problem:** Legacy services have slightly different DAO implementations.

**Solution:** 
1. Identify the **union** of all methods across all services
2. Implement the union in the shared library with feature flags or optional parameters
3. Mark deprecated variants with `@deprecated` decorator
4. Document migration path for each variant

**Example:**
```python
# backend_common/dao.py (union of all variants)
class BaseDao:
    async def get_paginated_response(
        self,
        query: Select,
        page_size: int = 20,
        page_number: int = 1,
        sort_by: str | None = None,
        order_by: str | None = None,
        count_field: object | None = None,  # variant A
        count_query: object | None = None,  # variant B
    ) -> tuple[list, dict]:
        """
        Pagination with optional sorting and custom count query.
        
        Args:
            count_field: Override count field (variant A)
            count_query: Custom count query (variant B)
        """
        # Implement union logic
        ...
```

## Benefits

1. **Consistency**: All services use the same BaseDao, ConnectionHandler, routing logic
2. **Bug fixes propagate**: Fix a bug in BaseDao once, all services benefit
3. **Easier onboarding**: New developers learn one pattern, not 12 variants
4. **Testing**: Shared library has its own test suite
5. **Incremental adoption**: Services upgrade when ready, not forced

## Anti-Patterns to Avoid

- **Big-bang migration**: Do not force all services to migrate at once
- **Domain logic in shared lib**: Keep domain DAOs service-local
- **Breaking changes without major version bump**: Use semantic versioning
- **Tight coupling**: Services should pin to a specific version, not `backend-common>=1.0.0`
- **Copying core/ from legacy services**: Use the reference service pattern for new services, not legacy patterns

## Reference Service Approach (No Duplication)

The reference service avoided this problem by:
1. Using a clean `app/` structure without a duplicated `core/` directory
2. Defining BaseDao/ConnectionHandler directly in `app/dao.py` and `app/connection.py`
3. Not copying from legacy services

**Reference service structure:**
```
backend/
├── app/
│   ├── database.py         # DeclarativeBase
│   ├── dao.py              # BaseDao (no duplication, service-local)
│   ├── connection.py       # ConnectionHandler (service-local)
│   ├── routing.py          # CustomRequestRoute (service-local)
│   └── ...
└── identity/v1/
    ├── organization/{models,serializers,dao,views}.py
    └── tenant/{models,serializers,dao,views}.py
```

**Why the reference service doesn't need extraction:**
The reference service was built after the duplication problem was recognized, so it has clean infrastructure without copy-paste. However, **future new services should still use the shared library** to avoid re-introducing the problem.

## Recommendation

1. **Immediate**: Create `backend-common==1.0.0` with BaseDao, ConnectionHandler, routing
2. **Phase 1**: New services adopt from day 1
3. **Phase 2**: Migrate 2-3 high-traffic services as proof-of-concept
4. **Phase 3**: Gradual migration of remaining services during refactors
5. **Phase 4**: Retire legacy core/ directories after all services migrate

**Current status:** The shared library approach is a **recommendation** based on observed duplication across multiple services.
