# Query Parameter Conventions

HTTP query parameter patterns for pagination, filtering, sorting, and search observed across production services.

## Pagination patterns

### Pattern A: page/page_size (1-indexed)

User-facing pagination with explicit page numbers:

```python
# Router parameters
page: int = Query(1, ge=1, description="Page number (1-indexed)")
page_size: int = Query(20, ge=1, le=100, description="Records per page")

# Offset calculation
offset = (page - 1) * page_size

# Response metadata
{
    "page": 1,
    "page_size": 20,
    "total_records": 150,
    "total_pages": 8,
    "has_next": true
}
```

Total pages calculation:
```python
total_pages = (total_count + page_size - 1) // page_size  # Ceiling division
has_next = page < total_pages
```

### Pattern B: limit/offset (0-indexed)

SQL-native pagination:

```python
# Router parameters
limit: int = Query(20, ge=1, le=1000, description="Maximum records to return")
offset: int = Query(0, ge=0, description="Records to skip")

# Response metadata
{
    "limit": 20,
    "offset": 0,
    "total_records": 150,
    "has_next": true
}
```

Has next calculation:
```python
has_next = (offset + limit) < total_count
```

### Choosing a pattern

- **page/page_size**: Better for UI pagination controls (page 1, 2, 3...)
- **limit/offset**: More SQL-native, easier cursor-based pagination for infinite scroll
- **Consistency**: Choose one per service; mixing confuses clients

## Multi-value filters

### Array query parameters

FastAPI accepts both `?status=pending&status=approved` and `?status[]=pending&status[]=approved`:

```python
from typing import Optional, List
from fastapi import Query

status: Optional[List[str]] = Query(None, description="Filter by status")
store_ids: Optional[List[str]] = Query(None, description="Filter by store IDs")
```

Translate to SQL `IN` or `ANY`:
```sql
WHERE status = ANY($1)  -- PostgreSQL array param
WHERE store_id = ANY($2)
```

### Comma-separated single parameter

Legacy or client-constrained APIs:

```python
items: Optional[str] = Query(None, description="Comma-separated item codes")
```

Split in service/repository:
```python
item_list = items.split(',') if items else []
# Then use in SQL: WHERE item_id = ANY($1)
```

Example: `?items=ITEM-001,ITEM-002,ITEM-003`

## Hierarchical filters

Product or location hierarchies use separate optional params for each level:

```python
# Product hierarchy
segment: Optional[str] = Query(None, description="Product segment")
family: Optional[str] = Query(None, description="Product family")
class_: Optional[str] = Query(None, description="Product class")
brick: Optional[str] = Query(None, description="Product brick")

# Location hierarchy
zone: Optional[str] = Query(None)
format: Optional[str] = Query(None)
state: Optional[str] = Query(None)
city: Optional[str] = Query(None)
store: Optional[str] = Query(None)
```

Each level narrows the filter:
```sql
WHERE 1=1
  AND (segment_cd = $1 OR $1 IS NULL)
  AND (family_cd = $2 OR $2 IS NULL)
  AND (class_cd = $3 OR $3 IS NULL)
```

Some services support both singular and plural:
```python
store: Optional[str] = Query(None)
stores: Optional[str] = Query(None)

# Coalesce: prefer plural if provided
effective_stores = stores or store
```

## Sorting parameters

### Pattern A: sort_by + sort_order

```python
sort_by: str = Query("created_at", description="Field to sort by")
sort_order: str = Query("desc", regex="^(asc|desc)$", description="Sort direction")
```

### Pattern B: order_by + direction

```python
order_by: str = Query("created_at", description="Field to order by")
direction: str = Query("DESC", regex="^(ASC|DESC)$", description="Sort direction")
```

### Column name mapping

User-facing names often differ from database columns:

```python
sort_mapping = {
    "doh": "days_on_hand",
    "stock": "total_stock",
    "sales": "sales_90d",
    "cost": "total_cost",
    "created": "created_at",
    "updated": "updated_at",
}

column = sort_mapping.get(sort_by, "created_at")  # Default fallback
query = f"ORDER BY {column} {sort_order.upper()}"
```

## Search parameters

Single search param for multi-field substring matching:

```python
search: Optional[str] = Query(None, description="Search text across item, description, store")
```

Translate to case-insensitive SQL:
```sql
WHERE (
    LOWER(item_id) LIKE LOWER($1)
    OR LOWER(item_description) LIKE LOWER($1)
    OR LOWER(store_id) LIKE LOWER($1)
)
```

Param value: `f"%{search}%"`

Some implementations use PostgreSQL `ILIKE`:
```sql
WHERE (
    item_id ILIKE $1
    OR item_description ILIKE $1
)
```

## Pydantic query models

Encapsulate all query params in a Pydantic model:

```python
from pydantic import BaseModel, Field
from typing import Optional, List

class ItemQueryParams(BaseModel):
    # Pagination
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)
    
    # Sorting
    sort_by: str = Field(default="created_at")
    sort_order: str = Field(default="desc")
    
    # Search
    search: Optional[str] = None
    
    # Filters
    status: Optional[List[str]] = None
    store_ids: Optional[List[str]] = None
    segment: Optional[str] = None
    family: Optional[str] = None
    
    @property
    def offset(self) -> int:
        """Calculate offset from page and page_size."""
        return (self.page - 1) * self.page_size
    
    @property
    def limit(self) -> int:
        """Alias for page_size."""
        return self.page_size
```

Route handler instantiates the model:
```python
@router.get("/items")
async def list_items(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    sort_by: str = Query("created_at"),
    sort_order: str = Query("desc"),
    search: Optional[str] = Query(None),
    status: Optional[List[str]] = Query(None),
    store_ids: Optional[List[str]] = Query(None),
    segment: Optional[str] = Query(None),
    family: Optional[str] = Query(None),
):
    query_params = ItemQueryParams(
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

## FastAPI validation

Use `Query()` constraints for validation:

- `ge=1`: Greater than or equal to 1
- `le=100`: Less than or equal to 100
- `regex="^(asc|desc)$"`: Must match asc or desc
- `description="..."`: Appears in OpenAPI docs

Example:
```python
page: int = Query(1, ge=1, description="Page number (1-indexed)")
page_size: int = Query(20, ge=1, le=100, description="Records per page (max 100)")
sort_order: str = Query("desc", regex="^(asc|desc)$", description="Sort direction")
```

## Constants for defaults and limits

Centralize default and max values:

```python
DEFAULT_PAGE = 1
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100

DEFAULT_SORT_BY = "created_at"
DEFAULT_SORT_ORDER = "desc"
```

Use in `Query()`:
```python
page: int = Query(DEFAULT_PAGE, ge=1)
page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE)
```
