# API Versioning and Conditional Route Registration

Patterns for URL-prefix API versioning (`/v1.0`, `/v2.0`) and conditional router inclusion based on server type or deployment configuration.

## URL-prefix versioning

URL-prefix versioning embeds the API version in the path (`/v1.0/resource`, `/v2.0/resource`) and is the most explicit, client-friendly versioning strategy. It plays well with OpenAPI schemas, API gateways, and HTTP routing.

### Pattern: Versioned APIRouter

Create a top-level versioned router with `APIRouter(prefix="/v1.0")` and include feature routers into it:

```python
# app/router.py
from fastapi.routing import APIRouter

api_router = APIRouter()
api_router_v1_prefix = APIRouter(prefix="/v1.0")

# Include feature routers
api_router_v1_prefix.include_router(shipment_router, prefix="/shipment", tags=["Shipment v1.0"])
api_router_v1_prefix.include_router(order_router, prefix="/order", tags=["Order v1.0"])

# Mount versioned router on main api_router
api_router.include_router(api_router_v1_prefix, tags=["API v1"])
```

**Result:** All routes in `shipment_router` and `order_router` are prefixed with `/v1.0/shipment/...` and `/v1.0/order/...`.

### Pattern: v2.0 routes with app-level prefix

For v2.0 routes, either create a second versioned router or add the prefix at `app.include_router()` time:

```python
# Option 1: Second versioned router
api_router_v2_prefix = APIRouter(prefix="/v2.0")
api_router_v2_prefix.include_router(shipment_v2_router, prefix="/shipment", tags=["Shipment v2.0"])
api_router.include_router(api_router_v2_prefix, tags=["API v2"])

# Option 2: Prefix at app mount time (simpler for small v2 surface)
# app/main.py
from domain.v2.router import router as domain_v2_router

app = FastAPI(...)
app.include_router(api_router)  # v1.0 routes
app.include_router(domain_v2_router, prefix="/v2.0")  # v2.0 routes
```

**Recommendation:** Use option 1 (second versioned router) if you have many v2 routers; use option 2 for one-off v2 routes or incremental migration.

## Conditional router inclusion

Conditionally include routers based on `SERVER_TYPE`, `DEPLOYMENT_NAME`, or feature flags. This allows a single codebase to serve different API surfaces per deployment.

### Pattern: SERVER_TYPE-based inclusion

Common server types: `public` (customer-facing), `internal` (admin/partner), `platform` (integration), `webhook` (callbacks).

```python
# app/router.py
from config.settings import settings

api_router_v1_prefix = APIRouter(prefix="/v1.0")

if settings.SERVER_TYPE == "public":
    # Public-facing endpoints only
    api_router_v1_prefix.include_router(shipment_router, tags=["Shipment v1.0"])
    api_router_v1_prefix.include_router(tracking_router, tags=["Tracking v1.0"])

elif settings.SERVER_TYPE == "internal":
    # Internal admin endpoints + public endpoints
    api_router_v1_prefix.include_router(shipment_router, tags=["Shipment v1.0"])
    api_router_v1_prefix.include_router(tracking_router, tags=["Tracking v1.0"])
    api_router_v1_prefix.include_router(partner_config_router, tags=["Partner Config v1.0"])
    api_router_v1_prefix.include_router(admin_router, tags=["Admin v1.0"])

elif settings.SERVER_TYPE == "platform":
    # Integration-only endpoints
    api_router_v1_prefix.include_router(partner_config_router, tags=["Partner Config v1.0"])
    api_router_v1_prefix.include_router(integration_router, tags=["Integration v1.0"])

elif settings.SERVER_TYPE == "webhook":
    # Webhook callbacks
    api_router_v1_prefix.include_router(webhook_router, tags=["Webhook v1.0"])
```

**What to copy:** Use `if/elif` guards to include different routers per server type. Public servers get minimal routers; internal servers get admin + public; platform servers get integration-only.

### Pattern: DEPLOYMENT_NAME-based inclusion

When a service has multiple deployment instances with different feature sets:

```python
# app/routers.py
from config.settings import settings

api_router_v1_prefix = APIRouter(prefix="/v1.0")

if settings.DEPLOYMENT_NAME == "App":
    # Main app deployment
    api_router_v1_prefix.include_router(supplier_router, prefix="/supplier", tags=["supplier"])
    api_router_v1_prefix.include_router(brand_router, prefix="/brand", tags=["brand"])
    api_router_v1_prefix.include_router(auth_router, prefix="/auth", tags=["auth"])
    # ... many feature routers

elif settings.DEPLOYMENT_NAME == "WorkerAPI":
    # Worker-specific API (e.g., internal task status endpoints)
    api_router_v1_prefix.include_router(task_status_router, prefix="/task", tags=["task"])

# Always-included routers (independent of deployment)
api_router_v1_prefix.include_router(webhook_callback_router, prefix="/webhooks", tags=["webhooks"])
api_router_v1_prefix.include_router(external_integration_router, prefix="/external", tags=["external"])
```

**What to copy:** Use `DEPLOYMENT_NAME` to include routers only in specific deployments. Some routers (webhooks, integrations) are included unconditionally.

### Pattern: Unconditional routers

Health checks, webhooks, and external integrations often live outside conditional blocks:

```python
api_router = APIRouter()

# Health check router (unconditional)
api_router_healthz = APIRouter()
api_router_healthz.add_api_route("/_healthz", methods=["GET"], endpoint=healthz, include_in_schema=False)
api_router_healthz.add_api_route("/_readyz", methods=["GET"], endpoint=readyz, include_in_schema=False)
api_router.include_router(api_router_healthz, tags=["Healthz"])

# Conditional versioned routers
api_router_v1_prefix = APIRouter(prefix="/v1.0")
if settings.SERVER_TYPE == "public":
    api_router_v1_prefix.include_router(shipment_router, tags=["Shipment v1.0"])
# ...

# Always-included integrations (outside conditional blocks)
api_router_v1_prefix.include_router(webhook_callback_router, prefix="/webhooks", tags=["webhooks-callback"])

api_router.include_router(api_router_v1_prefix, tags=["API v1"])
```

**What to copy:** Health checks are unconditional; conditional routers go inside `if` guards; webhooks/integrations may be unconditional or gated by server type.

## Sharing business logic across versions

Route handlers are version-specific (different Pydantic models), but business logic is shared via a service layer.

### Pattern: Version-agnostic service layer

```python
# domain/service.py
from sqlalchemy.ext.asyncio import AsyncSession
from domain.models import Item

class ItemService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_item(self, name: str, description: str | None = None) -> Item:
        item = Item(name=name, description=description)
        self.session.add(item)
        await self.session.commit()
        await self.session.refresh(item)
        return item

    async def get_item(self, item_id: UUID) -> Item | None:
        result = await self.session.execute(select(Item).where(Item.id == item_id))
        return result.scalar_one_or_none()
```

### Pattern: Version-specific handlers calling shared service

```python
# domain/v1/serializers.py
from pydantic import BaseModel, Field

class ItemCreateV1(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str | None = None

class ItemOutV1(BaseModel):
    id: UUID
    name: str
    description: str | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

# domain/v1/views.py
from domain.service import ItemService

async def create_item_v1(
    payload: ItemCreateV1,
    connection_handler: ConnectionHandler = Depends(get_connection_handler),
) -> ResponseData:
    service = ItemService(connection_handler.session)
    item = await service.create_item(**payload.model_dump())
    return ResponseData.ok(data=ItemOutV1.model_validate(item).model_dump(mode="json"), message="Item created")
```

```python
# domain/v2/serializers.py
from pydantic import BaseModel, Field

class ItemCreateV2(BaseModel):
    # v2.0 schema adds new fields, different validation
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    category: str | None = None  # new field

class ItemOutV2(BaseModel):
    id: UUID
    name: str
    description: str | None
    category: str | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

# domain/v2/views.py
from domain.service import ItemService

async def create_item_v2(
    payload: ItemCreateV2,
    connection_handler: ConnectionHandler = Depends(get_connection_handler),
) -> ResponseData:
    service = ItemService(connection_handler.session)  # same service
    # Map v2 fields to service method
    item = await service.create_item(
        name=payload.name,
        description=payload.description,
        # Handle new v2 fields if service supports them
    )
    return ResponseData.ok(data=ItemOutV2.model_validate(item).model_dump(mode="json"), message="Item created")
```

**What to copy:**

- Business logic lives in a service class that receives `AsyncSession` in `__init__`
- v1 and v2 handlers call the same service methods
- Only the Pydantic models differ between v1 and v2
- v2 handlers may map new fields to service methods or pass them through if service supports them

### Pattern: Service layer evolution for v2

When v2 introduces new functionality, add methods to the service class and call them only from v2 handlers:

```python
# domain/service.py
class ItemService:
    async def create_item(self, name: str, description: str | None = None) -> Item:
        # v1 logic
        ...

    async def create_item_with_category(self, name: str, description: str | None, category: str | None) -> Item:
        # v2 logic (new method)
        item = Item(name=name, description=description, category=category)
        self.session.add(item)
        await self.session.commit()
        await self.session.refresh(item)
        return item

# domain/v1/views.py
async def create_item_v1(...):
    service = ItemService(connection_handler.session)
    item = await service.create_item(**payload.model_dump())  # calls v1 method
    ...

# domain/v2/views.py
async def create_item_v2(...):
    service = ItemService(connection_handler.session)
    item = await service.create_item_with_category(**payload.model_dump())  # calls v2 method
    ...
```

**What to copy:** Add new service methods for v2 functionality. v1 handlers call old methods; v2 handlers call new methods. No duplication of business logic.

## Deployment configuration

Version and server-type config is loaded from environment variables or Docker config:

```python
# config/settings.py
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    SERVER_TYPE: str = "public"  # public | internal | platform | webhook
    DEPLOYMENT_NAME: str = "App"  # App | WorkerAPI | ...

    class Config:
        env_file = ".env"

settings = Settings()
```

**What to copy:** Use `SERVER_TYPE` for public/internal/platform/webhook gating; use `DEPLOYMENT_NAME` for multi-deployment gating. Load from environment variables.

## Anti-patterns to avoid

1. **Version logic inside handlers**: Don't use `if request.url.path.startswith("/v1.0")` inside a handler. Use separate routers per version.
2. **Duplicated business logic**: Don't copy-paste service layer code into v1 and v2 handlers. Factor out into a shared service class.
3. **Query param or header versioning**: `?version=2` or `X-API-Version: 2` is less clear for client routing and OpenAPI docs. Prefer URL-prefix versioning.
4. **Forgetting to mount the versioned router**: `api_router_v1_prefix` must be included in `api_router` or `app` via `include_router()`.
5. **Hardcoded server types in routers**: Load `SERVER_TYPE` from config, not from a global constant in the router module.
6. **Not tagging routes by version**: Tag routes with `["Shipment v1.0"]` or `["Shipment v2.0"]` for clear OpenAPI grouping.

## Example: Full router structure with versioning and conditional inclusion

```python
# app/router.py
from fastapi.routing import APIRouter
from fastapi.responses import ORJSONResponse
from config.settings import settings
from shipment.routers import router as shipment_router
from partner_config.routers import router as partner_config_router
from webhook.routers import router as webhook_router
from integration.routers import router as integration_router

api_router = APIRouter()

# Health check router (unconditional)
async def healthz():
    return ORJSONResponse(status_code=200, content={"success": True})

api_router_healthz = APIRouter()
api_router_healthz.add_api_route("/_healthz", methods=["GET"], endpoint=healthz, include_in_schema=False)
api_router_healthz.add_api_route("/_readyz", methods=["GET"], endpoint=healthz, include_in_schema=False)
api_router.include_router(api_router_healthz, tags=["Healthz"])

# v1.0 router with conditional inclusion
api_router_v1_prefix = APIRouter(prefix="/v1.0")

if settings.SERVER_TYPE == "public":
    api_router_v1_prefix.include_router(shipment_router, tags=["Shipment v1.0"])

elif settings.SERVER_TYPE == "internal":
    api_router_v1_prefix.include_router(shipment_router, tags=["Shipment v1.0"])
    api_router_v1_prefix.include_router(partner_config_router, tags=["Partner Config v1.0"])

elif settings.SERVER_TYPE == "platform":
    api_router_v1_prefix.include_router(partner_config_router, tags=["Partner Config v1.0"])
    api_router_v1_prefix.include_router(integration_router, tags=["Integration v1.0"])

elif settings.SERVER_TYPE == "webhook":
    api_router_v1_prefix.include_router(webhook_router, tags=["Webhook v1.0"])

# Always-included routers (webhooks, external integrations)
api_router_v1_prefix.include_router(webhook_router, prefix="/webhooks", tags=["webhooks-callback"])

# Mount v1.0 router
api_router.include_router(api_router_v1_prefix, tags=["API v1"])
```

```python
# app/main.py or app/application.py
from fastapi import FastAPI
from app.router import api_router
from domain.v2.router import router as domain_v2_router

def get_app() -> FastAPI:
    app = FastAPI(...)
    app.include_router(api_router)  # v1.0 routes
    app.include_router(domain_v2_router, prefix="/v2.0")  # v2.0 routes
    return app
```

**What to copy:**

- Health checks are unconditional
- v1.0 router uses `APIRouter(prefix="/v1.0")` and conditional `include_router()` guards
- v2.0 router is mounted with `prefix="/v2.0"` at app level
- Webhooks and integrations may be unconditional or gated by server type
- Tags include version suffix (`["Shipment v1.0"]`)
