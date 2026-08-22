# Strawberry Backend Patterns

How to use Strawberry GraphQL with FastAPI in production backend services.

## Schema-Per-Endpoint Pattern

From `app/v1/catalog/graphql/schema.py` in a production service:

```python
import strawberry
from app.v1.catalog.graphql.query import (
    ProductQuery, AllProductQuery, CategoryQuery, AllCategoryQuery,
    RegionQuery, AllRegionQuery, FormatQuery, AllFormatQuery,
    SupplierRegionQuery, AllSupplierRegionQuery, ApprovalStageQuery
)

# One schema per query type (11 total)
product_schema = strawberry.Schema(query=ProductQuery)
all_product_schema = strawberry.Schema(query=AllProductQuery)
category_schema = strawberry.Schema(query=CategoryQuery)
all_category_schema = strawberry.Schema(query=AllCategoryQuery)
region_schema = strawberry.Schema(query=RegionQuery)
all_region_schema = strawberry.Schema(query=AllRegionQuery)
supplier_region_schema = strawberry.Schema(query=SupplierRegionQuery)
all_supplier_region_schema = strawberry.Schema(query=AllSupplierRegionQuery)
format_schema = strawberry.Schema(query=FormatQuery)
all_format_schema = strawberry.Schema(query=AllFormatQuery)
approval_stage_schema = strawberry.Schema(query=ApprovalStageQuery)
```

**Why**: Each schema serves a specific dropdown/filter use case. Narrow scope, no nested resolvers. Note the pairing pattern: regular schemas (e.g., `product_schema`) join the Audit table to filter by active records, while "All*" variants (e.g., `all_product_schema`) skip that filter for admin/unfiltered dropdown views.

## Query Class Pattern

From `app/v1/catalog/graphql/query.py`:

```python
import strawberry
from typing import List, Optional
from sqlalchemy import select, distinct, asc
from app.connection import get_connection_handler_for_app

@strawberry.type
class ProductQuery:
    @strawberry.field
    async def list_products(
        self,
        page: str = '',
        internal_status: Optional[str] = ''
    ) -> List[Optional[str]]:
        async_gen = get_connection_handler_for_app()
        connection_handler = await async_gen.__anext__()

        try:
            internal_status_list = (
                [status.strip() for status in internal_status.split(",")]
                if internal_status else []
            )
            if page == 'manage-products':
                query = select(distinct(Product.name)).where(Product.name != None)
            else:
                query = (
                    select(distinct(Product.name))
                    .join(Audit, Product.id == Audit.product_id)
                    .where(Audit.is_active == True, Product.name != None)
                )
            result = await connection_handler.session.execute(query)
            products = result.scalars().all()
            return sorted(list(set(products)), key=str.lower)
        finally:
            await connection_handler.close()
```

**Key points**:
- `@strawberry.type` decorates the query class
- `@strawberry.field` decorates async resolver methods
- Always `try/finally` with `await connection_handler.close()`
- Return types are `List[Optional[str]]` or simple scalars — no nested objects
- SQLAlchemy `select` queries with `distinct`, `join`, `where` clauses

## Async Connection Handler

From `app/v1/catalog/graphql/query.py`:

```python
async_gen = get_connection_handler_for_app()
connection_handler = await async_gen.__anext__()

try:
    # ... DB queries using connection_handler.session
    result = await connection_handler.session.execute(query)
finally:
    await connection_handler.close()  # CRITICAL: always close
```

**Why**: The connection handler is an async generator. `__anext__()` gets the first (only) connection. Must close in finally block.

## Mounting GraphQL Routers

From `app/v1/catalog/router.py`:

```python
from fastapi import APIRouter
from strawberry.fastapi import GraphQLRouter
from app.v1.catalog.graphql.schema import (
    product_schema, category_schema, region_schema, format_schema,
    all_product_schema, all_category_schema, all_region_schema, all_format_schema,
    approval_stage_schema
)

catalog_router = APIRouter(prefix="/catalog", route_class=CustomRequestRoute)

# REST routes
catalog_router.add_api_route("/{product_id}", methods=["GET"], endpoint=get_product_info_by_id, ...)

# GraphQL filter routes (separate router)
filter_graphql_router = APIRouter(prefix="/filter-graphql", route_class=CustomRequestRoute)

product_graphql_app = GraphQLRouter(product_schema)
filter_graphql_router.include_router(
    product_graphql_app,
    prefix="/products",
    tags=['admin', 'member']
)

all_product_graphql_app = GraphQLRouter(all_product_schema)
filter_graphql_router.include_router(
    all_product_graphql_app,
    prefix="/all-products",
    tags=['admin', 'member']
)

# ... (repeat for category, region, format, approval_stage)
```

**Result**: GraphQL endpoints live at `/v1/catalog/filter-graphql/products`, `/v1/catalog/filter-graphql/category`, etc. alongside REST routes.

## Scalar Types

From `app/v1/catalog/graphql/type.py`:

```python
import strawberry

ProductType = strawberry.scalar(str, name="ProductType")
AllProductType = strawberry.scalar(str, name="AllProductType")
CategoryType = strawberry.scalar(str, name="CategoryType")
AllCategoryType = strawberry.scalar(str, name="AllCategoryType")
RegionType = strawberry.scalar(str, name="RegionType")
AllRegionType = strawberry.scalar(str, name="AllRegionType")
FormatType = strawberry.scalar(str, name="FormatType")
AllFormatType = strawberry.scalar(str, name="AllFormatType")
```

**Why**: Nominal typing for string scalars. In practice, the queries return `List[Optional[str]]` directly, so these may be unused legacy declarations.

## When to Use This Pattern

- **Filter/dropdown APIs**: Need distinct values from a database table for frontend filters (categories, regions, formats, statuses)
- **Async DB access**: Using SQLAlchemy async sessions with `get_connection_handler_for_app`
- **Coexist with REST**: GraphQL is a supplement for specific use cases, not a full replacement
- **No nested resolvers**: Queries return flat lists or scalars — no complex object graphs

## File Locations

- `app/v1/catalog/graphql/schema.py` — Schema definitions
- `app/v1/catalog/graphql/query.py` — Query classes with `@strawberry.field` resolvers
- `app/v1/catalog/graphql/type.py` — Scalar type declarations
- `app/v1/catalog/router.py` — FastAPI router mounting (REST + GraphQL)
