# api-pagination-filtering-sorting

HTTP query parameter conventions for pagination, filtering, sorting, and search with standardized response metadata.

## Coverage

This skill covers production-tested conventions for designing paginated, filtered, and sorted list endpoints:

- **Pagination patterns**: `page`/`page_size` vs `limit`/`offset` with offset calculation and response metadata
- **Multi-value filters**: FastAPI `Query(List[str])` and comma-separated single-param styles
- **Hierarchical filters**: Product/location hierarchy filters (segment → family → class; zone → store)
- **Sorting**: `sort_by`/`sort_order` or `order_by`/`direction` with column name mapping
- **Search**: Multi-field case-insensitive substring matching
- **Response metadata**: `total_records`, `total_pages`, `has_next`, `has_prev` conventions
- **QueryBuilder pattern**: Parameterized SQL construction with filter/sort/pagination separation
- **Repository pagination**: Parallel count + data query execution
- **Pydantic query models**: Encapsulating filters, pagination, sorting, and search in typed models

## Origin

This skill derives from real production backend services handling inventory, forecasting, and order data. It distills conventions observed across multiple services with large datasets (10k-1M+ records per tenant) requiring efficient pagination, multi-dimensional filtering, and flexible sorting.

## Relation to other skills

- **Cross-reference**: `python-dao-and-database` for DAO-level pagination (`get_paginated_response`)
- **Cross-reference**: `fastapi-service-patterns` for ResponseData envelope, dependency injection, and Pydantic models
- **Complement**: This skill focuses on **API-level** query params and response metadata; `python-dao-and-database` covers **DAO-level** query construction and session management
- **Complement**: Use this skill for the HTTP contract; use `fastapi-service-patterns` for the service structure around it

## Usage

Use this skill when:

- Designing a new list endpoint with pagination, filtering, or sorting
- Implementing multi-value or hierarchical filters (e.g., segment/family/class filters)
- Building repository/query builder layers that translate query params to SQL
- Adding search across multiple fields to a list endpoint
- Standardizing response metadata across paginated endpoints
- Reviewing endpoint consistency for pagination patterns
- Adding sort capabilities to existing endpoints
