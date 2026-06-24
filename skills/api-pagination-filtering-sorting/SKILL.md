---
name: api-pagination-filtering-sorting
description: HTTP query parameter conventions for pagination (page/page_size vs limit/offset), multi-value filtering (comma-separated lists, hierarchical filters), sorting (sort_by/order_by/direction), and multi-field search with standardized response metadata (total_records, total_pages, has_next). Use when designing list endpoints, implementing pagination and filtering, or building repository layers that translate query params to SQL.
---

Standardize HTTP query parameter conventions and response metadata for paginated, filtered, and sorted list endpoints.

## When to use

- Designing a new list endpoint with pagination, filtering, or sorting
- Implementing multi-value or hierarchical filters (e.g., segment, family, class filters)
- Building repository/query builder layers that translate query params to SQL
- Adding search across multiple fields to a list endpoint
- Standardizing response metadata across paginated endpoints
- Reviewing endpoint consistency for pagination patterns
- Adding sort_by/order_by capabilities to existing endpoints
- Implementing cursor-based pagination for large datasets (complement to offset-based)

## Core conventions

1. **Pagination styles**: Two common patterns emerge—(a) `page` (1-indexed) + `page_size` with `total_pages` in response; (b) `limit` + `offset` (0-indexed) with `has_next` boolean. Pattern (a) is friendlier for UI pagination controls; pattern (b) is more SQL-native. Choose one per service; mixing within a service confuses clients. `page_size` or `limit` should have a `ge=1, le=<MAX>` constraint (common max: 100 or 1000).

2. **Offset calculation**: When using `page`/`page_size`, calculate `offset = (page - 1) * page_size` in the route handler or service layer before passing to repository. When using `limit`/`offset`, pass directly. Both approaches translate to `LIMIT {limit} OFFSET {offset}` in SQL.

3. **Response pagination metadata**: Standardize on a `PaginationInfo` or inline fields embedded in the data response. Common fields: `page` (current page, 1-indexed), `page_size` or `limit` (records per page), `total` or `total_records` (total count across all pages), `total_pages` (ceiling division: `(total + page_size - 1) // page_size`), `has_next` (boolean: `(offset + limit) < total` or `page < total_pages`), optional `has_prev` (boolean: `page > 1` or `offset > 0`). Return metadata alongside `data` list in the response envelope.

4. **Multi-value filters via FastAPI `Query`**: For filters that accept multiple values (e.g., `status`, `store_ids`, `segment_codes`), use `Optional[List[str]] = Query(None, description="...")`. The client sends `?status=pending&status=approved` or `?status[]=pending&status[]=approved` (FastAPI accepts both). In the query builder, translate to SQL `IN` clause or `ANY(ARRAY[...])`.

5. **Comma-separated multi-value filters**: Some endpoints accept comma-separated values in a single param (e.g., `?items=ITEM-001,ITEM-002,ITEM-003`). Use `Optional[str] = Query(None)` and split by comma in the service or repository layer before building SQL. This pattern is common for legacy APIs or when the client cannot send array query params.

6. **Hierarchical filters**: Product or location hierarchies (e.g., segment → family → class → brick; zone → format → state → region → city → store) use separate query params for each level. Each is optional; when provided, it narrows results to that level. Example: `?segment=BEVERAGES&family=SOFT_DRINKS&class=COLA`. Query builder applies `WHERE` clauses for each non-null filter. Some services support both singular and plural param names (`?store=...` and `?stores=...`); prefer plural for multi-value, singular for single value.

7. **Sorting via `sort_by` + `sort_order` or `order_by` + `direction`**: Two naming conventions—`sort_by` (field name) + `sort_order` (asc/desc) or `order_by` + `direction`. Choose one per service. Use FastAPI `Query` with `regex="^(ASC|DESC)$"` or `regex="^(asc|desc)$"` for order validation. Map user-facing sort field names (e.g., `doh`, `stock`, `sales`) to actual column names in query builder via a `sort_mapping` dict. Default sort is usually `created_at DESC` or a domain-specific default (e.g., `total_actual_qty DESC` for forecast data).

8. **QueryBuilder pattern**: Encapsulate SQL construction in a `QueryBuilder` class. It receives filters, pagination params, and sort params; returns `(query, params)` tuple with parameterized placeholders (`$1, $2, ...` for PostgreSQL, `?` for others). The builder resets params per query via `_reset_params()` and adds params via `_add_param(value)` returning a placeholder. Separate methods for data query (`build_data_query`) and count query (`build_count_query`) sharing the same filter logic.

9. **Repository layer pagination**: The repository fetches two results in parallel—`(records_data, total_count)`—via `asyncio.gather` or sequential calls. It executes the count query to get `total_count`, then executes the data query with `LIMIT/OFFSET`. Service layer constructs the response object with data + pagination metadata. For download endpoints (no pagination), omit `LIMIT/OFFSET` from the query.

10. **Search across multiple fields**: A single `search` query param applies a case-insensitive substring match across multiple columns. In SQL, use `WHERE (LOWER(field1) LIKE LOWER(:search) OR LOWER(field2) LIKE LOWER(:search) OR ...)` with param `%{search}%`. Some implementations use `ILIKE` (PostgreSQL) or full-text search. Common searchable fields: item codes, descriptions, store IDs, order IDs.

11. **Pydantic models for query params**: Define a `QueryParams` Pydantic model (e.g., `InventoryQueryParams`, `ForecastQuery`) to encapsulate all filters, pagination, sorting, and search params. This separates route handler param extraction from business logic. The model can provide helper methods like `@property def limit(self)` to derive limit from `page_size` or compute `offset` from `page` and `page_size`.

12. **FastAPI route handler**: Extract query params via `Query()` for primitive types or depend on Pydantic model. Calculate `offset = (page - 1) * page_size` if needed. Call service layer with `query_params` object or individual params. Return response via `ResponseData.ok(data=..., pagination=...)` or a typed response model wrapping data + metadata.

13. **Default and max constraints**: Pagination params should have defaults and constraints: `page: int = Query(1, ge=1)`, `page_size: int = Query(20, ge=1, le=100)`, `limit: int = Query(20, ge=1, le=1000)`, `offset: int = Query(0, ge=0)`. Document max values in endpoint docstring. Constants like `DEFAULT_PAGE_SIZE = 20`, `MAX_PAGE_SIZE = 1000` centralize these values.

14. **RBAC / hierarchy access control**: Some endpoints filter results by user's hierarchy access (e.g., user can only see data for their assigned stores or segments). This is modeled as `List[HierarchyFilter]` derived from user context (x-user-data JWT). The query builder applies RBAC filters as additional `WHERE` clauses (e.g., `WHERE (segment = ANY(:allowed_segments) OR :allowed_segments = '{all}')`). Cross-reference `python-dao-and-database` for DAO-level RLS patterns.

15. **Caching paginated responses**: For expensive queries, cache results by a key derived from `(query_params, hierarchy_filters, org_id, run_id)`. Serialize the Pydantic response model to JSON for cache storage. Cache TTL is typically 1 hour. Invalidate cache on data writes. Use Redis or in-memory cache. Avoid caching every page individually; instead cache the full result set or the first page and accept cache misses for deeper pages.

## Skeleton / example

```python
# models.py
from typing import Optional, List
from pydantic import BaseModel, Field

class QueryParams(BaseModel):
    """Query parameters for list endpoint."""
    # Pagination (page/page_size style)
    page: int = Field(default=1, ge=1, description="Page number (1-indexed)")
    page_size: int = Field(default=20, ge=1, le=100, description="Records per page")
    
    # Sorting
    sort_by: str = Field(default="created_at", description="Field to sort by")
    sort_order: str = Field(default="desc", description="Sort direction: asc or desc")
    
    # Search
    search: Optional[str] = Field(None, description="Search text")
    
    # Multi-value filters
    status: Optional[List[str]] = Field(None, description="Filter by status")
    store_ids: Optional[List[str]] = Field(None, description="Filter by store IDs")
    
    # Hierarchical filters
    segment: Optional[str] = Field(None, description="Product segment")
    family: Optional[str] = Field(None, description="Product family")
    
    @property
    def offset(self) -> int:
        """Calculate offset from page and page_size."""
        return (self.page - 1) * self.page_size


class PaginationInfo(BaseModel):
    """Pagination metadata."""
    page: int = Field(..., description="Current page number")
    page_size: int = Field(..., description="Records per page")
    total_records: int = Field(..., description="Total number of records")
    total_pages: int = Field(..., description="Total number of pages")
    has_next: bool = Field(..., description="Whether more records are available")


class ItemListData(BaseModel):
    """Response data for item list."""
    data: List[dict] = Field(default_factory=list, description="List of records")
    pagination: PaginationInfo = Field(..., description="Pagination metadata")
```

```python
# query_builder.py
from typing import Dict, List, Any, Tuple

class ItemQueryBuilder:
    """Builds SQL queries for item list with filters, sorting, pagination."""
    
    def __init__(self, schema: str, table: str):
        self.schema = schema
        self.table = table
        self._params: List[Any] = []
        self._param_index = 1
    
    def build_data_query(
        self,
        query_params: QueryParams,
        limit: int,
        offset: int
    ) -> Tuple[str, List[Any]]:
        """Build main query with pagination."""
        self._reset_params()
        
        filters_where = self._build_filters(query_params)
        search_where = self._build_search(query_params.search)
        sort_clause = self._build_sort(query_params.sort_by, query_params.sort_order)
        
        query = f"""
            SELECT *
            FROM {self.schema}.{self.table}
            WHERE 1=1
            {filters_where}
            {search_where}
            {sort_clause}
            LIMIT {self._add_param(limit)} OFFSET {self._add_param(offset)}
        """
        return query.strip(), self._params
    
    def build_count_query(self, query_params: QueryParams) -> Tuple[str, List[Any]]:
        """Build count query for pagination metadata."""
        self._reset_params()
        
        filters_where = self._build_filters(query_params)
        search_where = self._build_search(query_params.search)
        
        query = f"""
            SELECT COUNT(*) as total
            FROM {self.schema}.{self.table}
            WHERE 1=1
            {filters_where}
            {search_where}
        """
        return query.strip(), self._params
    
    def _build_filters(self, query_params: QueryParams) -> str:
        """Build filter clauses."""
        clauses = []
        
        # Multi-value filters
        if query_params.status:
            clauses.append(f"AND status = ANY({self._add_param(query_params.status)})")
        if query_params.store_ids:
            clauses.append(f"AND store_id = ANY({self._add_param(query_params.store_ids)})")
        
        # Hierarchical filters
        if query_params.segment:
            clauses.append(f"AND segment_cd = {self._add_param(query_params.segment)}")
        if query_params.family:
            clauses.append(f"AND family_cd = {self._add_param(query_params.family)}")
        
        return "\n".join(clauses)
    
    def _build_search(self, search: Optional[str]) -> str:
        """Build search clause."""
        if not search:
            return ""
        search_param = self._add_param(f"%{search}%")
        return f"""
            AND (
                LOWER(item_id) LIKE LOWER({search_param})
                OR LOWER(item_description) LIKE LOWER({search_param})
                OR LOWER(store_id) LIKE LOWER({search_param})
            )
        """
    
    def _build_sort(self, sort_by: str, sort_order: str) -> str:
        """Build ORDER BY clause with column mapping."""
        sort_mapping = {
            "created_at": "created_at",
            "updated_at": "updated_at",
            "item": "item_id",
            "store": "store_id",
        }
        column = sort_mapping.get(sort_by, "created_at")
        direction = sort_order.upper()
        return f"ORDER BY {column} {direction}"
    
    def _reset_params(self) -> None:
        self._params = []
        self._param_index = 1
    
    def _add_param(self, value: Any) -> str:
        placeholder = f"${self._param_index}"
        self._params.append(value)
        self._param_index += 1
        return placeholder
```

```python
# repository.py
from typing import List, Tuple, Dict, Any

class ItemRepository:
    """Repository for item data access."""
    
    def __init__(self, pool, schema: str, table: str):
        self.pool = pool
        self.query_builder = ItemQueryBuilder(schema, table)
    
    async def fetch_list(
        self,
        query_params: QueryParams
    ) -> Tuple[List[Dict[str, Any]], int]:
        """Fetch paginated list and total count."""
        # Build queries
        data_query, data_params = self.query_builder.build_data_query(
            query_params,
            limit=query_params.page_size,
            offset=query_params.offset
        )
        count_query, count_params = self.query_builder.build_count_query(query_params)
        
        # Execute queries
        async with self.pool.acquire() as conn:
            # Fetch count
            count_row = await conn.fetchrow(count_query, *count_params)
            total_count = count_row['total'] if count_row else 0
            
            # Fetch data
            rows = await conn.fetch(data_query, *data_params)
            records = [dict(r) for r in rows]
        
        return records, total_count
```

```python
# service.py
class ItemService:
    """Service for item operations."""
    
    def __init__(self, pool, schema: str, table: str):
        self.repository = ItemRepository(pool, schema, table)
    
    async def get_item_list(self, query_params: QueryParams) -> ItemListData:
        """Get paginated item list."""
        records, total_count = await self.repository.fetch_list(query_params)
        
        # Calculate pagination metadata
        total_pages = (total_count + query_params.page_size - 1) // query_params.page_size
        has_next = query_params.page < total_pages
        
        pagination = PaginationInfo(
            page=query_params.page,
            page_size=query_params.page_size,
            total_records=total_count,
            total_pages=total_pages,
            has_next=has_next
        )
        
        return ItemListData(data=records, pagination=pagination)
```

```python
# router.py
from fastapi import APIRouter, Query, Depends
from typing import Optional, List

router = APIRouter(prefix="/items", tags=["Items"])

@router.get("/", response_model=ItemListData)
async def list_items(
    # Pagination
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    page_size: int = Query(20, ge=1, le=100, description="Records per page (max 100)"),
    # Sorting
    sort_by: str = Query("created_at", description="Field to sort by"),
    sort_order: str = Query("desc", regex="^(asc|desc)$", description="Sort direction"),
    # Search
    search: Optional[str] = Query(None, description="Search across item, description, store"),
    # Filters
    status: Optional[List[str]] = Query(None, description="Filter by status (multi-value)"),
    store_ids: Optional[List[str]] = Query(None, description="Filter by store IDs"),
    segment: Optional[str] = Query(None, description="Product segment"),
    family: Optional[str] = Query(None, description="Product family"),
    # Service dependency
    service: ItemService = Depends(get_item_service),
) -> ItemListData:
    """
    Get paginated item list with filtering, search, and sorting.
    
    **Pagination:**
    - page: Page number (1-indexed, default: 1)
    - page_size: Records per page (1-100, default: 20)
    
    **Sorting:**
    - sort_by: Field to sort by (created_at, updated_at, item, store)
    - sort_order: asc or desc (default: desc)
    
    **Filters:**
    - status[]: Filter by status (multi-value)
    - store_ids[]: Filter by store IDs (multi-value)
    - segment: Product segment (hierarchical)
    - family: Product family (hierarchical, requires segment)
    
    **Search:**
    - search: Substring match across item_id, item_description, store_id
    """
    query_params = QueryParams(
        page=page,
        page_size=page_size,
        sort_by=sort_by,
        sort_order=sort_order,
        search=search,
        status=status,
        store_ids=store_ids,
        segment=segment,
        family=family,
    )
    return await service.get_item_list(query_params)
```

## Anti-patterns to avoid

1. **Mixing pagination styles within a service**: Choose either `page`/`page_size` or `limit`/`offset`; mixing both confuses API consumers.
2. **Omitting max constraints on `page_size` or `limit`**: Without `le=<MAX>`, clients can request unbounded result sets (e.g., `?page_size=999999`), causing OOM or slow queries.
3. **Returning total count for every request without caching**: `SELECT COUNT(*)` on large tables is expensive; cache total count or use approximate counts (PostgreSQL `reltuples`), or omit total_pages and rely on `has_next` alone for cursor-based UIs.
4. **Not parameterizing filter values**: Building SQL via string concatenation (`WHERE status IN ('{",".join(status)}')"`) is SQL injection-prone; always use parameterized placeholders.
5. **Single-responsibility violation**: Query construction in route handlers; move SQL building to a dedicated QueryBuilder or repository method.
6. **Zero-indexed `page` in user-facing APIs**: Users expect page 1 to be the first page; use 1-indexed `page` in API and convert to 0-indexed offset internally.
7. **Hardcoding sort column names**: User sends `sort_by=doh` but SQL uses `days_on_hand`; maintain a sort mapping dict to translate user-facing names to column names.
8. **Ignoring case-sensitivity in search**: `WHERE item_id LIKE :search` is case-sensitive on some DBs; use `LOWER(...)` or `ILIKE` for case-insensitive search.
9. **Fetching full result set then paginating in Python**: Always push `LIMIT/OFFSET` to SQL; paginating in-memory defeats the purpose and exhausts memory on large datasets.
10. **Not validating `sort_order`**: Accepting arbitrary `sort_order` can inject ASC/DESC into SQL unsafely; use `regex="^(asc|desc)$"` or enum validation.
11. **Returning inconsistent metadata field names**: `total` vs `total_records`, `limit` vs `page_size`, `next` vs `has_next`; standardize on one naming convention per service.
12. **Missing offset calculation documentation**: Document whether `page` is 0-indexed or 1-indexed, and show the offset formula in comments or docstrings.

## References

- [query-params-conventions.md](references/query-params-conventions.md) — pagination, filtering, sorting, search param patterns
- [response-metadata.md](references/response-metadata.md) — standardized pagination response structures
- [repo-evidence.md](references/repo-evidence.md) — genericized source snippets
