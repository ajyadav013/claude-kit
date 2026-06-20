# Example Patterns

Real-world production patterns demonstrating each GraphQL convention.

## Backend: Strawberry GraphQL

### Schema-Per-Endpoint Pattern

**File**: `app/v1/vendor/graphql/schema.py`

```python
import strawberry
from app.v1.vendor.graphql.query import (
    CategoryQuery, AllCategoryQuery, ClusterQuery, AllClusterQuery,
    FormatQuery, AllFormatQuery, ...
)

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
# ... 11 total schemas for different filter types
```

**Evidence**: One `strawberry.Schema` per query class, each serving a specific dropdown/filter use case. Note the "All*" vs regular schema pattern: regular schemas join the Audit table and filter by active records, while "All*" schemas skip that filter for admin/unfiltered views.

### @strawberry.type Query Classes

**File**: `app/v1/vendor/graphql/query.py`

```python
@strawberry.type
class CategoryQuery:
    @strawberry.field
    async def list_categories(self, page: str='', internal_status: Optional[str]='') -> List[Optional[str]]:
        async_gen = get_connection_handler_for_app()
        connection_handler = await async_gen.__anext__()

        try:
            query = (select(distinct(Vendor.category))
                    .where(Vendor.category != None)
                    .order_by(asc(Vendor.category)))
            result = await connection_handler.session.execute(query)
            categories = result.scalars().all()
            return sorted(list(set(categories)), key=str.lower)
        finally:
            await connection_handler.close()
```

**Evidence**: `@strawberry.type` decorates class; `@strawberry.field` decorates resolver method; async DB access with `try/finally` close pattern.

### Async Connection Handler Pattern

**File**: `app/v1/vendor/graphql/query.py`

```python
async_gen = get_connection_handler_for_app()  # Get async generator
connection_handler = await async_gen.__anext__()  # Get first instance

try:
    result = await connection_handler.session.execute(query)
    # ... process results
finally:
    await connection_handler.close()  # CRITICAL: always close
```

**Evidence**: All 11 query classes use this exact pattern: `CategoryQuery`, `AllCategoryQuery`, `ClusterQuery`, `AllClusterQuery`, `SourcingClusterQuery`, `AllSourcingClusterQuery`, `CommercialClusterQuery`, `AllCommercialClusterQuery`, `FormatQuery`, `AllFormatQuery`, `ProfileStatusQuery`.

### Mounting GraphQL Routers

**File**: `app/v1/vendor/router.py`

```python
from strawberry.fastapi import GraphQLRouter
from app.v1.vendor.graphql.schema import (
    category_schema, cluster_schema, format_schema, ...
)

# Separate router for GraphQL filters
filter_graphql_router = APIRouter(prefix="/filter-graphql", route_class=CustomRequestRoute)

category_graphql_app = GraphQLRouter(category_schema)
filter_graphql_router.include_router(
    category_graphql_app,
    prefix="/category",
    tags=['admin', 'member']
)

# ... 10 more GraphQL routers mounted similarly (11 total)
```

**Evidence**: GraphQL routers coexist with REST routes under `/vendor-info/filter-graphql/` prefix; each schema gets its own sub-path.

### Scalar Types

**File**: `app/v1/vendor/graphql/type.py`

```python
import strawberry

ClusterType = strawberry.scalar(str, name="ClusterType")
CategoryType = strawberry.scalar(str, name="CategoryType")
FormatType = strawberry.scalar(str, name="FormatType")
# ... 6 scalar type declarations
```

**Evidence**: Nominal types for string scalars (though queries return `List[Optional[str]]` directly, these may be legacy).

## Frontend: Apollo Client

### Apollo Client Setup with Link Chain

**File**: `frontend/src/graphql/client.ts`

```typescript
import { ApolloClient, InMemoryCache, from } from '@apollo/client';
import { setContext } from '@apollo/client/link/context';
import { onError } from '@apollo/client/link/error';
import { createUploadLink } from 'apollo-upload-client';

const httpLink = createUploadLink({
  uri: getGraphqlUrl(),
  headers: { 'apollo-require-preflight': 'true' },
});

const authLink = setContext((_, { headers }) => {
  const token = localStorage.getItem('app_token');
  const orgId = localStorage.getItem('app_org_id');
  return {
    headers: {
      ...headers,
      authorization: token ? `Bearer ${token}` : '',
      ...(orgId && { 'x-org-id': orgId }),  // Multi-tenancy header
    },
  };
});

const errorLink = onError(({ graphQLErrors }) => {
  if (graphQLErrors) {
    graphQLErrors.forEach(({ extensions }) => {
      if (extensions?.code === 'UNAUTHENTICATED') {
        const isAuthPage = window.location.pathname === '/login' || ...;
        if (!isAuthPage) {
          localStorage.removeItem('app_token');
          window.location.href = '/login';
        }
      }
    });
  }
});

export const apolloClient = new ApolloClient({
  link: from([errorLink, authLink, httpLink]),
  cache: new InMemoryCache({ typePolicies: { ... } }),
  defaultOptions: {
    watchQuery: { fetchPolicy: 'cache-and-network' },
  },
});
```

**Evidence**: Link chain order (error → auth → http); multi-tenancy header injection; auth page check to avoid redirect loops; `cache-and-network` fetch policy.

### InMemoryCache Merge Policies

**File**: `frontend/src/graphql/client.ts`

```typescript
cache: new InMemoryCache({
  typePolicies: {
    Query: {
      fields: {
        jobs: {
          merge(_existing, incoming) {
            return incoming;  // Replace, don't append
          },
        },
        candidates: {
          merge(_existing, incoming) {
            return incoming;
          },
        },
      },
    },
  },
}),
```

**Evidence**: Explicit merge policies prevent cache concatenation for list fields.

### Apollo Provider

**File**: `frontend/src/main.tsx`

```tsx
import { ApolloProvider } from "@apollo/client";
import { apolloClient } from "./graphql/client";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <ConfigProvider>
      <ApolloProvider client={apolloClient}>
        <BrowserRouter>
          <AuthProvider>
            <App />
          </AuthProvider>
        </BrowserRouter>
      </ApolloProvider>
    </ConfigProvider>
  </React.StrictMode>
);
```

**Evidence**: App wrapped in `ApolloProvider` to make client available via hooks.

### Hand-Typed Query Definitions

**File**: `frontend/src/graphql/queries/defaultDashboard.ts`

```typescript
import { gql } from '@apollo/client';

export const GET_DEFAULT_DASHBOARD = gql`
  query GetDefaultDashboard($orgId: ID!) {
    defaultDashboard(orgId: $orgId) {
      metrics {
        openPositions
        activeCandidates
        interviewsToday
      }
      activePositions { id title department }
      pendingTasks { id type title dueDate }
    }
  }
`;

export type {
  DashboardMetrics,
  ActivePosition,
} from './hiringManagerDashboard';
```

**Evidence**: `gql` template tag for query; manually-defined TypeScript types exported separately; no codegen.

### Hand-Typed Mutation Definitions

**File**: `frontend/src/graphql/enrichment.ts`

```typescript
export const ENRICH_CANDIDATE_MUTATION = gql`
  mutation EnrichCandidate($input: EnrichCandidateInput!) {
    enrichCandidate(input: $input) {
      enrichment { id candidateId provider status email phone }
      fromCache
      comparisons { field currentValue enrichedValue isDifferent }
    }
  }
`;

export const APPLY_ENRICHMENT_MUTATION = gql`
  mutation ApplyEnrichment($input: ApplyEnrichmentInput!) {
    applyEnrichment(input: $input) {
      id name email phone isEnriched
    }
  }
`;
```

**Evidence**: Multiple mutations grouped by feature; flat structure; no fragments.

### useQuery in Components

**File**: `frontend/src/components/CountrySelect.tsx`

```tsx
import { useQuery, gql } from "@apollo/client";

const { data, loading } = useQuery<{ countries: Country[] }>(COUNTRIES_QUERY);
const countryList = data?.countries || [];
```

**Evidence**: Standard `useQuery` pattern with type annotation and null-safe access.

### useMutation in Components

**File**: `frontend/src/components/JobVersionHistory.tsx`

```tsx
import { useQuery, useMutation, gql } from "@apollo/client";

const { data, loading, refetch } = useQuery(GET_JOB_VERSION_HISTORY, {
  variables: { jobId, limit: 20 },
});

const [restoreVersion, { loading: restoring }] = useMutation(RESTORE_JOB_VERSION);

// After mutation, refetch
await restoreVersion({ variables: { jobId, versionId } });
await refetch();
```

**Evidence**: `useMutation` returns `[mutate, { loading }]`; `refetch` from `useQuery` used to refresh data.

**File**: `frontend/src/components/EnrichmentPanel.tsx`

```tsx
const [enrichCandidate, { loading: enriching }] = useMutation(ENRICH_CANDIDATE_MUTATION);
const [applyEnrichment, { loading: applying }] = useMutation(APPLY_ENRICHMENT_MUTATION);

const { refetch: refetchEnrichments } = useQuery(GET_CANDIDATE_ENRICHMENTS, {
  variables: { candidateId },
  skip: true,  // Don't run on mount
});
```

**Evidence**: Multiple mutations in one component; `skip: true` for manual query triggering; renamed destructured values to avoid conflicts.

### Dependencies

**File**: `frontend/package.json`

```json
{
  "dependencies": {
    "@apollo/client": "^3.8.8",
    "apollo-upload-client": "^17.0.0"
  },
  "devDependencies": {
    "@types/apollo-upload-client": "^17.0.5"
  }
}
```

**Evidence**: `apollo-upload-client` for file upload support; types for TypeScript.

## Pattern Summary

**Backend services with Strawberry GraphQL**:
- Vendor filter service — filter GraphQL endpoints

**Frontend applications with Apollo Client**:
- Dashboard application — dashboard queries, enrichment mutations, file uploads

**Limited footprint**: GraphQL is used in ~2 applications. Most services use pure REST.
