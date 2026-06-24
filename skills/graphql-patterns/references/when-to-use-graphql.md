# When to Use GraphQL (vs REST)

Decision matrix for choosing GraphQL vs REST in this codebase, based on observed usage patterns.

## Use GraphQL for

### Filter/Dropdown APIs
**Pattern**: Distinct values from database tables for frontend filter dropdowns.

**Example**: `/v1/catalog/filter-graphql/products` in a production service returns distinct product categories.

**Why GraphQL**:
- Frontend needs only the distinct values, not full records
- Query shape is simple: `{ listProducts(page: "manage-products") }`
- Multiple similar endpoints (product, category, region, format) benefit from shared schema pattern
- Client can specify exactly which filter field it needs

### Dashboard/Analytics Queries
**Pattern**: Aggregate metrics + multiple related lists in one request.

**Example**: A `defaultDashboard` query returns metrics, active positions, and pending tasks.

**Why GraphQL**:
- Avoids REST N+1 problem (would need 3+ REST endpoints)
- Frontend dictates which dashboard fields to fetch
- Different dashboard types (hiring manager vs recruiter) fetch different subsets
- Single round-trip for related data

### File Upload with Metadata
**Pattern**: Upload files alongside structured mutation input.

**Example**: Enrichment mutations with candidate data and optional file attachments.

**Why GraphQL**:
- `apollo-upload-client` handles multipart requests cleanly
- Mutation input can mix file upload with typed metadata
- Better than REST multipart/form-data for complex structured input

## Use REST for

### CRUD Operations
**Pattern**: Standard create/read/update/delete on a single resource type.

**Example**: Standard REST endpoints like `POST /v1/catalog/products`, `GET /v1/catalog/products/{id}`, `PUT /v1/catalog/products/{id}`.

**Why REST**:
- Well-understood HTTP semantics (201 Created, 204 No Content, etc.)
- Simpler caching via HTTP headers
- No need for GraphQL schema overhead
- Standard FastAPI request/response models work great

### Batch Operations
**Pattern**: Bulk create/update/delete on many records.

**Example**: Bulk product import, batch status updates.

**Why REST**:
- REST POST with array body is clearer than GraphQL mutation with array input
- Error handling for partial failures is more straightforward
- Progress tracking and streaming responses work better with HTTP

### File Download
**Pattern**: Serving static files, exports, generated reports.

**Example**: CSV exports, PDF reports, image assets.

**Why REST**:
- HTTP Content-Type, Content-Disposition headers
- Browser download behavior works out of the box
- CDN caching for static assets
- No GraphQL schema needed for binary blobs

### Webhooks / Callbacks
**Pattern**: External services calling back into your API.

**Example**: Payment gateway callbacks, OAuth redirects.

**Why REST**:
- External systems expect standard HTTP POST/GET
- No control over client (can't require GraphQL client)
- Simpler signature verification with raw request body

## Observed Codebase Pattern

**GraphQL footprint**: ~2 applications (filter API services, dashboard applications)

**REST footprint**: 15+ services, hundreds of endpoints

**Organizational default**: REST

**GraphQL use cases**:
1. Filter API service: 11 filter dropdown schemas (product, category, region, format × "All*" variants)
2. Dashboard application: Dashboard queries (metrics + lists), enrichment mutations

**Key insight**: GraphQL is used **tactically** where it solves a specific problem (avoiding N+1, flexible filtering), not as a full API replacement strategy.

## Anti-Pattern: Don't Use GraphQL Just Because

**Don't** introduce GraphQL just because:
- "It's modern" — REST is the organizational default
- "We might need flexibility later" — YAGNI
- "One endpoint to rule them all" — adds cognitive overhead
- "Avoid versioning" — GraphQL schemas still evolve and break clients

**Do** introduce GraphQL when:
- You have a real N+1 problem (dashboard aggregation)
- Multiple similar endpoints would benefit from parameterized queries (filters)
- Client-driven field selection provides measurable value
- File upload + structured input in one request simplifies the flow

## Migration Pattern

If a REST API grows complex enough to justify GraphQL:

1. **Coexist**: Mount GraphQL under a new prefix (e.g., `/filter-graphql`), keep existing REST routes
2. **Narrow scope**: Start with one specific use case (filters, dashboards), not the whole API
3. **Shared models**: Reuse SQLAlchemy models and database connection patterns
4. **Deprecate gradually**: Mark old REST endpoints deprecated, migrate clients over time
5. **Document the decision**: Update SKILL.md or ADRs so future devs know why GraphQL exists here

## Evidence

- **Filter API service GraphQL**: Only for filters (`/v1/catalog/filter-graphql/*`), not the full catalog API
- **Dashboard application GraphQL**: Only for dashboards and enrichment, not for core job/candidate CRUD
- **All other services**: Pure REST

This confirms the "tactical supplement, not replacement" pattern.
