# Example Patterns

This file shows example code structures and representative snippets derived from production React services.

---

## Reference Service A (Module-scoped model)

**Key patterns**: Module-scoped folder structure (`modules/<feature>/{api,components,hooks,stores,types,pages,route.tsx}`), route aggregator pattern, axios + react-query API layer, `DYNAMIC_HEADERS` proxy, runtime `window._conf` config, Radix + Tailwind + `cn()` helper.

### Structure

- `src/modules/auth/api/authApi.ts`
- `src/modules/auth/stores/authStore.ts` (inferred, not present in scan; pattern exists in other modules)
- `src/modules/auth/pages/LoginPage.tsx` (inferred)
- `src/modules/analytics/stores/analytics.store.ts`
- `src/modules/analytics/stores/workflow.store.ts`
- `src/modules/analytics/types/analytics.types.ts`
- `src/routes.tsx`
- `src/environment.ts`
- `src/lib/api.ts`
- `src/lib/utils.ts` (inferred; contains `cn()` helper per evidence brief)

### Snippets

**`src/routes.tsx` (lines 1–24, 67–80):**

```typescript
import { Route } from 'react-router-dom';
import { PlaceholderPage } from '@/pages/PlaceholderPage';
import { dashboardRoutes } from '@/modules/dashboard/route';
import { exceptionRoutes } from '@/modules/exceptions/route';
import { reviewRoutes } from '@/modules/review/route';
import { agentRoutes } from '@/modules/agents/route';
// ... 18 more module route imports

export const appRoutes = (
  <>
    {dashboardRoutes}
    {reviewRoutes}
    {exceptionRoutes}
    {agentRoutes}
    // ... 15 more route fragments
    {placeholderRoutes}
  </>
);
```

**`src/lib/api.ts` (lines 19–20, 44–93, 127–153, 182–243):**

```typescript
// Service base paths
export const API_BASE = "/service/public/api-service/v1.0";
export const API_APP_BASE = "/service/application/api-service/v1.0";

export const ApiService = {
  get: (url: string, options: ApiOptions = {}): Promise<AxiosResponse> => {
    return axios.get(resolveUrl(url), { params: options.params, headers: options.headers });
  },
  post: (url: string, options: ApiOptions = {}): Promise<AxiosResponse> => {
    return axios.post(resolveUrl(url), options.data, { headers: options.headers, params: options.params });
  },
  // ... put, patch, del, axios methods
};

// Default headers for api-service endpoints — tenant ID derived from active org
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

// Helper for api-service endpoints — prepends API_BASE and unwraps envelope
export async function apiFetch<T>(path: string, params?: Record<string, string | number | boolean | undefined>): Promise<T> {
  const cleanParams: Record<string, unknown> = {};
  if (params) {
    for (const [k, v] of Object.entries(params)) {
      if (v !== undefined && v !== null && v !== "") cleanParams[k] = v;
    }
  }
  const res = await ApiService.get(`${API_BASE}${path}`, { params: cleanParams, headers: API_HEADERS });
  return res.data?.data ?? res.data;
}

export async function apiPost<T>(path: string, data?: unknown): Promise<T> {
  const res = await ApiService.post(`${API_BASE}${path}`, { data, headers: API_HEADERS });
  return res.data?.data ?? res.data;
}
```

**`src/lib/api.ts` (lines 109–125, 401 interceptor):**

```typescript
axios.interceptors.response.use(
  (response: AxiosResponse) => response,
  (error: AxiosError) => {
    const status = error.response?.status;
    if (status === HttpStatusCodes.FORBIDDEN) {
      redirectToUnauthorizedPage();
      return Promise.reject(error?.response?.data ?? error);
    }
    if (status === HttpStatusCodes.UNAUTHORIZED) {
      clearAllSessionData();
      sessionStorage.setItem("app-logged-out", "1");
      window.location.pathname = "/login";
    }
    return Promise.reject(error?.response?.data ?? error);
  },
);
```

**`src/environment.ts` (lines 1–60, excerpt):**

```typescript
interface WindowConfig {
  ENV?: string;
  API_BASE_URL?: string;
  AUTH_API_BASE_URL?: string;
  SESSION_COOKIE_DOMAIN?: string;
  DEV_COOKIES?: string;
  TENANT_ID?: string;
  ORG_ID?: string;
  // ...
}

declare global {
  interface Window {
    _conf?: WindowConfig;
  }
}

const browserConfig = typeof window !== 'undefined' && window._conf ? window._conf : {};

function readString(value: unknown, fallback: string): string {
  return typeof value === 'string' && value.length > 0 ? value : fallback;
}

const environment: EnvironmentConfig = {
  ENV: readString(browserConfig.ENV, 'development'),
  API_BASE_URL: readString(browserConfig.API_BASE_URL, 'https://api.example.com'),
  AUTH_API_BASE_URL: readString(browserConfig.AUTH_API_BASE_URL, /* ... */),
  // ...
};
```

**`src/modules/analytics/stores/analytics.store.ts` (lines 1–60, zustand example):**

```typescript
import { create } from 'zustand';
import type { DataRecommendation, HandoffState } from '../types/analytics.types';

interface AnalyticsState {
  recommendations: DataRecommendation[];
  planningDecisions: Record<string, PlanningDecision>;
  layoutHandoffs: LayoutHandoff[];
  updateRecommendationStatus: (id: string, newStatus: RecStatus) => void;
  setPlanningDecision: (tenantId: string, decision: PlanningDecision) => void;
  // ...
}

export const useAnalyticsStore = create<AnalyticsState>((set) => ({
  recommendations: [...analyticsRecommendations],
  planningDecisions: {},
  layoutHandoffs: [],
  updateRecommendationStatus: (id, newStatus) =>
    set((state) => ({
      recommendations: state.recommendations.map((r) => r.id === id ? { ...r, status: newStatus } : r),
    })),
  // ...
}));
```

---

## Reference Service B (Feature-sliced model)

**Key patterns**: Feature-sliced folder structure (`src/{features,pages,lib,stores,types,components/{ui,domain}}`), fetch wrapper + token refresh race-guard, `APIError` class with `.is(code)` helpers, zustand with persist middleware, path aliases, msw contract tests.

### Structure

- `src/features/auth/`
- `src/features/analytics/`
- `src/features/documents/`
- `src/pages/LoginPage.tsx` (inferred; lazy-loaded)
- `src/lib/api.ts`
- `src/lib/video.ts`
- `src/stores/video.ts`
- `src/stores/reports.ts`
- `src/types/video.ts` (inferred)
- `src/types/error-codes.ts` (inferred)
- `src/components/ui/` (inferred)
- `src/components/domain/` (inferred)
- `src/__tests__/contracts` (msw-based contract tests)
- `tsconfig.app.json`

### Snippets

**`src/lib/api.ts` (lines 13–89, token storage + refresh race-guard):**

```typescript
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? '/api/v1';
const ACCESS_TOKEN_KEY = 'app_access_token';
const REFRESH_TOKEN_KEY = 'app_refresh_token';
const TOKEN_EXPIRY_KEY = 'app_token_expiry';
const REFRESH_BUFFER_MS = 5 * 60 * 1000;

let refreshPromise: Promise<boolean> | null = null;

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

export function clearTokens(): void {
  localStorage.removeItem(ACCESS_TOKEN_KEY);
  localStorage.removeItem(REFRESH_TOKEN_KEY);
  localStorage.removeItem(TOKEN_EXPIRY_KEY);
}
```

**`src/lib/api.ts` (lines 218–262, race-guard implementation):**

```typescript
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

**`src/lib/api.ts` (lines 94–170, APIError class):**

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
}
```

**`src/lib/api.ts` (lines 383–385, 398–401, Sentry 5xx-only filter):**

```typescript
// Report 5xx server errors to Sentry (not 4xx client errors)
if (response.status >= 500) {
  Sentry.captureException(apiError);
}

// Report network errors to Sentry (errors without a response, e.g. connection refused)
if (!(error instanceof APIError)) {
  Sentry.captureException(error);
}
```

**`src/stores/video.ts` (lines 1–60, zustand example):**

```typescript
import { create } from 'zustand';
import { videoService } from '@/lib/video';
import type { Video, VideoStatus, GenerateVideoRequest, /* ... */ } from '@/types';

interface VideoState {
  currentVideo: Video | null;
  isLoading: boolean;
  isGenerating: boolean;
  isPolling: boolean;
  error: string | null;
  pollingInterval: ReturnType<typeof setInterval> | null;
  loadVideo: (videoId: string) => Promise<void>;
  generateVideo: (documentId: string, options?: GenerateVideoRequest) => Promise<void>;
  // ...
}

const initialState = {
  currentVideo: null,
  isLoading: false,
  isGenerating: false,
  isPolling: false,
  error: null,
  pollingInterval: null,
};

export const useVideoStore = create<VideoState>()((set, get) => ({
  ...initialState,
  loadVideo: async (videoId: string): Promise<void> => { /* ... */ },
  generateVideo: async (documentId: string, options?: GenerateVideoRequest): Promise<void> => { /* ... */ },
  // ...
}));
```

**`tsconfig.app.json` (lines 19–28, 40–51, strict + path aliases):**

```json
{
  "compilerOptions": {
    "strict": true,
    "noImplicitAny": true,
    "strictNullChecks": true,
    "strictFunctionTypes": true,
    "strictBindCallApply": true,
    "strictPropertyInitialization": true,
    "noImplicitThis": true,
    "alwaysStrict": true,
    "noUncheckedIndexedAccess": true,

    "baseUrl": ".",
    "paths": {
      "@/*": ["./src/*"],
      "@components/*": ["./src/components/*"],
      "@features/*": ["./src/features/*"],
      "@lib/*": ["./src/lib/*"],
      "@hooks/*": ["./src/hooks/*"],
      "@stores/*": ["./src/stores/*"],
      "@types/*": ["./src/types/*"],
      "@pages/*": ["./src/pages/*"]
    }
  }
}
```

---

## Reference Service C (GraphQL-SSR model)

**Key patterns**: Apollo client setup (authLink + errorLink + createUploadLink), `authLink` setContext pattern, `errorLink` UNAUTHENTICATED handler, Headless UI + Tailwind, zustand + React Contexts, SSR entry points, Vite dev proxy.

### Structure

- `src/graphql/client.ts`
- `src/graphql/queries/` (inferred; gql files)
- `src/App.tsx` (80+ inline routes; anti-pattern)
- `src/components/` (flat 50+ files; anti-pattern)
- `src/contexts/AuthContext.tsx`
- `src/contexts/OrgContext.tsx`
- `src/stores/authStore.ts` (inferred; exists per evidence brief)
- `src/pages/` (46+ page files)
- `src/entry-client.tsx`
- `src/entry-server.tsx`
- `ssr-server.ts` (inferred; SSR server)

### Snippets

**`src/graphql/client.ts` (lines 1–105, Apollo setup):**

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

// Use createUploadLink for file upload support (GraphQL multipart request spec)
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
      ...(orgId && { 'x-org-id': orgId }),
    },
  };
});

const errorLink = onError(({ graphQLErrors, networkError }) => {
  if (graphQLErrors) {
    graphQLErrors.forEach(({ message, locations, path, extensions }) => {
      console.error(`[GraphQL error]: Message: ${message}, Location: ${locations}, Path: ${path}`);
      // Handle authentication errors - but not on login/register pages
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

**`src/contexts/AuthContext.tsx` (lines 1–80, React Context + gql queries):**

```typescript
import { createContext, useContext, useState, useEffect, ReactNode } from "react";
import { useMutation, useQuery, gql } from "@apollo/client";
import { apolloClient } from "../graphql/client";

const ME_QUERY = gql`
  query Me {
    me {
      id
      email
      name
      role
      avatar
      emailVerified
      phone
      phoneVerified
      hasPassword
    }
  }
`;

const LOGIN_MUTATION = gql`
  mutation Login($input: LoginInput!) {
    login(input: $input) {
      token
      user {
        id
        email
        name
        role
        avatar
        emailVerified
        phone
        phoneVerified
        hasPassword
      }
    }
  }
`;

// ... AuthContext provider, useAuth hook
```

**`src/App.tsx` (lines 1–100, anti-pattern: 80+ inline routes):**

```typescript
import { Routes, Route, Navigate, useLocation } from "react-router-dom";
import { useEffect } from "react";
import { useAuth } from "./contexts/AuthContext";
import { useOrg } from "./contexts/OrgContext";
// ... 70+ page imports

// ... 80+ <Route> elements inline (not shown; anti-pattern per evidence brief)
```

---

## Common patterns (all three repos)

- **React 18/19 + Vite + TypeScript strict** — `noUncheckedIndexedAccess: true` in tsconfig
- **Tailwind CSS** — `tailwind.config.js` + utility-first styling
- **react-router-dom** — v6+ with `<Routes>` + `<Route>` JSX API
- **zustand** — `create<State>((set, get) => ({ /* ... */ }))` pattern
- **vitest + @testing-library/react** — test files in `__tests__/` or adjacent `.test.tsx`
- **Sentry integration** — `@sentry/react` with `captureException` for 5xx + network errors
- **Function components only** — no class components
- **PascalCase file names** — `LoginPage.tsx`, `AuthContext.tsx`, `authApi.ts` (camelCase for non-component modules)
- **Hand-written API types** — NO OpenAPI/GraphQL codegen; types manually defined in `types/` or module-scoped `types/`
- **Server-state vs client-state split** — React Query/Apollo for server data; zustand/context for UI state
