# Apollo Client Frontend Patterns

How to set up and use Apollo Client in a React + Vite frontend application.

## Apollo Client Setup

From `src/graphql/client.ts` in a production React application:

```typescript
import { ApolloClient, InMemoryCache, from } from '@apollo/client';
import { setContext } from '@apollo/client/link/context';
import { onError } from '@apollo/client/link/error';
import { createUploadLink } from 'apollo-upload-client';

// HTTP link with file upload support
const httpLink = createUploadLink({
  uri: getGraphqlUrl(),
  headers: {
    'apollo-require-preflight': 'true',  // Apollo Server 4 CSRF protection
  },
});

// Auth link: inject JWT + org context
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

// Error link: handle auth failures
const errorLink = onError(({ graphQLErrors, networkError }) => {
  if (graphQLErrors) {
    graphQLErrors.forEach(({ message, extensions }) => {
      if (extensions?.code === 'UNAUTHENTICATED') {
        const isAuthPage = window.location.pathname === '/login' ||
                          window.location.pathname === '/register' ||
                          window.location.pathname.startsWith('/sso');

        if (!isAuthPage) {
          localStorage.removeItem('app_token');
          localStorage.removeItem('app_user');
          window.location.href = '/login';
        }
      }
    });
  }
  if (networkError) console.error('[Network error]:', networkError);
});

export const apolloClient = new ApolloClient({
  link: from([errorLink, authLink, httpLink]),  // Order matters!
  cache: new InMemoryCache({
    typePolicies: {
      Query: {
        fields: {
          jobs: { merge(_existing, incoming) { return incoming; } },
          candidates: { merge(_existing, incoming) { return incoming; } },
        },
      },
    },
  }),
  defaultOptions: {
    watchQuery: { fetchPolicy: 'cache-and-network' },
  },
});
```

**Key points**:
- **Link order**: `from([errorLink, authLink, httpLink])` — error handling first, auth second, network last
- **Multi-tenancy**: Inject `x-org-id` header from localStorage in authLink
- **Auth error handling**: Redirect to `/login` on `UNAUTHENTICATED`, but skip redirect if already on auth pages (prevents loops)
- **InMemoryCache merge policies**: Replace incoming data rather than appending for `jobs` and `candidates` fields
- **Default fetch policy**: `cache-and-network` shows cached data immediately while refetching

## Dynamic GraphQL URL

From `src/graphql/client.ts`:

```typescript
function getGraphqlUrl(): string {
  const backendUrl = import.meta.env.VITE_BACKEND_URL;
  if (backendUrl) {
    const baseUrl = backendUrl.replace(/\/+$/, '');
    return `${baseUrl}/graphql`;
  }
  return "/graphql";  // Fallback to relative path (Vite proxy)
}
```

**Why**: Production/SIT uses absolute URL from env var; local dev uses relative path that Vite proxy rewrites to backend.

## Apollo Provider

From `src/main.tsx`:

```tsx
import { ApolloProvider } from "@apollo/client";
import { apolloClient } from "./graphql/client";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <ConfigProvider>
      <ApolloProvider client={apolloClient}>
        <BrowserRouter>
          <ThemeProvider>
            <AuthProvider>
              <OrgProvider>
                <App />
              </OrgProvider>
            </AuthProvider>
          </ThemeProvider>
        </BrowserRouter>
      </ApolloProvider>
    </ConfigProvider>
  </React.StrictMode>
);
```

**Why**: Wrap the app with `ApolloProvider` to make the client available to all components via hooks.

## Query Definitions

From `src/graphql/queries/defaultDashboard.ts`:

```typescript
import { gql } from '@apollo/client';

export const GET_DEFAULT_DASHBOARD = gql`
  query GetDefaultDashboard($orgId: ID!) {
    defaultDashboard(orgId: $orgId) {
      metrics {
        openPositions
        openPositionsChange
        activeCandidates
        interviewsToday
        totalApplications
        avgTimeToHire
      }
      activePositions {
        id
        title
        department
        status
        pipelineStages { name count order }
        totalCandidates
      }
      pendingTasks {
        id
        type
        title
        dueDate
        isOverdue
      }
    }
  }
`;

export type {
  DashboardMetrics,
  ActivePosition,
  PendingTask,
} from './hiringManagerDashboard';
```

**Key points**:
- Use `gql` template tag for query definition
- Export manually-defined TypeScript types (no codegen)
- Flat query structure — no fragments
- Keep queries in `src/graphql/queries/` directory

## Mutation Definitions

From `src/graphql/enrichment.ts`:

```typescript
import { gql } from '@apollo/client';

export const ENRICH_CANDIDATE_MUTATION = gql`
  mutation EnrichCandidate($input: EnrichCandidateInput!) {
    enrichCandidate(input: $input) {
      enrichment {
        id
        candidateId
        provider
        status
        email
        phone
        linkedinUrl
        companyName
      }
      fromCache
      comparisons {
        field
        currentValue
        enrichedValue
        isDifferent
      }
    }
  }
`;

export const APPLY_ENRICHMENT_MUTATION = gql`
  mutation ApplyEnrichment($input: ApplyEnrichmentInput!) {
    applyEnrichment(input: $input) {
      id
      name
      email
      phone
      isEnriched
    }
  }
`;
```

**Key points**:
- Mutations also use `gql` template tag
- Keep feature-related mutations grouped in one file (e.g., `enrichment.ts`)
- Input types are manually defined on backend; no codegen on frontend

## Using Queries in Components

From `src/components/JobVersionHistory.tsx`:

```tsx
import { useQuery, useMutation, gql } from "@apollo/client";

const { data, loading, refetch } = useQuery(GET_JOB_VERSION_HISTORY, {
  variables: { jobId, limit: 20 },
});

const [restoreVersion, { loading: restoring }] = useMutation(RESTORE_JOB_VERSION);

// Trigger refetch after mutation
await restoreVersion({ variables: { jobId, versionId } });
await refetch();
```

**Key points**:
- Destructure `{ data, loading, error }` from `useQuery`
- Pass `variables` as option
- Destructure `refetch` when you need to manually re-query
- `useMutation` returns `[mutate, { loading, error }]`

From `src/components/EnrichmentPanel.tsx`:

```tsx
import { useMutation, useQuery } from '@apollo/client';

const [enrichCandidate, { loading: enriching }] = useMutation(ENRICH_CANDIDATE_MUTATION);
const [applyEnrichment, { loading: applying }] = useMutation(APPLY_ENRICHMENT_MUTATION);

const { refetch: refetchEnrichments } = useQuery(GET_CANDIDATE_ENRICHMENTS, {
  variables: { candidateId },
  skip: true,  // Don't run on mount; only call refetch() manually
});

// Call mutations
await enrichCandidate({ variables: { input: { candidateId, provider } } });
await applyEnrichment({ variables: { input: { candidateId, fields } } });
await refetchEnrichments();
```

**Key points**:
- Use `skip: true` when you don't want to run the query on mount
- Call `refetch()` to manually trigger the query later
- Rename destructured values (e.g., `loading: enriching`) to avoid conflicts

## File Structure

```
src/graphql/
├── client.ts              # Apollo Client setup (links, cache, policies)
├── enrichment.ts          # Enrichment mutations
└── queries/
    ├── defaultDashboard.ts
    ├── hiringManagerDashboard.ts
    └── recruiterDashboard.ts
```

**Why**: Separate client setup from queries/mutations; group queries by feature or dashboard type.

## Dependencies

From `package.json`:

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

**Why**: `apollo-upload-client` provides `createUploadLink` for file uploads; types package for TypeScript support.
