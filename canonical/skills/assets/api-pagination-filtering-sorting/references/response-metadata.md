# Response Metadata Patterns

Standardized pagination metadata structures observed across production services.

## Page/page_size style response

For endpoints using `page` and `page_size` query params:

```python
from pydantic import BaseModel, Field
from typing import List

class PaginationInfo(BaseModel):
    """Pagination metadata for page/page_size style."""
    page: int = Field(..., description="Current page number (1-indexed)")
    page_size: int = Field(..., description="Records per page")
    total_records: int = Field(..., description="Total number of records")
    total_pages: int = Field(..., description="Total number of pages")
    has_next: bool = Field(..., description="Whether more records are available")

class ItemListData(BaseModel):
    """Response data for item list."""
    data: List[dict] = Field(default_factory=list)
    pagination: PaginationInfo
```

Example response:
```json
{
    "data": [
        {"id": "1", "name": "Item A"},
        {"id": "2", "name": "Item B"}
    ],
    "pagination": {
        "page": 1,
        "page_size": 20,
        "total_records": 150,
        "total_pages": 8,
        "has_next": true
    }
}
```

Calculation in service layer:
```python
total_pages = (total_count + page_size - 1) // page_size  # Ceiling division
has_next = page < total_pages

pagination = PaginationInfo(
    page=page,
    page_size=page_size,
    total_records=total_count,
    total_pages=total_pages,
    has_next=has_next
)
```

## Limit/offset style response

For endpoints using `limit` and `offset` query params:

```python
class ItemListData(BaseModel):
    """Response data for item list (limit/offset style)."""
    data: List[dict] = Field(default_factory=list)
    total_records: int = Field(..., description="Total number of records")
    page: int = Field(..., description="Current page (derived from offset/limit)")
    page_size: int = Field(..., description="Records per page (same as limit)")
    has_next: bool = Field(..., description="Whether more records are available")
```

Example response:
```json
{
    "data": [...],
    "total_records": 150,
    "page": 1,
    "page_size": 20,
    "has_next": true
}
```

Calculation:
```python
page = (offset // limit) + 1  # Derive page from offset and limit
has_next = (offset + limit) < total_count

result = ItemListData(
    data=records,
    total_records=total_count,
    page=page,
    page_size=limit,
    has_next=has_next
)
```

## Inline metadata (flat structure)

Some services embed pagination fields directly in the response:

```python
class ItemListResponse(BaseModel):
    """Flat response structure with inline pagination."""
    data: List[dict] = Field(default_factory=list)
    page: int
    page_size: int
    total_records: int
    total_pages: int
    has_next: bool
```

Example:
```json
{
    "data": [...],
    "page": 1,
    "page_size": 20,
    "total_records": 150,
    "total_pages": 8,
    "has_next": true
}
```

## Nested metadata (structured)

Alternative: separate `pagination` object:

```json
{
    "data": [...],
    "pagination": {
        "page": 1,
        "page_size": 20,
        "total_records": 150,
        "total_pages": 8,
        "has_next": true,
        "has_prev": false
    }
}
```

Pydantic model:
```python
class PaginationMeta(BaseModel):
    page: int
    page_size: int
    total_records: int
    total_pages: int
    has_next: bool
    has_prev: bool = False

class ItemListResponse(BaseModel):
    data: List[dict]
    pagination: PaginationMeta
```

## With ResponseData envelope

When using a `ResponseData` wrapper (common pattern in production services):

```python
from app.utils import ResponseData

# In route handler
return ResponseData.ok(
    data={
        "items": records,
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total_records": total_count,
            "total_pages": total_pages,
            "has_next": has_next
        }
    },
    message="Items listed"
)
```

Response structure:
```json
{
    "success": true,
    "data": {
        "items": [...],
        "pagination": {
            "page": 1,
            "page_size": 20,
            "total_records": 150,
            "total_pages": 8,
            "has_next": true
        }
    },
    "errors": [],
    "message": "Items listed"
}
```

## Has previous indicator

Some services include `has_prev` for bidirectional pagination:

```python
has_prev = page > 1  # For page/page_size style
has_prev = offset > 0  # For limit/offset style
```

Example:
```json
{
    "pagination": {
        "page": 3,
        "page_size": 20,
        "total_records": 150,
        "total_pages": 8,
        "has_next": true,
        "has_prev": true
    }
}
```

## Empty result response

When no records match filters:

```python
# Service layer
if total_count == 0:
    return ItemListData(
        data=[],
        pagination=PaginationInfo(
            page=1,
            page_size=page_size,
            total_records=0,
            total_pages=0,
            has_next=False
        )
    )
```

Response:
```json
{
    "data": [],
    "pagination": {
        "page": 1,
        "page_size": 20,
        "total_records": 0,
        "total_pages": 0,
        "has_next": false
    }
}
```

## Download mode (no pagination)

When `download=true`, omit pagination metadata:

```python
# Service layer
if download:
    # No LIMIT/OFFSET in query
    all_records = await repository.fetch_all(query_params)
    return all_records  # Return raw data without pagination
```

Or return dummy pagination:
```python
return ItemListData(
    data=all_records,
    pagination=PaginationInfo(
        page=1,
        page_size=len(all_records),
        total_records=len(all_records),
        total_pages=1,
        has_next=False
    )
)
```

## Home mode (aggregated data)

Some services have a "home" mode with limited data and different response structure:

```python
if home:
    # Fetch aggregated data (no pagination)
    home_records = await repository.fetch_home()
    return ItemHomeData(
        data=home_records,
        total_records=len(home_records),
        page=1,
        page_size=len(home_records),
        has_next=False
    )
```

## Metadata field naming conventions

Different services use different naming conventions. Standardize within a service:

| Field | Variants |
|-------|----------|
| Current page | `page`, `current_page`, `page_number` |
| Records per page | `page_size`, `limit`, `per_page` |
| Total records | `total_records`, `total`, `total_count`, `count` |
| Total pages | `total_pages`, `pages`, `page_count` |
| More records | `has_next`, `next`, `has_more`, `is_last` (inverted) |
| Previous page | `has_prev`, `prev`, `has_previous` |

Choose one naming convention per service and stick to it across all endpoints.

## Service layer construction

Typical service layer pattern:

```python
async def get_item_list(self, query_params: QueryParams) -> ItemListData:
    """Get paginated item list."""
    # Fetch data and count
    records, total_count = await self.repository.fetch_list(query_params)
    
    # Calculate metadata
    total_pages = (total_count + query_params.page_size - 1) // query_params.page_size
    has_next = query_params.page < total_pages
    
    # Construct response
    pagination = PaginationInfo(
        page=query_params.page,
        page_size=query_params.page_size,
        total_records=total_count,
        total_pages=total_pages,
        has_next=has_next
    )
    
    return ItemListData(data=records, pagination=pagination)
```

## Repository layer return type

Repository returns `(records, total_count)` tuple:

```python
async def fetch_list(
    self,
    query_params: QueryParams
) -> Tuple[List[Dict[str, Any]], int]:
    """Fetch paginated list and total count."""
    # Build queries
    data_query, data_params = self.query_builder.build_data_query(...)
    count_query, count_params = self.query_builder.build_count_query(...)
    
    async with self.pool.acquire() as conn:
        # Fetch count
        count_row = await conn.fetchrow(count_query, *count_params)
        total_count = count_row['total'] if count_row else 0
        
        # Fetch data
        rows = await conn.fetch(data_query, *data_params)
        records = [dict(r) for r in rows]
    
    return records, total_count
```

Service layer uses the tuple to construct the response with metadata.
