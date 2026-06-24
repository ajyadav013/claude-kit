# Repository Evidence

Genericized code snippets demonstrating pagination, filtering, and sorting patterns from production services.

## Pydantic query models

### Page/page_size style

```python
# app/models.py
from pydantic import BaseModel, Field
from typing import Optional, List

class ForecastQuery(BaseModel):
    """Query parameters for forecast data."""
    zone: Optional[str] = None
    format: Optional[str] = None
    state: Optional[str] = None
    city: Optional[str] = None
    store: Optional[str] = None
    segment: Optional[str] = None
    family: Optional[str] = None
    classes: Optional[str] = None
    search: Optional[str] = None
    page: Optional[int] = 1
    page_size: Optional[int] = 50
    download: bool = False
```

### Limit/offset style

```python
# app/inventory/models.py
class InventoryQueryParams(BaseModel):
    """Query parameters for inventory data list."""
    
    # Pagination
    limit: int = Field(default=100, ge=1, le=1000, description="Maximum records to return")
    offset: int = Field(default=0, ge=0, description="Records to skip")
    
    # Sorting
    sort_by: str = Field(default="created_at", description="Field to sort by")
    sort_order: str = Field(default="desc", description="Sort direction: asc or desc")
    
    # Search
    search: Optional[str] = Field(None, description="Search text")
    
    # Filters
    status: Optional[List[str]] = Field(None, description="Filter by status")
    store_ids: Optional[List[str]] = Field(None, description="Filter by store IDs")
    priorities: Optional[List[str]] = Field(None, description="Filter by priorities")
    segment_codes: Optional[List[str]] = Field(None, description="Filter by segment codes")
    family_codes: Optional[List[str]] = Field(None, description="Filter by family codes")
```

### With computed offset property

```python
# app/forecast/models.py
class QueryParams(BaseModel):
    page: int = Field(default=1, ge=1, description="Page number")
    page_size: int = Field(default=50, ge=1, le=1000, description="Records per page")
    
    @property
    def limit(self) -> int:
        """Get limit from page_size."""
        return self.page_size
    
    @property
    def offset(self) -> int:
        """Calculate offset from page and page_size."""
        return (self.page - 1) * self.page_size
```

## Response metadata models

### Page/page_size response

```python
# app/forecast/models.py
class ForecastResponse(BaseModel):
    """Response model for forecast data."""
    data: List[ForecastRecord] = Field(..., description="List of forecast records")
    total_records: int = Field(..., description="Total number of records")
    page: int = Field(..., description="Current page number")
    page_size: int = Field(..., description="Records per page")
    total_pages: int = Field(..., description="Total number of pages")
    has_next: bool = Field(..., description="Whether more records are available")
    metadata: dict = Field(default_factory=dict, description="Additional metadata")
```

### Limit/offset response

```python
# app/inventory/models.py
class InventoryListData(BaseModel):
    """Response data for inventory list."""
    data: List[InventoryRecord] = Field(default_factory=list, description="List of records")
    total_records: int = Field(0, description="Total number of records")
    page: int = Field(1, description="Current page number")
    page_size: int = Field(100, description="Records per page")
    has_next: bool = Field(False, description="Has more pages")
```

## Router endpoints

### Page/page_size with sorting

```python
# app/home/router.py
@router.get("/detailed_item_view")
async def get_detailed_item_view(
    # Pagination
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page (max 100)"),
    
    # Sorting
    sort_by: str = Query(
        "doh",
        description="Column to sort by: site, category, subcategory, item, doh, stock, sales, cost"
    ),
    sort_order: str = Query(
        "DESC",
        regex="^(ASC|DESC)$",
        description="Sort order: ASC or DESC"
    ),
    
    # Hierarchical filters
    families: Optional[str] = Query(None, description="Category/Family ID"),
    subcategory: Optional[str] = Query(None, description="Subcategory/Class ID"),
    
    # Search
    search: Optional[str] = Query(None, description="Search text across site, category, item"),
    
    # Multi-value filters (comma-separated)
    items: Optional[str] = Query(None, description="Comma-separated item codes"),
    stores: Optional[str] = Query(None, description="Comma-separated store IDs"),
    
    service = Depends(get_service),
):
    """
    Get detailed item view with pagination and sorting.
    
    **Usage Examples:**
    ```
    GET /detailed_item_view?sort_by=stock&sort_order=DESC
    GET /detailed_item_view?items=ITEM-001,ITEM-002,ITEM-003
    GET /detailed_item_view?category=BEVERAGES&stores=6217,6220&sort_by=cost&sort_order=ASC
    ```
    """
    # Service call omitted
    pass
```

### Limit/offset with multi-value filters

```python
# app/inventory/distribution/router.py
DEFAULT_PAGE = 1
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 1000

@router.get("/distribution")
async def get_distribution_data(
    # Search
    search: Optional[str] = Query(None, description="Search text across order_id, location_id, item_id"),
    
    # Sorting
    sort_by: str = Query("created_at", description="Field to sort by"),
    sort_type: str = Query("desc", description="Sort direction: asc or desc"),
    
    # Pagination
    page: int = Query(DEFAULT_PAGE, description="Page number (1-indexed)", ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, description="Number of records per page", ge=1, le=MAX_PAGE_SIZE),
    
    # Multi-value filters
    status: Optional[List[str]] = Query(None, description="Filter by status (multi-value)"),
    source_location_id: Optional[List[str]] = Query(None, description="Filter by source location IDs"),
    destination_location_id: Optional[List[str]] = Query(None, description="Filter by destination location IDs"),
    
    # Hierarchical product filters
    segment_cd: Optional[List[str]] = Query(None, description="Filter by segment codes"),
    family_cd: Optional[List[str]] = Query(None, description="Filter by family codes"),
    
    service = Depends(get_service),
):
    """
    Get distribution data with filtering, search, sorting, and pagination.
    
    **Pagination:**
    - page: Page number (1-indexed, default: 1)
    - page_size: Records per page (1-1000, default: 20)
    """
    # Calculate offset from page and page_size
    offset = (page - 1) * page_size
    
    # Service call omitted
    pass
```

## Query builder patterns

### Parameterized query construction

```python
# app/forecast/query_builder.py
class ForecastQueryBuilder:
    """Builds SQL queries for forecast data."""
    
    def __init__(self, schema: str, table: str):
        self.schema = schema
        self.table = table
        self._params: List[Any] = []
        self._param_index = 1
    
    def build_forecast_query(
        self,
        filters: Dict[str, str],
        limit: int,
        offset: int,
        download: bool = False
    ) -> Tuple[str, List[Any]]:
        """Build main query with pagination."""
        self._reset_params()
        
        # Build filter clauses
        site_where = self._build_site_filters(filters)
        hierarchy_where = self._build_hierarchy_filters(filters)
        search_where = self._build_search_filter(filters)
        
        query = f"""
            SELECT *
            FROM {self.schema}.{self.table}
            WHERE 1=1
            {site_where}
            {hierarchy_where}
            {search_where}
            ORDER BY total_qty DESC NULLS LAST, created_at DESC
        """
        
        # Add pagination
        if not download and limit:
            limit_placeholder = self._add_param(limit)
            offset_placeholder = self._add_param(offset)
            query += f"\nLIMIT {limit_placeholder} OFFSET {offset_placeholder}"
        
        return query.strip(), self._params
    
    def _reset_params(self) -> None:
        """Reset parameters for new query."""
        self._params = []
        self._param_index = 1
    
    def _add_param(self, value: Any) -> str:
        """Add parameter and return placeholder."""
        placeholder = f"${self._param_index}"
        self._params.append(value)
        self._param_index += 1
        return placeholder
```

### Sort column mapping

```python
# app/home/query_builder.py
class ItemQueryBuilder:
    def _get_sort_column(self, sort_by: str) -> str:
        """Map sort_by parameter to actual column name."""
        sort_mapping = {
            "site": "store_name",
            "category": "category_description",
            "item": "item_id",
            "doh": "days_on_hand",
            "stock": "total_stock",
            "sales": "sales_90d",
            "cost": "total_cost",
            "bucket": "doh_bucket",
        }
        return sort_mapping.get(sort_by, 'days_on_hand')  # Default to DOH
```

### Multi-value filter building

```python
# app/inventory/distribution/query_builder.py
def _build_filters(self, query_params) -> str:
    """Build filter clauses."""
    clauses = []
    
    # Multi-value filters
    if query_params.status:
        clauses.append(f"AND status = ANY({self._add_param(query_params.status)})")
    if query_params.store_ids:
        clauses.append(f"AND store_id = ANY({self._add_param(query_params.store_ids)})")
    if query_params.segment_codes:
        clauses.append(f"AND segment_cd = ANY({self._add_param(query_params.segment_codes)})")
    
    return "\n".join(clauses)
```

### Search filter building

```python
# app/query_builder.py
def _build_search_filter(self, search: Optional[str]) -> str:
    """Build search clause for multi-field search."""
    if not search:
        return ""
    
    search_param = self._add_param(f"%{search}%")
    return f"""
        AND (
            LOWER(item_id) LIKE LOWER({search_param})
            OR LOWER(item_description) LIKE LOWER({search_param})
            OR LOWER(order_id) LIKE LOWER({search_param})
            OR LOWER(store_id) LIKE LOWER({search_param})
        )
    """
```

### Count query

```python
# app/query_builder.py
def build_count_query(self, filters: Dict[str, str]) -> Tuple[str, List[Any]]:
    """Build count query for pagination metadata."""
    self._reset_params()
    
    # Build filter clauses (same as data query)
    site_where = self._build_site_filters(filters)
    hierarchy_where = self._build_hierarchy_filters(filters)
    search_where = self._build_search_filter(filters)
    
    query = f"""
        SELECT COUNT(DISTINCT CONCAT(site_id, '-', item_id)) as total
        FROM {self.schema}.{self.table}
        WHERE 1=1
        {site_where}
        {hierarchy_where}
        {search_where}
    """
    return query.strip(), self._params
```

## Repository layer

### Fetch list with count

```python
# app/inventory/distribution/repository.py
class DistributionRepository:
    async def fetch_list(
        self,
        query_params: QueryParams
    ) -> Tuple[List[Dict[str, Any]], int]:
        """Fetch paginated list and total count."""
        # Build queries
        data_query, data_params = self.query_builder.build_data_query(
            query_params,
            limit=query_params.limit,
            offset=query_params.offset
        )
        count_query, count_params = self.query_builder.build_count_query(query_params)
        
        async with self.pool.acquire() as conn:
            # Fetch count
            count_row = await conn.fetchrow(count_query, *count_params)
            total_count = count_row['total'] if count_row else 0
            
            # Fetch data
            rows = await conn.fetch(data_query, *data_params)
            records = [dict(r) for r in rows]
        
        return records, total_count
```

## Service layer

### Pagination metadata construction

```python
# app/forecast/service.py
class ForecastService:
    async def get_forecast_list(
        self,
        filters: Dict[str, str],
        page: int = 1,
        page_size: int = 50
    ) -> ForecastResponse:
        """Get forecast data list with pagination."""
        offset = (page - 1) * page_size
        
        # Fetch data and count
        records, total_count = await self.repository.fetch_list(
            filters=filters,
            limit=page_size,
            offset=offset
        )
        
        # Calculate pagination metadata
        total_pages = (total_count + page_size - 1) // page_size if total_count > 0 else 0
        has_next = page < total_pages
        
        return ForecastResponse(
            data=records,
            total_records=total_count,
            page=page,
            page_size=page_size,
            total_pages=total_pages,
            has_next=has_next,
            metadata={}
        )
```

### Limit/offset style

```python
# app/inventory/distribution/service.py
class DistributionService:
    async def get_distribution_list(
        self,
        query_params: QueryParams
    ) -> DistributionListData:
        """Get distribution data list with pagination."""
        records_data, total_count = await self.repository.fetch_list(query_params)
        
        # Convert to Pydantic models
        records = [InventoryRecord(**r) for r in records_data]
        
        # Calculate pagination metadata
        page = (query_params.offset // query_params.limit) + 1
        has_next = (query_params.offset + query_params.limit) < total_count
        
        return DistributionListData(
            data=records,
            total_records=total_count,
            page=page,
            page_size=query_params.limit,
            has_next=has_next
        )
```

## Configuration patterns

### Sort configuration

```python
# app/inventory/distribution/config.py
class DistributionConfig:
    """Configuration for distribution module."""
    
    default_sort_by: str = "created_at"
    
    sortable_columns: Dict[str, str] = {
        "created_at": "created_at",
        "updated_at": "updated_at",
        "order_id": "order_id",
        "store_id": "store_id",
        "item_id": "item_id",
        "quantity": "quantity",
        "status": "status",
    }
    
    def get_sort_column(self, sort_by: str) -> str:
        """Get actual column name from user-facing sort_by parameter."""
        return self.sortable_columns.get(sort_by.lower(), self.default_sort_by)
```

### Constants

```python
# app/forecast/constants.py
DEFAULT_PAGE = 1
DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 1000

DEFAULT_SORT_BY = "created_at"
DEFAULT_SORT_ORDER = "desc"
```

## File paths (generic)

These patterns appear across multiple services:

- `app/models.py` — Pydantic query and response models
- `app/inventory/models.py` — Domain-specific models
- `app/inventory/router.py` — FastAPI route handlers with Query() params
- `app/inventory/service.py` — Service layer with pagination metadata construction
- `app/inventory/repository.py` — Repository layer with fetch_list returning (records, count)
- `app/inventory/query_builder.py` — QueryBuilder class with build_data_query and build_count_query
- `app/inventory/config.py` — Configuration for sort mappings and defaults
- `app/inventory/constants.py` — Constants for pagination defaults and limits
