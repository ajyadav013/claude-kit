# Strawberry Backend Patterns

How to use Strawberry GraphQL with FastAPI in production backend services.

## Schema-Per-Endpoint Pattern

From `app/v1/vendor/graphql/schema.py` in a production service:

```python
import strawberry
from app.v1.vendor.graphql.query import (
    CategoryQuery, AllCategoryQuery, ClusterQuery, AllClusterQuery,
    FormatQuery, AllFormatQuery, AllSourcingClusterQuery, AllCommercialClusterQuery,
    CommercialClusterQuery, SourcingClusterQuery, ProfileStatusQuery
)

# One schema per query type (11 total)
category_schema = strawberry.Schema(query=CategoryQuery)
all_category_schema = strawberry.Schema(query=AllCategoryQuery)
cluster_schema = strawberry.Schema(query=ClusterQuery)
all_cluster_schema = strawberry.Schema(query=AllClusterQuery)
all_sourcing_cluster_schema = strawberry.Schema(query=AllSourcingClusterQuery)
all_commercial_cluster_schema = strawberry.Schema(query=AllCommercialClusterQuery)
sourcing_cluster_schema = strawberry.Schema(query=SourcingClusterQuery)
commercial_cluster_schema = strawberry.Schema(query=CommercialClusterQuery)
format_schema = strawberry.Schema(query=FormatQuery)
all_format_schema = strawberry.Schema(query=AllFormatQuery)
profile_status_schema = strawberry.Schema(query=ProfileStatusQuery)
```

**Why**: Each schema serves a specific dropdown/filter use case. Narrow scope, no nested resolvers. Note the pairing pattern: regular schemas (e.g., `category_schema`) join the Audit table to filter by active records, while "All*" variants (e.g., `all_category_schema`) skip that filter for admin/unfiltered dropdown views.

## Query Class Pattern

From `app/v1/vendor/graphql/query.py`:

```python
import strawberry
from typing import List, Optional
from sqlalchemy import select, distinct, asc
from app.connection import get_connection_handler_for_app

@strawberry.type
class CategoryQuery:
    @strawberry.field
    async def list_categories(
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
            if page == 'manage-vendor':
                query = select(distinct(Vendor.category)).where(Vendor.category != None)
            else:
                query = (
                    select(distinct(Vendor.category))
                    .join(Audit, Vendor.id == Audit.vendor_id)
                    .where(Audit.is_active == True, Vendor.category != None)
                )
            result = await connection_handler.session.execute(query)
            categories = result.scalars().all()
            return sorted(list(set(categories)), key=str.lower)
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

From `app/v1/vendor/graphql/query.py`:

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

From `app/v1/vendor/router.py`:

```python
from fastapi import APIRouter
from strawberry.fastapi import GraphQLRouter
from app.v1.vendor.graphql.schema import (
    category_schema, cluster_schema, format_schema,
    all_category_schema, all_cluster_schema, all_format_schema,
    profile_status_schema
)

vendor_router = APIRouter(prefix="/vendor-info", route_class=CustomRequestRoute)

# REST routes
vendor_router.add_api_route("/{vendor_id}", methods=["GET"], endpoint=get_vendor_info_by_id, ...)

# GraphQL filter routes (separate router)
filter_graphql_router = APIRouter(prefix="/filter-graphql", route_class=CustomRequestRoute)

category_graphql_app = GraphQLRouter(category_schema)
filter_graphql_router.include_router(
    category_graphql_app,
    prefix="/category",
    tags=['admin', 'member']
)

all_category_graphql_app = GraphQLRouter(all_category_schema)
filter_graphql_router.include_router(
    all_category_graphql_app,
    prefix="/all-category",
    tags=['admin', 'member']
)

# ... (repeat for cluster, format, profile_status)
```

**Result**: GraphQL endpoints live at `/v1/vendor-info/filter-graphql/category`, `/v1/vendor-info/filter-graphql/cluster`, etc. alongside REST routes.

## Scalar Types

From `app/v1/vendor/graphql/type.py`:

```python
import strawberry

ClusterType = strawberry.scalar(str, name="ClusterType")
AllClusterType = strawberry.scalar(str, name="AllClusterType")
CategoryType = strawberry.scalar(str, name="CategoryType")
AllCategoryType = strawberry.scalar(str, name="AllCategoryType")
FormatType = strawberry.scalar(str, name="FormatType")
AllFormatType = strawberry.scalar(str, name="AllFormatType")
```

**Why**: Nominal typing for string scalars. In practice, the queries return `List[Optional[str]]` directly, so these may be unused legacy declarations.

## When to Use This Pattern

- **Filter/dropdown APIs**: Need distinct values from a database table for frontend filters (categories, clusters, formats, statuses)
- **Async DB access**: Using SQLAlchemy async sessions with `get_connection_handler_for_app`
- **Coexist with REST**: GraphQL is a supplement for specific use cases, not a full replacement
- **No nested resolvers**: Queries return flat lists or scalars — no complex object graphs

## File Locations

- `app/v1/vendor/graphql/schema.py` — Schema definitions
- `app/v1/vendor/graphql/query.py` — Query classes with `@strawberry.field` resolvers
- `app/v1/vendor/graphql/type.py` — Scalar type declarations
- `app/v1/vendor/router.py` — FastAPI router mounting (REST + GraphQL)
