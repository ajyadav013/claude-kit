# API Layer and Types

This file details the three API-layer strategies and the hand-written types convention.

---

## API Layer Strategy 1: Axios + react-query hooks (Reference Service A)

**Use when**: REST API with envelope-based responses (`{ data: T, message?: string }`), multi-tenant headers, structured error handling (401 → logout, 403 → unauthorized page).

### Pattern

1. **`lib/api.ts`** exports:
   - `ApiService` — thin wrapper around axios with `.get`, `.post`, `.put`, `.patch`, `.del`, `.axios` methods
   - `apiFetch<T>(path, params?)` — GET helper that prepends `API_BASE`, injects `API_HEADERS`, unwraps envelope (`res.data?.data ?? res.data`)
   - `apiPost<T>(path, data?)` — POST helper with same conventions
   - `appApiFetch<T>` / `appApiPost<T>` — application-scoped variants (prepend `API_APP_BASE`)
   - `apiFetchBlob(path, params, filename)` — download helper (triggers browser save)
   - `API_HEADERS` — dynamic Proxy that reads `X-Tenant-ID` + `X-Org-ID` from session at access time (solves multi-tenant header injection)
   - Axios interceptor — catches 401 (clear session, redirect to `/login`) and 403 (redirect to `/unauthorized`)

2. **`modules/<feature>/api/<feature>Api.ts`** exports custom react-query hooks:
   - `useSessionQuery()` → `useQuery({ queryKey: ['session'], queryFn: () => apiFetch<SessionResponse>('/session') })`
   - `useLoginMutation()` → `useMutation({ mutationFn: (credentials) => apiPost<LoginResponse>('/login', credentials) })`
   - One file per feature; exports hooks, not raw functions (hooks own the cache key + invalidation logic)

3. **Components** call the hooks:
   ```typescript
   import { useSessionQuery } from '@/modules/auth/api/authApi';

   function Header() {
     const { data: session, isLoading } = useSessionQuery();
     if (isLoading) return <LoadingSpinner />;
     return <div>Welcome, {session.user.firstName}</div>;
   }
   ```

### Code snippets

**`lib/api.ts` (ApiService wrapper):**

```typescript
export const ApiService = {
  get: (url: string, options: ApiOptions = {}): Promise<AxiosResponse> => {
    return axios.get(resolveUrl(url), { params: options.params, headers: options.headers });
  },
  post: (url: string, options: ApiOptions = {}): Promise<AxiosResponse> => {
    return axios.post(resolveUrl(url), options.data, { headers: options.headers, params: options.params });
  },
  put: (url: string, options: ApiOptions = {}): Promise<AxiosResponse> => {
    return axios.put(resolveUrl(url), options.data ?? {}, { headers: options.headers, params: options.params });
  },
  patch: (url: string, options: ApiOptions = {}): Promise<AxiosResponse> => {
    return axios.patch(resolveUrl(url), options.data, { headers: options.headers, params: options.params });
  },
  del: (url: string, options: ApiOptions = {}): Promise<AxiosResponse> => {
    return axios.delete(resolveUrl(url), { params: options.params, headers: options.headers });
  },
};
```

**`lib/api.ts` (apiFetch/apiPost helpers):**

```typescript
export async function apiFetch<T>(path: string, params?: Record<string, string | number | boolean | undefined>): Promise<T> {
  const cleanParams: Record<string, unknown> = {};
  if (params) {
    for (const [k, v] of Object.entries(params)) {
      if (v !== undefined && v !== null && v !== "") cleanParams[k] = v;
    }
  }
  const res = await ApiService.get(`${API_BASE}${path}`, { params: cleanParams, headers: API_HEADERS });
  return res.data?.data ?? res.data; // unwrap envelope or return raw data
}

export async function apiPost<T>(path: string, data?: unknown): Promise<T> {
  const res = await ApiService.post(`${API_BASE}${path}`, { data, headers: API_HEADERS });
  return res.data?.data ?? res.data;
}
```

**`lib/api.ts` (API_HEADERS proxy):**

```typescript
export function getDynamicHeaders(): Record<string, string> {
  return { "X-Tenant-ID": getActiveTenantId(), "X-Org-ID": getActiveOrgUuid() };
}

// Backward-compatible dynamic proxy — reads tenant at access time
export const API_HEADERS: Record<string, string> = new Proxy({} as Record<string, string>, {
  get(_target, prop: string) { return getDynamicHeaders()[prop]; },
  ownKeys() { return Object.keys(getDynamicHeaders()); },
  getOwnPropertyDescriptor(_target, prop: string) {
    const headers = getDynamicHeaders();
    if (prop in headers) return { configurable: true, enumerable: true, value: headers[prop] };
    return undefined;
  },
});
```

Why a Proxy? Tenant ID changes when the user switches tenants. If `API_HEADERS` were a plain object, it would capture the tenant ID at module-load time and never update. The Proxy ensures every access reads the current tenant from session storage.

**`lib/api.ts` (axios interceptor):**

```typescript
axios.interceptors.response.use(
  (response: AxiosResponse) => response,
  (error: AxiosError) => {
    const status = error.response?.status;
    if (status === HttpStatusCodes.FORBIDDEN) {
      redirectToUnauthorizedPage(); // window.location.replace('/unauthorized')
      return Promise.reject(error?.response?.data ?? error);
    }
    if (status === HttpStatusCodes.UNAUTHORIZED) {
      clearAllSessionData(); // preserve biometric enrollment
      sessionStorage.setItem("app-logged-out", "1");
      window.location.pathname = "/login";
    }
    return Promise.reject(error?.response?.data ?? error);
  },
);
```

**`modules/auth/api/authApi.ts` (react-query hooks):**

```typescript
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { apiFetch, apiPost } from '@/lib/api';
import type { SessionResponse, LoginRequest, LoginResponse } from '../types/auth.types';

export function useSessionQuery() {
  return useQuery({
    queryKey: ['session'],
    queryFn: () => apiFetch<SessionResponse>('/session'),
    staleTime: 5 * 60 * 1000, // 5 minutes
  });
}

export function useLoginMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (credentials: LoginRequest) => apiPost<LoginResponse>('/login', credentials),
    onSuccess: () => {
      queryClient.invalidateQueries(['session']); // refetch session after login
    },
  });
}
```

### Pros/Cons

**Pros:**
- react-query handles caching, refetching, deduplication, invalidation automatically
- Envelope unwrapping is centralized (no `res.data.data` in every component)
- Multi-tenant headers (X-Tenant-ID, X-Org-ID) are injected dynamically via the Proxy (no manual header management)
- 401/403 handling is global (one place to update logout/unauthorized logic)

**Cons:**
- More boilerplate (each feature needs a `<feature>Api.ts` file with hooks)
- axios adds bundle size (~13 KB gzipped)
- Envelope convention is backend-specific (not universal; some APIs return flat JSON)

---

## API Layer Strategy 2: Fetch wrapper + token refresh race-guard (Reference Service B)

**Use when**: REST API with flat JSON responses (no envelope), JWT token refresh, custom error codes, multi-tenant support.

### Pattern

1. **`lib/api.ts`** exports:
   - `api.get/post/put/patch/delete<T>(endpoint, body?, options?)` — fetch wrapper that returns `T` directly (no envelope)
   - `getAccessToken()` / `setTokens()` / `clearTokens()` — localStorage helpers for `app_access_token`, `app_refresh_token`, `app_token_expiry`
   - `isTokenExpiringSoon()` — checks if token expires in < 5 minutes
   - `refreshAccessToken()` — race-guard: if `refreshPromise` is already in progress, await it; otherwise fire a new refresh and clear the promise in `finally`
   - `APIError` class — extends Error with `status`, `code`, `field`, `errors`, `meta`; includes `.is(code)`, `.isNotFound()`, `.isAuthError()`, `.isValidationError()` helpers
   - `fetchWithAuth<T>(endpoint, options)` — core wrapper: injects Bearer token, handles 401 retry (refresh token + retry), reports 5xx to Sentry

2. **Service modules** (e.g., `lib/video.ts`, `lib/analytics.ts`) call `api.*`:
   ```typescript
   export const videoService = {
     generate: (documentId: string) => api.post<Video>('/videos/generate', { document_id: documentId }),
     approve: (videoId: string, notes?: string) => api.post<void>(`/videos/${videoId}/approve`, { notes }),
   };
   ```

3. **Components/stores** call service modules or `api.*` directly (anti-pattern in reference service B: bypasses react-query cache; should wrap in `useMutation`/`useQuery`).

### Code snippets

**`lib/api.ts` (token storage):**

```typescript
const ACCESS_TOKEN_KEY = 'app_access_token';
const REFRESH_TOKEN_KEY = 'app_refresh_token';
const TOKEN_EXPIRY_KEY = 'app_token_expiry';
const REFRESH_BUFFER_MS = 5 * 60 * 1000;

export function getAccessToken(): string | null {
  return localStorage.getItem(ACCESS_TOKEN_KEY);
}

export function isTokenExpiringSoon(): boolean {
  const expiry = getTokenExpiry();
  if (!expiry) return true;
  return Date.now() > expiry - REFRESH_BUFFER_MS;
}

export function setTokens(accessToken: string, refreshToken?: string, expiresIn?: number): void {
  localStorage.setItem(ACCESS_TOKEN_KEY, accessToken);
  if (refreshToken) localStorage.setItem(REFRESH_TOKEN_KEY, refreshToken);
  if (expiresIn) {
    const expiryTime = Date.now() + expiresIn * 1000;
    localStorage.setItem(TOKEN_EXPIRY_KEY, expiryTime.toString());
  }
}
```

**`lib/api.ts` (race-guard pattern):**

```typescript
let refreshPromise: Promise<boolean> | null = null;

async function refreshAccessToken(): Promise<boolean> {
  // If refresh is already in progress, wait for it
  if (refreshPromise) return refreshPromise;

  const refreshToken = getRefreshToken();
  if (!refreshToken) return false;

  // Create the refresh promise
  refreshPromise = (async () => {
    try {
      const response = await fetch(buildUrl('/auth/refresh'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh_token: refreshToken }),
      });
      if (!response.ok) {
        clearTokens();
        return false;
      }
      const data = await response.json() as { access_token: string; refresh_token?: string; expires_in?: number };
      setTokens(data.access_token, data.refresh_token, data.expires_in);
      return true;
    } catch {
      clearTokens();
      return false;
    } finally {
      // Clear the promise so next refresh can proceed
      refreshPromise = null;
    }
  })();

  return refreshPromise;
}
```

Why this pattern? Without the race-guard, if 3 requests fire simultaneously and all receive 401, they will all call `refreshAccessToken()` at the same time, firing 3 refresh requests. The race-guard ensures only 1 refresh request fires; the other 2 await the same promise.

> Confirmed against: https://www.rfc-editor.org/rfc/rfc6749#section-6 (OAuth 2.0 token refresh flow; race condition handling is implementation-specific but widely documented in auth libraries like Auth0, Firebase, AWS Amplify)

**`lib/api.ts` (APIError class):**

```typescript
export class APIError extends Error {
  status: number;
  code: ErrorCode | (string & {});
  field: string | undefined;
  errors: FieldError[] | undefined;
  meta: Record<string, unknown> | undefined;

  constructor(message: string, status: number, code?: ErrorCode | (string & {}), field?: string, errors?: FieldError[], meta?: Record<string, unknown>) {
    super(message);
    this.name = 'APIError';
    this.code = code || 'UNKNOWN_ERROR';
    this.status = status;
    this.field = field;
    this.errors = errors;
    this.meta = meta;
  }

  is(code: ErrorCode | (string & {})): boolean {
    return this.code === code;
  }

  isNotFound(): boolean {
    return this.status === 404 || this.code.endsWith('_NOT_FOUND');
  }

  isAuthError(): boolean {
    return this.status === 401 || this.code.startsWith('AUTH_');
  }

  isValidationError(): boolean {
    return this.code === 'VALIDATION_ERROR' || this.status === 400;
  }

  getFieldError(field: string): string | undefined {
    return this.errors?.find((e) => e.field === field)?.message;
  }
}
```

**`lib/api.ts` (fetchWithAuth wrapper):**

```typescript
async function fetchWithAuth<T>(endpoint: string, options: RequestOptions = {}): Promise<T> {
  try {
    const { body, params, tenantId, skipAuth = false, ...fetchOptions } = options;

    // Proactively refresh token if it's about to expire
    if (!skipAuth) await ensureValidToken();

    const url = buildUrl(endpoint, params);
    const headers: HeadersInit = {
      'Content-Type': 'application/json',
      ...fetchOptions.headers,
    };

    if (!skipAuth) {
      const token = getAccessToken();
      if (token) (headers as Record<string, string>)['Authorization'] = `Bearer ${token}`;
    }

    if (tenantId) (headers as Record<string, string>)['X-Tenant-ID'] = tenantId;

    const config: RequestInit = { ...fetchOptions, headers, body: body !== undefined ? JSON.stringify(body) : null };
    let response = await fetch(url, config);

    // Handle 401 - try to refresh token
    if (response.status === 401 && !skipAuth) {
      const refreshed = await refreshAccessToken();
      if (refreshed) {
        const newToken = getAccessToken();
        if (newToken) (headers as Record<string, string>)['Authorization'] = `Bearer ${newToken}`;
        response = await fetch(url, { ...config, headers });
      } else {
        clearTokens();
        window.location.href = '/login';
        throw new APIError('Session expired', 401, 'SESSION_EXPIRED');
      }
    }

    if (!response.ok) {
      // Parse error from backend (uses 'detail' field)
      let errorMessage = 'An unexpected error occurred';
      let errorCode: string | undefined;
      try {
        const errorData = await response.json() as { detail?: string | { detail?: string; code?: string }; code?: string; field?: string; errors?: FieldError[]; meta?: Record<string, unknown> };
        if (typeof errorData.detail === 'object' && errorData.detail !== null) {
          errorMessage = errorData.detail.detail || errorMessage;
          errorCode = errorData.detail.code || errorData.code;
        } else {
          errorMessage = errorData.detail || errorMessage;
          errorCode = errorData.code;
        }
      } catch {
        errorMessage = response.statusText || errorMessage;
      }
      const apiError = new APIError(errorMessage, response.status, errorCode, /* ... */);
      if (response.status >= 500) Sentry.captureException(apiError); // 5xx only
      throw apiError;
    }

    if (response.status === 204) return undefined as T;
    return response.json() as Promise<T>;
  } catch (error) {
    if (!(error instanceof APIError)) Sentry.captureException(error); // network errors
    throw error;
  }
}

export const api = {
  get<T>(endpoint: string, options?: Omit<RequestOptions, 'body' | 'method'>): Promise<T> {
    return fetchWithAuth<T>(endpoint, { ...options, method: 'GET' });
  },
  post<T>(endpoint: string, body?: unknown, options?: Omit<RequestOptions, 'body' | 'method'>): Promise<T> {
    return fetchWithAuth<T>(endpoint, { ...options, method: 'POST', body });
  },
  // ... put, patch, delete
};
```

### Pros/Cons

**Pros:**
- Zero dependencies (fetch is native)
- Race-guard prevents duplicate refresh requests
- `APIError` class provides semantic error handling (`.is(code)`, `.isNotFound()`, `.isAuthError()`)
- Sentry integration (5xx + network errors only)
- Multi-tenant support via `X-Tenant-ID` header

**Cons:**
- More code to maintain (150+ lines of custom fetch logic)
- No automatic caching/deduplication (must integrate with react-query manually)
- Anti-pattern in reference service B: stores call `api.*` directly, bypassing react-query cache

---

## API Layer Strategy 3: Apollo Client + links (Reference Service C)

**Use when**: GraphQL backend, SSR, file uploads, complex multi-entity relationships (jobs, candidates, interviews).

### Pattern

1. **`graphql/client.ts`** exports `apolloClient`:
   - `authLink` (setContext) injects `Bearer app_token` + `x-org-id` header into every request
   - `errorLink` (onError) catches `UNAUTHENTICATED` errors and redirects to `/login` (unless on `/login`, `/register`, `/sso/*`)
   - `createUploadLink` (apollo-upload-client) enables file uploads via GraphQL multipart request spec
   - `InMemoryCache` with custom `typePolicies` to merge jobs/candidates arrays (prevents cache duplication)

2. **`graphql/queries/<domain>.ts`** exports `gql`` tagged templates:
   ```typescript
   export const GET_JOBS = gql`
     query GetJobs($status: String) {
       jobs(status: $status) { id title status location }
     }
   `;

   export const CREATE_JOB = gql`
     mutation CreateJob($input: CreateJobInput!) {
       createJob(input: $input) { id title }
     }
   `;
   ```

3. **Components** use Apollo hooks:
   ```typescript
   import { useQuery, useMutation } from '@apollo/client';
   import { GET_JOBS, CREATE_JOB } from '@/graphql/queries/jobs';

   function JobsPage() {
     const { data, loading } = useQuery(GET_JOBS, { variables: { status: 'active' } });
     const [createJob] = useMutation(CREATE_JOB);
     // Apollo cache handles caching/refetching automatically
   }
   ```

### Code snippets

**`graphql/client.ts`:**

```typescript
import { ApolloClient, InMemoryCache, from } from '@apollo/client';
import { setContext } from '@apollo/client/link/context';
import { onError } from '@apollo/client/link/error';
import { createUploadLink } from 'apollo-upload-client';

function getGraphqlUrl(): string {
  const backendUrl = import.meta.env.VITE_BACKEND_URL;
  if (backendUrl) {
    const baseUrl = backendUrl.replace(/\/+$/, '');
    return `${baseUrl}/graphql`;
  }
  return "/graphql"; // Vite proxy in local dev
}

const httpLink = createUploadLink({
  uri: getGraphqlUrl(),
  headers: { 'apollo-require-preflight': 'true' }, // Apollo Server 4 CSRF protection
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
    graphQLErrors.forEach(({ message, locations, path, extensions }) => {
      console.error(`[GraphQL error]: Message: ${message}, Location: ${locations}, Path: ${path}`);
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
  if (networkError) console.error(`[Network error]:`, networkError);
});

export const apolloClient = new ApolloClient({
  link: from([errorLink, authLink, httpLink]),
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

> Confirmed against: https://www.apollographql.com/docs/react/api/link/introduction (Apollo link documentation: composition via `from([errorLink, authLink, httpLink])`)

**Usage in contexts:**

```typescript
// contexts/AuthContext.tsx
import { useQuery, useMutation, gql } from '@apollo/client';

const ME_QUERY = gql`
  query Me {
    me { id email name role avatar }
  }
`;

const LOGIN_MUTATION = gql`
  mutation Login($input: LoginInput!) {
    login(input: $input) {
      token
      user { id email name role }
    }
  }
`;

export function AuthProvider({ children }: { children: ReactNode }) {
  const { data, loading } = useQuery(ME_QUERY);
  const [loginMutation] = useMutation(LOGIN_MUTATION);

  const login = async (email: string, password: string) => {
    const { data } = await loginMutation({ variables: { input: { email, password } } });
    localStorage.setItem('app_token', data.login.token);
    // Apollo cache updates automatically
  };

  return <AuthContext.Provider value={{ user: data?.me, loading, login }}>{children}</AuthContext.Provider>;
}
```

### Pros/Cons

**Pros:**
- Apollo cache handles caching/refetching automatically (no need for react-query)
- File upload support via `createUploadLink` (multipart GraphQL spec)
- Error handling is centralized in `errorLink` (UNAUTHENTICATED → redirect)
- Multi-tenancy via `x-org-id` header (injected in authLink)
- SSR-friendly (Apollo cache serializes/deserializes)

**Cons:**
- GraphQL adds backend complexity (schema design, resolver logic, N+1 query risk)
- apollo-upload-client is unmaintained (last release 2021; still works but may break)
- `typePolicies` are required to prevent cache duplication for list queries
- Bundle size (~50 KB gzipped for @apollo/client)

---

## Hand-written types convention (all three repos)

**NO OpenAPI/GraphQL codegen anywhere.** All API types are manually defined in `types/<domain>.ts` or `modules/<feature>/types/<x>.types.ts`.

### Why no codegen?

1. **Codegen is brittle** — breaks when backend schema changes; requires rebuild/restart
2. **Hand-written types are self-documenting** — comments explain business logic, not just field names
3. **Wire vs FE adapter pattern** — API DTOs differ from FE models; codegen produces only DTOs, not FE shapes
4. **Type safety is enforced at compile time** — TypeScript catches mismatches; codegen only shifts errors to build time

### Pattern

1. **API response types** in `types/<domain>.ts`:
   ```typescript
   // types/video.ts
   export interface Video {
     id: string;
     document_id: string;
     url: string | null;
     status: VideoStatus;
     created_at: string;
     updated_at: string;
   }

   export type VideoStatus = 'pending' | 'processing' | 'completed' | 'failed';
   ```

2. **Request types** (optional; often inferred from API functions):
   ```typescript
   export interface GenerateVideoRequest {
     document_id: string;
     options?: {
       style?: 'minimal' | 'detailed';
       duration?: number;
     };
   }
   ```

3. **FE models** (wire adapter pattern; transforms API DTO to FE shape):
   ```typescript
   // types/video.ts
   export interface VideoFE {
     id: string;
     documentId: string; // camelCase (API uses snake_case)
     url: string | null;
     status: VideoStatus;
     createdAt: Date; // Date object (API returns ISO string)
     updatedAt: Date;
   }

   // adapters/videoAdapter.ts
   export function toVideoFE(apiVideo: Video): VideoFE {
     return {
       id: apiVideo.id,
       documentId: apiVideo.document_id,
       url: apiVideo.url,
       status: apiVideo.status,
       createdAt: new Date(apiVideo.created_at),
       updatedAt: new Date(apiVideo.updated_at),
     };
   }
   ```

4. **Components use FE models**; adapters run in API layer:
   ```typescript
   // modules/video/api/videoApi.ts
   export function useVideoQuery(videoId: string) {
     return useQuery({
       queryKey: ['video', videoId],
       queryFn: async () => {
         const apiVideo = await apiFetch<Video>(`/videos/${videoId}`);
         return toVideoFE(apiVideo); // transform to FE shape
       },
     });
   }

   // components/VideoPlayer.tsx
   const { data: video } = useVideoQuery(videoId); // video is VideoFE
   console.log(video.createdAt.toISOString()); // Date method available
   ```

### When to use adapters

- **Always** if API uses snake_case and FE uses camelCase (reference service B, reference service C)
- **Always** if API returns ISO strings and FE needs Date objects (all three repos)
- **Sometimes** if API returns nested objects and FE needs flat shapes (or vice versa)
- **Rarely** if API and FE shapes are identical (reference service A uses adapters sparingly)

### Adapter placement

- **reference service A**: `modules/<feature>/adapters/<domain>Adapter.ts` (or inline in `api/<feature>Api.ts`)
- **reference service B**: inline in `lib/<domain>.ts` or implicit (stores transform manually)
- **reference service C**: no adapters (GraphQL types match FE shapes closely; Apollo cache returns raw GraphQL response)

---

## Environment variables

### Build-time (Vite `import.meta.env.VITE_*`)

All three repos support build-time env vars for backend URLs:

```typescript
// vite.config.ts
export default defineConfig({
  define: {
    'import.meta.env.VITE_API_BASE_URL': JSON.stringify(process.env.VITE_API_BASE_URL || '/api'),
  },
});

// usage
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? '/api/v1';
```

**Pros**: Simple; works with Vite dev server
**Cons**: Baked into build; requires rebuild for different environments

### Runtime (reference service A `window._conf`)

reference service A injects runtime config via a Vite plugin or `/env-config` endpoint:

```typescript
// environment.ts
declare global {
  interface Window {
    _conf?: {
      ENV?: string;
      API_BASE_URL?: string;
      AUTH_API_BASE_URL?: string;
      TENANT_ID?: string;
      ORG_ID?: string;
      // ...
    };
  }
}

const browserConfig = typeof window !== 'undefined' && window._conf ? window._conf : {};

const environment = {
  ENV: readString(browserConfig.ENV, 'development'),
  API_BASE_URL: readString(browserConfig.API_BASE_URL, 'https://api.example.com'),
  // ...
};
```

**How it's injected**:
- **Vite plugin**: Custom plugin adds `<script>window._conf = { ... }</script>` to index.html at build time
- **Server endpoint**: `/env-config` returns `{ "API_BASE_URL": "...", ... }` and is fetched on app load (stored in window._conf)

**Pros**: Same build can run in dev/staging/prod with different configs (multi-tenant SaaS use case)
**Cons**: More complex; requires server-side config injection or Vite plugin

### Recommendation

- **Build-time** for simple apps (one deployment target, backend URL is fixed)
- **Runtime** for multi-tenant SaaS (same build, different tenant IDs per deployment)

---

## Summary: choosing an API layer strategy

| Criterion | Axios + react-query (A) | Fetch + race-guard (B) | Apollo + links (C) |
|-----------|-------------------------|------------------------|---------------------|
| **Backend** | REST with envelope | REST flat JSON | GraphQL |
| **Caching** | react-query | Manual (anti-pattern in reference service B) | Apollo cache |
| **Token refresh** | Interceptor (automatic) | Race-guard (manual) | N/A (GraphQL errors) |
| **Error handling** | Interceptor (401/403 global) | APIError class + 5xx Sentry | errorLink (UNAUTHENTICATED) |
| **File uploads** | FormData + axios | FormData + fetch | GraphQL multipart (createUploadLink) |
| **Multi-tenancy** | Dynamic headers (API_HEADERS proxy) | X-Tenant-ID header | x-org-id header (authLink) |
| **Bundle size** | ~13 KB (axios) + ~10 KB (react-query) | 0 KB (fetch is native) | ~50 KB (@apollo/client) |
| **Best for** | Envelope-based REST, multi-tenant | Flat JSON REST, JWT refresh | GraphQL, SSR, complex relationships |

**Rule of thumb:**
- **REST with envelope** → Use axios + react-query (pattern A)
- **REST flat JSON** → Use fetch + react-query (pattern B, but add react-query hooks; don't call `api.*` directly in stores)
- **GraphQL** → Use Apollo (pattern C); Apollo cache replaces react-query
