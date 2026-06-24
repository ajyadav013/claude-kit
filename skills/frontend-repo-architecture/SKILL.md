---
name: frontend-repo-architecture
description: Frontend repository structure patterns for React + Vite + TypeScript projects, covering three organizational models (module-scoped, feature-sliced, GraphQL-based), API layer strategies (axios+react-query, fetch+token-refresh, Apollo links), hand-written types convention, and state management (zustand + react-query/Apollo split). Derived from real-world production React services. Use when setting up a new React frontend, choosing a folder structure, designing the API layer, or architecting state management for a production SPA.
---

# Purpose

Encode three production-proven React frontend architectures and their API/state/types conventions: module-scoped monolith, feature-sliced, and GraphQL-SSR.

## When to use

- Setting up a new React + Vite + TypeScript frontend
- Choosing between module-scoped, feature-sliced, or GraphQL-based folder structure
- Designing the API layer (axios wrapper, fetch wrapper, or Apollo links)
- Architecting state management (server-state vs client-state split)
- Establishing type conventions (no codegen; hand-written API types)
- Configuring runtime vs build-time environment variables
- Implementing token refresh with race-guard logic
- Structuring test files (contract tests, vitest + testing-library)
- Reviewing an existing React frontend for architectural divergence

## Core conventions

1. **Shared stack baseline** — All three models use React 18/19 + Vite + TypeScript strict (`noUncheckedIndexedAccess: true`) + Tailwind + react-router-dom + zustand + Sentry + vitest + @testing-library/react. Function components only; PascalCase files. (reference service A, reference service B, reference service C)

2. **Three organizational models** — Choose one:
   - **Module-scoped** (`src/modules/<feature>/{api,components,hooks,stores,types,pages,route.tsx}` + `src/routes.tsx` aggregator) for large monoliths with parallel domains (reference service A)
   - **Feature-sliced** (`src/{features,pages,lib,stores,types,components/{ui,domain}}` + lazy-loaded pages) for medium-sized apps with cross-cutting features (reference service B)
   - **GraphQL-based** (`src/{graphql,pages,components,contexts,stores,utils}`) for schema-driven apps with SSR (reference service C)

3. **API layer: three patterns** — Match your backend contract:
   - **Axios + react-query hooks** (`lib/api.ts` exports `ApiService` + `apiFetch/apiPost` wrappers; `modules/<x>/api/<x>Api.ts` export `useQuery/useMutation` hooks; 401 → clear session + `/login`, 403 → `/unauthorized`) for envelope-based REST APIs (reference service A)
   - **Fetch wrapper + token refresh** (`lib/api.ts` exports `api.get/post/put/patch/delete`; single `refreshPromise` race-guard; `access_token/refresh_token` in localStorage; errors as `APIError` class with `.is(code)` helpers) for flat JSON REST APIs (reference service B)
   - **Apollo client + links** (`graphql/client.ts` with `authLink` (setContext adds Bearer token + x-org-id) + `errorLink` (UNAUTHENTICATED → `/login` if not on auth page) + `createUploadLink`; `apollo-require-preflight: true` header) for GraphQL (reference service C)

4. **Hand-written API types** — NO OpenAPI/GraphQL codegen anywhere. Define types in `types/<domain>.ts` or `modules/<feature>/types/<x>.types.ts`; API response shapes are manually transcribed. Wire/FE adapter pattern (separate API DTOs from FE models) is optional but common. (reference service A, reference service B, reference service C)

5. **State management: server vs client split** — Use React Query or Apollo cache for server state (GET-equivalent, cache/refetch/dedup); use zustand or React Context for client state (UI toggles, active filters, form drafts). Never mix: storing fetched data in zustand bypasses caching/dedup (anti-pattern observed in reference service B). (reference service A uses react-query+zustand; reference service C uses Apollo+context+zustand)

6. **Runtime config via `window._conf`** — Inject config from a Vite plugin or `/env-config` endpoint; read in `environment.ts` as `window._conf?.API_BASE_URL` with fallbacks. Build-time `import.meta.env.VITE_*` is allowed but less flexible. (reference service A uses window._conf; reference service B/reference service C use VITE_ vars)

7. **Token refresh race-guard** — If using fetch + JWT refresh, maintain a single `refreshPromise: Promise<boolean> | null`; if already in progress, await it instead of firing a second refresh. Clear it in `finally` so next refresh can proceed. (reference service B `lib/api.ts` lines 218–262)

8. **Path aliases** — Configure `tsconfig.app.json` `paths` (`@/*`, `@components/*`, `@features/*`, `@lib/*`, `@stores/*`, `@types/*`, `@pages/*`) and mirror in `vite.config.ts` `resolve.alias`. (reference service B tsconfig.app.json lines 42–50)

9. **Tailwind + Radix/Headless UI + `cn()` helper** — Install `tailwind-merge` + `clsx`; export `cn(...inputs) => twMerge(clsx(inputs))` in `lib/utils.ts`. Use Radix (reference service A) or Headless UI (reference service C) for unstyled primitives. (reference service A `lib/utils.ts`)

10. **Module route.tsx aggregator (module-scoped model only)** — Each module exports a fragment of `<Route>` elements in `route.tsx`; `src/routes.tsx` imports and composes them into `appRoutes`. (reference service A `routes.tsx` lines 1–80)

11. **Lazy-loaded pages (feature-sliced model)** — Use `React.lazy(() => import('./pages/XPage'))` + `<Suspense fallback={<LoadingScreen />}>` in the router for code-splitting. (reference service B pattern, not shown but conventional)

12. **Vitest + testing-library + msw** — Test files colocated in `__tests__/` (reference service B: `__tests__/{contracts,components,stores,hooks,pages}`) or adjacent `.test.tsx`. Use msw (Mock Service Worker) for contract tests (API mocking at network layer). Apollo MockedProvider for GraphQL tests. (reference service B `__tests__/contracts/*`, vitest.config.ts, `__tests__/setup.ts`)

13. **Sentry integration** — Install `@sentry/react`; report 5xx API errors (not 4xx). Capture network errors (no response) and unhandled exceptions. (reference service B `lib/api.ts` lines 383–385, 398–401)

## Skeleton / example

**Module-scoped model (reference service A pattern):**

```
src/
  modules/
    auth/
      api/authApi.ts          # exports useLoginMutation, useSessionQuery
      components/LoginForm.tsx
      hooks/useAuthGuard.ts
      stores/authStore.ts     # zustand slice
      types/auth.types.ts
      pages/LoginPage.tsx
      route.tsx               # exports authRoutes fragment
    purchasing/
      api/purchasingApi.ts
      components/...
      route.tsx
  lib/
    api.ts                    # ApiService + apiFetch/apiPost wrappers + DYNAMIC_HEADERS proxy
    utils.ts                  # cn() helper, getActiveTenantId, etc.
  routes.tsx                  # aggregates all module route fragments
  environment.ts              # window._conf reader
```

**Feature-sliced model (reference service B pattern):**

```
src/
  features/
    auth/                     # domain logic, service, hooks
    analytics/
    documents/
  pages/                      # lazy-loaded route containers
    LoginPage.tsx
    DashboardPage.tsx
  lib/
    api.ts                    # fetch wrapper + refreshAccessToken race-guard
    video.ts                  # service modules
  stores/
    video.ts                  # zustand with persist middleware
    analytics.ts
  types/
    video.ts
    error-codes.ts
  components/
    ui/                       # generic primitives
    domain/                   # feature-specific composed components
```

**GraphQL model (reference service C pattern):**

```
src/
  graphql/
    client.ts                 # apolloClient with authLink + errorLink
    queries/
      jobs.ts                 # gql`` tagged templates
      candidates.ts
  pages/
    JobsPage.tsx              # 80+ inline routes (anti-pattern; refactor to router)
  components/                 # flat (anti-pattern; 50+ files)
  contexts/
    AuthContext.tsx           # useAuth hook + ME_QUERY + LOGIN_MUTATION
    OrgContext.tsx
  stores/
    authStore.ts              # zustand
  utils/
  entry-server.tsx            # SSR
  ssr-server.ts
```

**API layer snippets:**

```typescript
// Axios + react-query (reference service A)
export async function apiFetch<T>(path: string, params?: Record<string, string | number | boolean | undefined>): Promise<T> {
  const res = await ApiService.get(`${API_BASE}${path}`, { params: cleanParams, headers: DYNAMIC_HEADERS });
  return res.data?.data ?? res.data;
}

// Fetch + token refresh (reference service B)
let refreshPromise: Promise<boolean> | null = null;
async function refreshAccessToken(): Promise<boolean> {
  if (refreshPromise) return refreshPromise;
  refreshPromise = (async () => { /* ... */ })();
  return refreshPromise;
}

// Apollo links (reference service C)
const authLink = setContext((_, { headers }) => {
  const token = localStorage.getItem('app_token');
  const orgId = localStorage.getItem('app_org_id');
  return { headers: { ...headers, authorization: token ? `Bearer ${token}` : '', ...(orgId && { 'x-org-id': orgId }) } };
});
const errorLink = onError(({ graphQLErrors }) => {
  graphQLErrors?.forEach(({ extensions }) => {
    if (extensions?.code === 'UNAUTHENTICATED' && !isAuthPage) {
      localStorage.removeItem('app_token');
      window.location.href = '/login';
    }
  });
});
```

## Anti-patterns to avoid

1. **Storing server data in zustand** — Bypasses cache/refetch/dedup; use react-query or Apollo cache instead. (observed in reference service B: stores calling `lib/api` directly)
2. **80+ inline routes in App.tsx** — Refactor to feature-based route modules or a dedicated router file. (reference service C App.tsx)
3. **Flat 50+ file components/ directory** — Split into `ui/` (primitives) and feature-scoped folders. (reference service C)
4. **Mixed default and named exports** — Stick to named exports for consistency; default exports hinder refactoring. (reference service C inconsistency)
5. **Skipping the token refresh race-guard** — Without a shared `refreshPromise`, concurrent requests will fire multiple refresh calls. (implement reference service B pattern)
6. **Build-time env vars for tenant/org IDs** — Use runtime config (`window._conf`) for multi-tenant values that change per deployment. (reference service A pattern is correct)
7. **Skipping the 5xx-only Sentry filter** — Report only server errors (≥500) and network errors; 4xx are user errors, not exceptions. (reference service B `lib/api.ts` line 383)

## References

- [repo-evidence.md](references/repo-evidence.md) — Source file paths and representative snippets from reference service A, reference service B, reference service C
- [structure-and-state.md](references/structure-and-state.md) — Detailed folder trees and state-management architecture per model
- [api-layer-and-types.md](references/api-layer-and-types.md) — API layer patterns, token refresh, hand-written types convention
- [divergences.md](references/divergences.md) — Comparison table and guidance on choosing between the three models
- [testing-patterns.md](references/testing-patterns.md) — vitest + testing-library + msw patterns, contract tests, store/hook/component testing, Apollo MockedProvider
