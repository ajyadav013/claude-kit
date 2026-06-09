# Code Structure & Conventions

Codified patterns extracted from the existing codebase. All new code must follow these established conventions.

## 1. Backend Module Layout

Every domain module follows a consistent structure. Example for a layered web service:

```
backend/<domain>/
├── __init__.py          # Module docstring + exports
├── models.py            # Data models (ORM entities, domain objects)
├── schemas.py           # Request/response schemas (Create, Read, Update)
├── repository.py        # Data Access Object — database operations
├── service.py           # Business logic (service layer)
├── handlers.py          # HTTP handler functions (thin — delegates to service)
└── routes.py            # URL-to-handler wiring (if separate from handlers)
```

### Naming Conventions (Adapt to Your Stack)
| Layer | File Name | Purpose |
|-------|-----------|---------|
| Models | `models.py` / `entities.py` | Domain entities, ORM models, data structures with cross-cutting mixins |
| Schemas | `schemas.py` / `serializers.py` / `dtos.py` | Typed request/response schemas (Create, Read, Update) |
| Repository | `repository.py` / `dao.py` | Data access — extends base repository pattern for CRUD |
| Service | `service.py` / `helpers.py` | Business logic (orchestration, validation, authorization) |
| Handlers | `handlers.py` / `views.py` / `controllers.py` | HTTP request handlers (thin — delegates to service) |
| Routes | `routes.py` / `router.py` | URL-to-handler registration |

### Rules
- New domains must follow this layout exactly
- Repository layer extends a base repository/DAO for standard CRUD operations
- Handler functions must be thin — no business logic, delegate to service layer
- Schema files must separate Create/Read/Update schemas — never mix request and response
- Models must use established cross-cutting mixins (timestamps, soft-delete, audit)

---

## 2. Base Repository Pattern

All repository classes extend a base repository which provides standard CRUD:

```
class BaseRepository:
    session: <DatabaseSession>
    model: type

    def __init__(self, session, model): ...

    # Available methods:
    async def create(self, create_object_dict) -> T: ...
    async def get_by_id(self, id_value) -> T | None: ...
    async def update(self, id_value, update_values_dict) -> ...: ...
    async def delete(self, id_value) -> bool: ...  # soft-delete aware
    async def find_by(self, **kwargs) -> Sequence[T]: ...
    async def paginate(self, query, page_size, page_number, sort_by, order_by) -> tuple[list[T], dict]: ...
    async def bulk_insert(self, create_objects_list) -> list[T]: ...
    async def bulk_update(self, update_objects_list, id_field_name) -> None: ...
```

### Rules
- Never bypass the base repository for standard operations — use its methods
- Domain-specific queries go in the domain repository as additional methods
- Query execution helper handles rollback on error — always use it for raw queries
- `delete` auto-detects soft-delete mixin — never manually set `is_deleted`
- `paginate` returns `tuple[list[T], pagination_dict]` — use this pattern consistently

---

## 3. Model Mixins

All models use established mixins for cross-cutting concerns:

```
class TimestampMixin:    # adds created_at, updated_at
class SoftDeleteMixin:   # adds is_deleted: bool, deleted_at
class AuditMixin:        # adds created_by, updated_by
```

### Rules
- Every domain model must use timestamp mixin
- Models that need soft delete must use soft-delete mixin
- Always filter `is_deleted == False` in queries for soft-delete models
- Never add duplicate timestamp/delete/audit columns — use the mixins
- New cross-cutting concerns → create a new mixin in the common/shared module

---

## 4. Request-Scoped Resource Management

Request-scoped connection/session management via dependency injection:

```
class ResourceManager:   # Singleton — database engine + cache client
class RequestHandler:    # Per-request — lazy session + cache
    @property session -> <DatabaseSession>
    @property cache -> <CacheClient>
    async def commit() -> None
    async def close() -> None

async def get_request_handler() -> AsyncGenerator[RequestHandler, None]:
    # Framework dependency — yields handler, closes on teardown
```

### Rules
- Inject `RequestHandler` via the framework's dependency injection mechanism
- Access `handler.session` and `handler.cache` — never create sessions directly
- Never instantiate `ResourceManager` directly in handlers — it's a singleton
- Pass `handler.session` to repository constructors

---

## 5. Response Envelope

All API responses use a standardized envelope:

```
class ResponseEnvelope:
    success: bool
    data: Any
    message: str
    errors: list

    @classmethod ok(cls, data=None, message="Success") -> ResponseEnvelope
    @classmethod error(cls, errors=None, message="Error") -> ResponseEnvelope
```

### Rules
- Always return `ResponseEnvelope.ok(data=..., message=...)` for success
- Always return `ResponseEnvelope.error(errors=[...], message=...)` for handled errors
- Never return raw dicts or plain strings from handlers
- Keep `data` typed in the handler's response schema — don't just use the envelope

---

## 6. Auth & Permission Dependencies

The established dependency chain for authentication and authorization:

```
get_current_session(request, handler)    → dict (session data)
  └─ require_auth(request, handler)      → dict (validated session)
       ├─ require_admin(session)         → dict (admin only)
       ├─ require_role(role)(session)    → dict (role-restricted)
       └─ require_tenant_access(session) → dict (tenant-scoped)

# Tenant/authorization access checks (for multi-tenant systems):
assert_same_tenant(session, target_tenant_id)      → None or raises 403
assert_tenant_access(session, target_tenant_id, h) → None or raises 403 (hierarchy-aware)

# Extractors:
get_caller_tenant_id(session)   → ID | None
get_caller_user_id(session)     → ID | None
get_caller_role(session)        → str
is_admin(session)               → bool
```

### Rules
- Use `require_auth` dependency for authenticated endpoints
- Use the appropriate role dependency for role-restricted endpoints
- Use tenant access checks for hierarchy-aware authorization scoping (if applicable)
- Never implement custom session parsing — use the established chain
- Never bypass the dependency chain with direct cache/session reads

---

## 7. Settings Pattern

Single configuration object from a centralized settings module:

```
from config.settings import settings

settings.DATABASE_URL
settings.CACHE_URL
settings.SESSION_COOKIE_NAME
# etc.
```

### Rules
- All configuration via the centralized settings module — never environment variable access scattered throughout code
- Add new env vars to the settings class with type + default
- Update `.env.example` and README.md when adding new settings
- Access via centralized import — never re-instantiate

---

## 8. Health Check Pattern

Standard health endpoints for orchestration:

```
GET /_healthz  → liveness probe (always 200)
GET /_readyz   → readiness probe (checks DB + cache, 200 or 503)
```

### Rules
- Never modify the health check paths — they're infrastructure contracts
- Add new dependency checks (external APIs, etc.) to readiness probe only
- Never add auth to health endpoints
- Return 503 with degraded service info — not 500

---

## 9. Enum Pattern for Roles & Statuses

Constrained string fields use enums:

```
class UserRole(str, enum.Enum):
    ADMIN = "admin"
    EDITOR = "editor"
    VIEWER = "viewer"
```

### Rules
- All constrained string fields must use enums — never bare strings
- Enum values follow project naming convention (e.g., snake_case or lowercase)
- Use ORM-specific enum mapping for database columns
- Add new roles/statuses to the existing enum — never create parallel string constants

---

## 10. Frontend Structure

Frontend code follows a consistent module structure. Example for a component-based UI:

```
frontend/src/
├── assets/        # Static assets (images, fonts)
├── components/    # Reusable UI components
├── lib/           # Shared utilities (API client, helpers)
├── pages/         # Route-level page components
├── stores/        # Client state stores
├── types/         # Shared type definitions
├── App.*          # Root component with router
└── main.*         # Entry point
```

### Rules
- Pages own data fetching — components are presentational
- One state store per domain/concern
- Shared HTTP client in `lib/` — centralized for error handling, auth
- Types shared across pages go in `types/` — component-local types stay in the component file
- Route configuration lives in root component

---

## 11. Import Order

### Backend (example: Python)
```python
# 1. Standard library
import uuid
from datetime import datetime

# 2. Third-party
from <web-framework> import Router, Depends
from <orm> import Session

# 3. First-party (app/ and config/)
from app.connection import RequestHandler
from config.settings import settings

# 4. Domain-local
from <project>.common.dependencies import require_auth
from <project>.identity.models import User
```

### Frontend (example: TypeScript)
```typescript
// 1. Framework (if applicable)
import { useState, useEffect } from "<framework>";

// 2. Third-party
import { useNavigate } from "<router>";
import toast from "<toast-lib>";

// 3. Internal (alias or absolute)
import { api } from "@/lib/api";
import { useAuthStore } from "@/stores/authStore";

// 4. Relative
import { UserCard } from "./UserCard";

// 5. Type-only imports
import type { User } from "@/types/user";
```

---

## 12. Error Handling Pattern

### Backend
```
from <framework>.exceptions import HTTPException
from <framework>.status import NOT_FOUND, CONFLICT

# In service layer:
if not user:
    raise HTTPException(status_code=NOT_FOUND, detail="User not found")

if existing:
    raise HTTPException(status_code=CONFLICT, detail="Resource already exists")
```

### Rules
- Raise HTTP exceptions in service layer — never in repository
- Repository returns `None` for not-found — service decides the error
- Use framework status constants — never magic numbers
- `detail` is a user-facing string — never expose internal errors
- Never catch and swallow exceptions silently
