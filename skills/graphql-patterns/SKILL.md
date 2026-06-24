---
name: graphql-patterns
description: Tactical Strawberry GraphQL (backend) and Apollo Client (frontend) patterns from production FastAPI and React services. Use when implementing GraphQL filter/dropdown endpoints alongside REST in FastAPI, mounting Strawberry schemas with GraphQLRouter, setting up Apollo Client with JWT authentication and multi-tenancy headers, writing hand-typed gql queries/mutations without codegen, debugging Apollo link chains or InMemoryCache merge policies, or adding file upload support with apollo-upload-client. Note this is a limited-footprint pattern (used in ~2 apps) — not the organizational default.
---

# GraphQL Patterns

Tactical GraphQL patterns for Strawberry (backend) and Apollo Client (frontend) from production services.

## When to use

- Implementing GraphQL filter/dropdown endpoints alongside REST APIs in FastAPI
- Setting up Apollo Client with JWT auth, org context headers, and error handling
- Writing hand-typed GraphQL queries/mutations without codegen
- Mounting multiple narrow-scope GraphQL schemas for specific use cases (filters, dashboards)
- Understanding where GraphQL is used in the codebase (limited footprint: filter API services, dashboard applications)

**NOTE**: This is a tactical pattern used in ~2 applications. It is **not** the organizational default — most services use pure REST. Use this skill when working on or extending these specific GraphQL-enabled apps.

## Core conventions

### Backend: Strawberry GraphQL with FastAPI

**Schema-per-endpoint pattern**: Define one `strawberry.Schema` per query type (e.g., `product_schema`, `category_schema`, `region_schema`, `supplier_region_schema`, `format_schema`), then mount each schema to its own GraphQL router under a shared prefix. The reference service has 11 schemas total for filters: product, all_product, category, all_category, region, all_region, supplier_region, all_supplier_region, format, all_format, approval_stage. _(filter API service)_

**Narrow query classes**: Use `@strawberry.type` decorated classes with single-purpose `@strawberry.field` methods. Each query returns `List[Optional[str]]` or scalar types — no complex nested resolvers. _(filter API service)_

**Async DB access in resolvers**: Call `get_connection_handler_for_app()` async generator, `await async_gen.__anext__()` to get the connection, execute SQLAlchemy queries, and **always** `await connection_handler.close()` in a `try/finally` block. _(filter API service)_

**Mount with `strawberry.fastapi.GraphQLRouter`**: Create a `GraphQLRouter(schema)`, then `include_router(graphql_app, prefix="/products", tags=[...])` under a shared `APIRouter(prefix="/filter-graphql")`. _(filter API router)_

**Coexist with REST**: GraphQL endpoints live under a versioned API prefix (e.g., `/v1/catalog/filter-graphql/products`) alongside traditional REST routes. GraphQL is supplementary, not a replacement. _(filter API router)_

**Scalar types for simple enums**: Use `strawberry.scalar(str, name="ProductType")` for typed scalars when you need nominal typing but the underlying type is a string. _(filter API types)_

### Frontend: Apollo Client Setup

**Link composition**: Compose links in order: `from([errorLink, authLink, httpLink])`. Use `createUploadLink` from `apollo-upload-client` for file upload support. _(dashboard client)_

**Auth link**: Use `setContext` to inject `Authorization: Bearer <token>` from localStorage and multi-tenancy headers (e.g., `x-org-id`) into every request. _(dashboard client)_

**Error link for auth failures**: Use `onError` to catch `UNAUTHENTICATED` GraphQL errors, clear tokens, and redirect to `/login` — but skip this on auth pages to avoid redirect loops. _(dashboard client)_

**InMemoryCache with typePolicies**: Configure `merge` policies for paginated/list fields (e.g., `jobs`, `candidates`) to replace rather than append: `merge(_existing, incoming) { return incoming; }`. _(dashboard client)_

**`cache-and-network` default fetch policy**: Set `defaultOptions.watchQuery.fetchPolicy = 'cache-and-network'` to show cached data immediately while refetching in the background. _(dashboard client)_

**Dynamic GraphQL URL**: Compute the GraphQL endpoint URL from `VITE_BACKEND_URL` env var (prod/SIT) or fall back to a relative path (local dev with Vite proxy). _(dashboard client)_

**Apollo Server 4 CSRF preflight**: Include `'apollo-require-preflight': 'true'` in httpLink headers when the backend uses Apollo Server 4 (though Strawberry doesn't need this). _(dashboard client)_

### Frontend: Writing Queries and Mutations

**Hand-typed operations**: Use `gql` template tag to define queries/mutations inline. Export TypeScript types manually (no codegen). _(dashboard app)_

**Fragment-free**: Queries are flat and specific to the component; no shared fragments. _(dashboard queries)_

**Inline `gql` in query files**: Keep queries in `src/graphql/queries/` and mutations in `src/graphql/<feature>.ts`; export both the `gql` document and manually-defined TypeScript types. _(dashboard structure)_

**useQuery/useMutation in components**: Import the `gql` document, call `useQuery(GET_DASHBOARD, { variables })` or `useMutation(ENRICH_CANDIDATE)`, destructure `{ data, loading, error }` or `[mutate, { loading }]`. _(dashboard components)_

**Refetch via returned function**: Destructure `refetch` from `useQuery` when you need to manually re-query (e.g., after a mutation). _(enrichment component)_

### Apollo Client setup (frontend)

**Link composition with file upload support**: Use `createUploadLink` from `apollo-upload-client` (instead of `createHttpLink`) for GraphQL multipart request spec file upload support. Compose links in order: `from([errorLink, authLink, httpLink])` — error handling first, auth injection second, network transport last.

**CSRF preflight header**: Include `'apollo-require-preflight': 'true'` in httpLink headers when the backend uses Apollo Server 4 CSRF protection (Strawberry doesn't require this, but it's harmless and future-proof). Preflight protects the GraphQL transport by forcing a non-"simple" request; it is **not** a substitute for a CSRF token if the API authenticates via a **cookie/session** (rather than an `Authorization` header) — see the *Cross-Site Request Forgery (CSRF)* section of `security-and-hardening` for the token pattern.

**Auth link via `setContext`**: Use `setContext` from `@apollo/client/link/context` to inject `Authorization: Bearer <token>` from localStorage and any tenant/org context headers (e.g., `x-org-id`) into every request. Spread existing headers to avoid clobbering operation-specific headers.

**Error link for UNAUTHENTICATED handling**: Use `onError` from `@apollo/client/link/error` to catch GraphQL errors with `extensions.code === 'UNAUTHENTICATED'`, clear auth tokens, and redirect to `/login`. **Critical**: check if the user is already on an auth page (login, register, SSO) before redirecting to prevent infinite loops — allow error messages to show on auth pages.

**Network error debugging**: In the `onError` handler, log network errors. For 400 errors, log additional details (`statusCode`, `result`, `message`) to debug malformed requests or schema mismatches during development.

**InMemoryCache with typePolicies**: Configure `merge` functions for paginated or list fields (e.g., `jobs`, `candidates`) to replace incoming data rather than appending: `merge(_existing, incoming) { return incoming; }`. The default merge behavior concatenates arrays, which breaks pagination resets.

**Default fetch policy**: Set `defaultOptions.watchQuery.fetchPolicy = 'cache-and-network'` to show cached data immediately while refetching in the background. This provides instant UI feedback with fresh data on the way. Use `network-only` for auth contexts where stale data can cause permission errors.

**Dynamic GraphQL URL**: Compute the GraphQL endpoint from an env var (e.g., `VITE_BACKEND_URL`) for production/SIT, or fall back to a relative path (e.g., `/graphql`) for local dev with a Vite proxy. Strip trailing slashes from the base URL before appending `/graphql`.

See [apollo-client-setup.md](./references/apollo-client-setup.md) for full setup code and patterns.

## Skeleton / example

```python
# Backend: filter API pattern
import strawberry
from typing import List, Optional
from app.connection import get_connection_handler_for_app
from sqlalchemy import select, distinct, asc

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
            query = select(distinct(Product.category)).where(Product.category != None)
            result = await connection_handler.session.execute(query)
            categories = result.scalars().all()
            return sorted(list(set(categories)), key=str.lower)
        finally:
            await connection_handler.close()

# Schema and router
from strawberry.fastapi import GraphQLRouter

product_schema = strawberry.Schema(query=ProductQuery)
filter_graphql_router = APIRouter(prefix="/filter-graphql")

product_graphql_app = GraphQLRouter(product_schema)
filter_graphql_router.include_router(
    product_graphql_app,
    prefix="/products",
    tags=['admin', 'member']
)
```

```typescript
// Frontend: Apollo Client setup
import { ApolloClient, InMemoryCache, from } from '@apollo/client';
import { setContext } from '@apollo/client/link/context';
import { onError } from '@apollo/client/link/error';
import { createUploadLink } from 'apollo-upload-client';

const httpLink = createUploadLink({
  uri: import.meta.env.VITE_BACKEND_URL
    ? `${import.meta.env.VITE_BACKEND_URL}/graphql`
    : '/graphql',
  headers: { 'apollo-require-preflight': 'true' },
});

const authLink = setContext((_, { headers }) => {
  const token = localStorage.getItem('app_token');
  const orgId = localStorage.getItem('app_org_id');

  return {
    headers: {
      ...headers,
      authorization: token ? `Bearer ${token}` : '',
      ...(orgId && { 'x-org-id': orgId }),
    },
  };
});

const errorLink = onError(({ graphQLErrors, networkError }) => {
  if (graphQLErrors) {
    graphQLErrors.forEach(({ extensions }) => {
      if (extensions?.code === 'UNAUTHENTICATED') {
        const isAuthPage = window.location.pathname === '/login';
        if (!isAuthPage) {
          localStorage.removeItem('app_token');
          window.location.href = '/login';
        }
      }
    });
  }
  if (networkError) console.error('[Network error]:', networkError);
});

export const apolloClient = new ApolloClient({
  link: from([errorLink, authLink, httpLink]),
  cache: new InMemoryCache({
    typePolicies: {
      Query: {
        fields: {
          jobs: { merge(_existing, incoming) { return incoming; } },
        },
      },
    },
  }),
  defaultOptions: {
    watchQuery: { fetchPolicy: 'cache-and-network' },
  },
});

// Query definition (hand-typed)
import { gql } from '@apollo/client';

export const GET_DASHBOARD = gql`
  query GetDashboard($orgId: ID!) {
    dashboard(orgId: $orgId) {
      metrics { openPositions activeCandidates }
      activePositions { id title department }
    }
  }
`;

// Component usage
import { useQuery } from '@apollo/client';

function Dashboard({ orgId }: { orgId: string }) {
  const { data, loading, error } = useQuery(GET_DASHBOARD, {
    variables: { orgId },
  });

  if (loading) return <Spinner />;
  if (error) return <Error message={error.message} />;

  return <MetricsCard metrics={data.dashboard.metrics} />;
}
```

## Anti-patterns to avoid

- **Forgetting to close the connection handler** — always wrap DB access in `try/finally` and `await connection_handler.close()`.
- **Using GraphQL for everything** — this is a tactical pattern for filters/dashboards, not a full API replacement. Most routes should stay REST.
- **Forgetting the auth-page check in errorLink** — redirect loops occur if you clear tokens and redirect from `/login` itself.
- **Using codegen** — the pattern is hand-typed queries/mutations; don't introduce a codegen step unless explicitly agreed.
- **Nesting resolvers deeply** — Strawberry queries here are flat (scalars, lists of scalars). Keep them simple.
- **Skipping multi-tenancy headers** — include `x-org-id` or equivalent tenant context header in authLink when the backend is multi-tenant.
- **Mixing `@strawberry.type` with Pydantic** — Strawberry types are separate from FastAPI request/response models; don't conflate them.
- **Not understanding "All*" vs regular schema variants** — the reference service has pairs like `product_schema` (joins Audit, filters by active records) and `all_product_schema` (no join, returns all). The "All*" variants skip the audit filter for admin/unfiltered views.

## References

- [strawberry-backend.md](./references/strawberry-backend.md) — Strawberry schema patterns, query classes, FastAPI mounting
- [apollo-client-frontend.md](./references/apollo-client-frontend.md) — Apollo Client setup, link chain, hooks usage
- [when-to-use-graphql.md](./references/when-to-use-graphql.md) — Decision matrix: when to use GraphQL vs REST, based on codebase patterns
- [repo-evidence.md](./references/repo-evidence.md) — Real-world production patterns and examples
- [apollo-client-setup.md](./references/apollo-client-setup.md) — Advanced Apollo Client setup: auth + multi-tenant headers, file uploads, CSRF preflight, UNAUTHENTICATED handling, InMemoryCache typePolicies
