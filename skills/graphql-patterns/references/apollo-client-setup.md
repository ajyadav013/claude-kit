# Apollo Client Setup (Frontend)

Comprehensive Apollo Client setup patterns for React applications with authentication, multi-tenancy, file uploads, and error handling.

## Full Client Setup

```typescript
import { ApolloClient, InMemoryCache, from } from '@apollo/client';
import { setContext } from '@apollo/client/link/context';
import { onError } from '@apollo/client/link/error';
import { createUploadLink } from 'apollo-upload-client';

/**
 * Get the GraphQL API URL.
 * Uses VITE_BACKEND_URL if set (for production/SIT), otherwise falls back to relative path (for local dev with proxy).
 */
function getGraphqlUrl(): string {
  const backendUrl = import.meta.env.VITE_BACKEND_URL;
  if (backendUrl) {
    // Remove trailing slash and append graphql path
    const baseUrl = backendUrl.replace(/\/+$/, '');
    return `${baseUrl}/graphql`;
  }
  // Fallback to relative path (works with Vite proxy in local dev)
  return "/graphql";
}

// Use createUploadLink for file upload support (GraphQL multipart request spec)
// Apollo Server 4 requires preflight headers for CSRF protection
const httpLink = createUploadLink({
  uri: getGraphqlUrl(),
  headers: {
    'apollo-require-preflight': 'true',
  },
});

const authLink = setContext((_, { headers }) => {
  const token = localStorage.getItem('app_token');
  const orgId = localStorage.getItem('app_org_id');

  return {
    headers: {
      ...headers,
      authorization: token ? `Bearer ${token}` : '',
      // Multi-tenancy: Include org context header
      ...(orgId && { 'x-org-id': orgId }),
    },
  };
});

const errorLink = onError(({ graphQLErrors, networkError }) => {
  if (graphQLErrors) {
    graphQLErrors.forEach(({ message, locations, path, extensions }) => {
      console.error(
        `[GraphQL error]: Message: ${message}, Location: ${locations}, Path: ${path}`
      );

      // Handle authentication errors - but not on login/register pages
      // to avoid redirect loops and allow showing error messages
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

  if (networkError) {
    console.error(`[Network error]:`, networkError);
    // Log more details for 400 errors
    if ('statusCode' in networkError && networkError.statusCode === 400) {
      console.error('[400 Bad Request] Details:', {
        message: networkError.message,
        result: (networkError as any).result,
        statusCode: (networkError as any).statusCode,
      });
    }
  }
});

export const apolloClient = new ApolloClient({
  link: from([errorLink, authLink, httpLink]),
  cache: new InMemoryCache({
    typePolicies: {
      Query: {
        fields: {
          jobs: {
            merge(_existing, incoming) {
              return incoming;
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
  defaultOptions: {
    watchQuery: {
      fetchPolicy: 'cache-and-network',
    },
  },
});
```

## Key Points

### Link Order

```typescript
link: from([errorLink, authLink, httpLink])
```

**Why this order**: 
- Error link first — intercepts errors from the entire chain
- Auth link second — injects headers before the request goes out
- HTTP link last — actually sends the request

### File Upload Support

```typescript
import { createUploadLink } from 'apollo-upload-client';

const httpLink = createUploadLink({
  uri: getGraphqlUrl(),
  headers: { 'apollo-require-preflight': 'true' },
});
```

**Why**: `createUploadLink` implements the [GraphQL multipart request spec](https://github.com/jaydenseric/graphql-multipart-request-spec) for file uploads. Use this even if you don't have file uploads yet — it's a drop-in replacement for `createHttpLink` and future-proofs the client.

**CSRF preflight**: The `apollo-require-preflight` header is required by Apollo Server 4 for CSRF protection. Strawberry GraphQL doesn't need it, but including it is harmless and makes the client compatible with both backends.

### Authentication Link

```typescript
const authLink = setContext((_, { headers }) => {
  const token = localStorage.getItem('app_token');
  const orgId = localStorage.getItem('app_org_id');

  return {
    headers: {
      ...headers,  // Preserve operation-specific headers
      authorization: token ? `Bearer ${token}` : '',
      ...(orgId && { 'x-org-id': orgId }),
    },
  };
});
```

**Key points**:
- Spread existing `headers` to preserve operation-specific headers (e.g., from `context` in `useQuery`/`useMutation`)
- Use conditional spread `...(orgId && { ... })` to only include the org header if `orgId` exists
- Return empty string for `authorization` if no token (don't omit the header entirely — some backends differentiate between missing and empty)

### Error Link for UNAUTHENTICATED

```typescript
const errorLink = onError(({ graphQLErrors, networkError }) => {
  if (graphQLErrors) {
    graphQLErrors.forEach(({ message, locations, path, extensions }) => {
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
});
```

**Why the auth-page check**: If you redirect from `/login` itself, you create an infinite loop. The check allows login/register pages to display error messages (e.g., "Invalid credentials") instead of redirecting.

**SSO variant**: Use `startsWith('/sso')` to cover SSO callback paths like `/sso/callback`, `/sso/microsoft`, etc.

### Network Error Debugging

```typescript
if (networkError) {
  console.error(`[Network error]:`, networkError);
  // Log more details for 400 errors
  if ('statusCode' in networkError && networkError.statusCode === 400) {
    console.error('[400 Bad Request] Details:', {
      message: networkError.message,
      result: (networkError as any).result,
      statusCode: (networkError as any).statusCode,
    });
  }
}
```

**Why**: 400 errors often indicate schema mismatches (e.g., wrong input type, missing required field). Logging the `result` field (which contains the GraphQL response body) helps debug these during development.

### InMemoryCache typePolicies

```typescript
cache: new InMemoryCache({
  typePolicies: {
    Query: {
      fields: {
        jobs: { merge(_existing, incoming) { return incoming; } },
        candidates: { merge(_existing, incoming) { return incoming; } },
      },
    },
  },
})
```

**Why**: By default, Apollo's `InMemoryCache` concatenates arrays when merging. For paginated fields (e.g., `jobs`, `candidates`), this means:
- Page 1: `[job1, job2, job3]`
- Page 2: `[job1, job2, job3, job4, job5, job6]` ❌ duplicates!

The `merge` function replaces the entire array with the incoming data, which is the correct behavior for "replace-on-refetch" pagination (common with Relay-style cursors or offset/limit).

**When to keep the default**: Use the default merge behavior (concatenation) for infinite-scroll "load more" UIs where you want to accumulate results.

### Default Fetch Policy

```typescript
defaultOptions: {
  watchQuery: { fetchPolicy: 'cache-and-network' },
}
```

**Options**:
- `cache-and-network` (recommended default): Show cached data immediately, refetch in background, update UI when fresh data arrives. Best UX for most apps.
- `cache-first`: Show cached data, only fetch from network if not in cache. Use for rarely-changing data (e.g., config, reference data).
- `network-only`: Always fetch from network, ignore cache. Use for auth contexts where stale data can cause permission errors.
- `cache-only`: Never fetch from network, only use cache. Use for offline-first apps.

### Dynamic GraphQL URL

```typescript
function getGraphqlUrl(): string {
  const backendUrl = import.meta.env.VITE_BACKEND_URL;
  if (backendUrl) {
    const baseUrl = backendUrl.replace(/\/+$/, '');
    return `${baseUrl}/graphql`;
  }
  return "/graphql";
}
```

**Pattern**:
- **Production/SIT**: Set `VITE_BACKEND_URL=https://api.example.com` in `.env.production`
- **Local dev**: Omit `VITE_BACKEND_URL`, let Vite proxy `/graphql` to `localhost:8000/graphql`

**Vite proxy config** (for local dev):
```typescript
// vite.config.ts
export default defineConfig({
  server: {
    proxy: {
      '/graphql': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
});
```

## Multiple Auth Contexts (Advanced)

For apps with multiple user types (e.g., admin, vendor, candidate), create separate Apollo clients with different token storage keys and endpoints:

```typescript
// Vendor client
const vendorAuthLink = setContext((_, { headers }) => {
  const token = localStorage.getItem('vendor_token');
  return {
    headers: {
      ...headers,
      authorization: token ? `Bearer ${token}` : '',
    },
  };
});

export const vendorApolloClient = new ApolloClient({
  link: from([vendorErrorLink, vendorAuthLink, httpLink]),
  cache: new InMemoryCache(),
  defaultOptions: {
    watchQuery: { fetchPolicy: 'network-only' },  // No cache for vendor auth
  },
});

// Candidate client (similar pattern)
```

**Why separate clients**: Each user type has its own token, logout behavior, and possibly different GraphQL endpoints. Using one client with conditional logic is fragile and error-prone.

## Dependencies

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

## Related Patterns

- See [strawberry-backend.md](./strawberry-backend.md) for backend GraphQL setup
- See [when-to-use-graphql.md](./when-to-use-graphql.md) for decision criteria
