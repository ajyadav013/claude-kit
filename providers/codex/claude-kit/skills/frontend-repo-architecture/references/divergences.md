# Divergences and Decision Guide

This file compares the three models and provides guidance on when to use each, including a table of divergences and anti-patterns observed.

---

## Three-way comparison

| Aspect | Module-scoped (A) | Feature-sliced (B) | GraphQL-SSR (C) |
|--------|-------------------|--------------------|--------------------|
| **Folder structure** | `modules/<feature>/{api,components,hooks,stores,types,pages,route.tsx}` | `{features,pages,lib,stores,types,components/{ui,domain}}` | `{graphql,pages,components,contexts,stores,utils}` |
| **Route organization** | Aggregated fragments (`route.tsx` per module, `routes.tsx` aggregates) | Lazy-loaded pages (`React.lazy` + `Suspense`) | Inline in `App.tsx` (anti-pattern: 80+ routes) |
| **API layer** | Axios + react-query hooks | Fetch wrapper + token refresh race-guard | Apollo links (authLink + errorLink) |
| **Server state** | react-query cache | Manual (anti-pattern: bypasses cache) | Apollo cache |
| **Client state** | zustand (module-scoped stores) | zustand with persist middleware | React Contexts + zustand |
| **Multi-tenancy** | `DYNAMIC_HEADERS` proxy (dynamic X-Tenant-ID/X-Org-ID) | `X-Tenant-ID` header | `x-org-id` header (authLink) |
| **Environment config** | Runtime (`window._conf` injected by Vite plugin or `/env-config`) | Build-time (`import.meta.env.VITE_*`) | Build-time (`import.meta.env.VITE_*`) |
| **Error handling** | Axios interceptor (401 → logout, 403 → /unauthorized) | `APIError` class + Sentry 5xx filter | `errorLink` (UNAUTHENTICATED → /login) |
| **Token refresh** | Automatic (axios interceptor) | Race-guard (single `refreshPromise`) | N/A (GraphQL errors) |
| **File uploads** | FormData + axios | FormData + fetch | GraphQL multipart (`createUploadLink`) |
| **Path aliases** | `@/*` (minimal) | Rich (`@components/*`, `@features/*`, `@lib/*`, `@stores/*`, `@types/*`, `@pages/*`) | `@/*` (minimal) |
| **Testing** | vitest + testing-library (inferred) | vitest + testing-library + msw contract tests | vitest + testing-library (inferred) |
| **SSR support** | No | No | Yes (`entry-server.tsx` / `ssr-server.ts`) |
| **Mobile support** | Capacitor (iOS/Android) | N/A | Electron (desktop app) |
| **Bundle size** | Medium (~23 KB: axios + react-query) | Small (0 KB: fetch is native) | Large (~50 KB: @apollo/client) |
| **Boilerplate** | High (each module needs 7 folders + `route.tsx`) | Medium (flat features/pages/lib/stores/types) | Low (GraphQL schema = API contract) |
| **Best for** | Large monoliths (20+ parallel domains) | Medium apps (10–20 cross-cutting features) | Schema-first apps (ATS, CMS, CRM) with SSR |
| **Observed in** | reference service A (17+ modules) | reference service B (11 features) | reference service C (GraphQL + SSR) |

---

## Decision matrix: which model to use

### Use Module-scoped (A) when:

- **App has 20+ domains** that evolve independently (e.g., inventory, purchasing, catalog, workflows, analytics, planning, agents, calendar, tasks, exceptions, review, ...)
- **Domains are parallel** — minimal shared logic between them (each is a mini-app)
- **Team is large** — multiple squads own different modules
- **Future micro-frontend extraction** is likely (each module can become a standalone app)
- **Multi-tenant SaaS** requires runtime config (tenant IDs change per deployment; `window._conf` pattern is essential)

**Pros:**
- Clear domain boundaries (easy to reason about ownership)
- Scales to 20+ features without folder explosion
- Route aggregation keeps routes colocated with modules
- Straightforward to parallelize development (squads work on different modules)

**Cons:**
- More boilerplate (each module needs 7+ folders)
- Harder to share logic across modules (must extract to top-level `lib/` or a shared module)
- Overkill for small apps (< 10 features)

### Use Feature-sliced (B) when:

- **App has 10–20 features** with cross-cutting concerns (e.g., analytics, documents, templates, reports, scoring)
- **Features share UI components** (generic primitives in `components/ui`, domain-specific in `components/domain`)
- **Code splitting is important** (lazy-loaded pages reduce initial bundle size)
- **Team is medium-sized** — 3–5 engineers, not enough to justify module boundaries
- **Backend is REST with flat JSON** (no envelope wrapping)

**Pros:**
- Optimized for code reuse (shared components in `components/ui`, shared hooks in `hooks/`)
- Lazy-loading reduces initial bundle size
- Rich path aliases simplify imports (`@components/*`, `@features/*`, `@lib/*`)
- Conventional folder structure (easy for new devs to navigate)

**Cons:**
- As features grow, `lib/` and `types/` become grab-bags (15+ service modules, 20+ type files in reference service B)
- No clear domain boundaries; features can cross-pollinate unintentionally
- Anti-pattern risk: bypassing react-query cache by calling `api.*` directly in stores (observed in reference service B)

### Use GraphQL-SSR (C) when:

- **Backend is GraphQL** (schema-first API design)
- **SSR is required** (SEO, initial load performance)
- **Complex multi-entity relationships** (e.g., ATS: jobs ↔ candidates ↔ interviews ↔ offers ↔ vendors)
- **File uploads** are common (GraphQL multipart request spec via `createUploadLink`)
- **Apollo cache** can replace react-query (no need to maintain two caching layers)

**Pros:**
- GraphQL eliminates REST boilerplate (no manual type transcription for queries; schema-first)
- Apollo cache handles server-state management automatically (no need for react-query)
- SSR improves SEO and initial load performance
- File upload support via `createUploadLink` (multipart GraphQL spec)
- Multi-tenancy via `x-org-id` header (clean separation)

**Cons:**
- GraphQL adds backend complexity (schema design, resolver logic, N+1 query risk)
- SSR adds build complexity (requires server setup, hydration logic, dual entry points)
- Bundle size is large (~50 KB for @apollo/client)
- Anti-patterns observed in reference service C: 80+ inline routes in `App.tsx`, flat 50+ file `components/` directory, mixed default/named exports

---

## Anti-patterns observed (by repo)

### reference service A (Module-scoped model)

**Good patterns:**
- ✅ Module-scoped folder structure with clear domain boundaries
- ✅ Route aggregation (`route.tsx` per module, `routes.tsx` aggregates)
- ✅ react-query hooks exported from `modules/<feature>/api/<x>Api.ts`
- ✅ `DYNAMIC_HEADERS` proxy for dynamic multi-tenant headers
- ✅ Runtime config via `window._conf` (solves multi-tenant SaaS)
- ✅ Axios interceptor for global 401/403 handling

**Anti-patterns:**
- ⚠️ No anti-patterns observed (cleanest of the three repos)

### reference service B (Feature-sliced model)

**Good patterns:**
- ✅ Feature-sliced folder structure with `components/ui` + `components/domain` split
- ✅ Token refresh race-guard (single `refreshPromise`)
- ✅ `APIError` class with `.is(code)` helpers (semantic error handling)
- ✅ Sentry 5xx-only filter (excludes 4xx client errors)
- ✅ Rich path aliases (`@components/*`, `@features/*`, `@lib/*`, `@stores/*`, `@types/*`, `@pages/*`)
- ✅ msw-based contract tests under `__tests__/contracts`

**Anti-patterns:**
- ❌ **Bypassing react-query cache**: Stores call `api.*` directly (e.g., `stores/video.ts` calls `videoService.generate()` which calls `api.post()` directly). This bypasses caching/deduplication. **Fix**: Wrap `api.*` calls in `useMutation`/`useQuery` hooks; call the hooks from components, not stores.
- ⚠️ **Storing server data in zustand**: Some stores fetch server data and store it in zustand state (e.g., `stores/video.ts` has `currentVideo: Video | null`). This duplicates Apollo/react-query cache. **Fix**: Use react-query for server state; zustand only for client state (UI toggles, filters, form drafts).
- ⚠️ **Grab-bag `lib/` and `types/` directories**: 15+ service modules in `lib/`, 20+ type files in `types/`. As features grow, these become hard to navigate. **Fix**: Consider splitting `lib/<domain>.ts` into `features/<domain>/<domain>Service.ts` or grouping related services into subdirectories (`lib/video/`, `lib/analytics/`).

### reference service C (GraphQL-SSR model)

**Good patterns:**
- ✅ Apollo client setup with authLink + errorLink + createUploadLink
- ✅ `authLink` setContext pattern (injects Bearer + x-org-id headers)
- ✅ `errorLink` UNAUTHENTICATED handler (redirects to `/login` unless on auth page)
- ✅ SSR entry points (`entry-server.tsx` / `entry-client.tsx`)
- ✅ Vite dev proxy forwards `/graphql` to backend

**Anti-patterns:**
- ❌ **80+ inline routes in `App.tsx`**: All routes are defined inline in one 100+ line `<Routes>` block. This is unscalable and hard to review. **Fix**: Extract routes into feature-based modules (e.g., `jobs/routes.tsx`, `candidates/routes.tsx`) or a route config array (`const routes = [{ path: '/jobs', element: <JobsPage /> }, ...]`) with a `<Routes>{routes.map(...)}</Routes>` renderer.
- ❌ **Flat 50+ file `components/` directory**: All components live in one directory with no subdirectories. **Fix**: Split into `components/ui/` (generic primitives: Button, Input, Card) and `components/domain/` (feature-specific: JobCard, CandidateCard, InterviewTimeline) or move feature-specific components into `pages/<feature>/components/`.
- ❌ **Mixed default and named exports**: Some files use `export default X`, others use `export const X`. **Fix**: Stick to named exports for consistency (default exports hinder refactoring; e.g., renaming a default-exported component requires updating every import).
- ⚠️ **No route-level code-splitting**: All pages are imported eagerly (`import JobsPage from './pages/JobsPage'`), not lazy-loaded (`const JobsPage = lazy(() => import('./pages/JobsPage'))`). This inflates the initial bundle. **Fix**: Use `React.lazy` + `Suspense` for route-level splitting (reference service B pattern).

---

## Hybrid model recommendations

None of the three models are perfect. Here are hybrid recommendations:

### Module-scoped + feature-sliced hybrid (for large apps with shared UI)

**Structure:**

```
src/
  modules/
    inventory/
      api/inventoryApi.ts
      components/
        InventoryTable.tsx   # domain-specific
      hooks/
        useInventoryFilters.ts
      stores/inventoryStore.ts
      types/inventory.types.ts
      pages/InventoryPage.tsx
      route.tsx
    purchasing/
      api/purchasingApi.ts
      # ...
  components/
    ui/                      # shared primitives (Button, Input, Card)
      Button.tsx
      Input.tsx
    domain/                  # cross-module domain components
      DataTable.tsx
      FilterPanel.tsx
  lib/
    api.ts
    utils.ts
  routes.tsx
```

**Why**: Preserves module boundaries (clear ownership) while extracting shared primitives to `components/ui` (DRY). Domain-specific components stay in modules; cross-module components go to `components/domain`.

### Feature-sliced + route modules hybrid (for medium apps with better route organization)

**Structure:**

```
src/
  features/
    auth/
      routes.tsx            # exports authRoutes fragment
      AuthService.ts
      useAuth.ts
    analytics/
      routes.tsx
      AnalyticsService.ts
  pages/
    LoginPage.tsx
    DashboardPage.tsx
  routes.tsx                # aggregates all feature routes
```

**Why**: Preserves feature-sliced simplicity while improving route organization (no 80+ inline routes). Each feature owns its routes; top-level `routes.tsx` aggregates.

### GraphQL-SSR + route config array hybrid (for SSR apps with clean routing)

**Structure:**

```
src/
  routes/
    index.tsx              # route config array
    jobs.tsx               # job routes
    candidates.tsx         # candidate routes
  graphql/
    client.ts
    queries/
  pages/
  App.tsx                  # <Routes>{routes.map(r => <Route key={r.path} path={r.path} element={r.element} />)}</Routes>
```

**routes/index.tsx:**

```typescript
import { lazy } from 'react';

const JobsPage = lazy(() => import('@/pages/JobsPage'));
const CandidatesPage = lazy(() => import('@/pages/CandidatesPage'));

export const routes = [
  { path: '/jobs', element: <JobsPage /> },
  { path: '/jobs/:id', element: <JobDetailPage /> },
  { path: '/candidates', element: <CandidatesPage /> },
  // ...
];
```

**Why**: Keeps SSR benefits while eliminating the 80+ inline routes anti-pattern. Route config is a single source of truth and easier to review/test.

---

## Migration paths

### Migrating from Feature-sliced (B) to Module-scoped (A)

**When**: App grows from 10 to 20+ features; domain boundaries become important; team scales to 10+ engineers.

**Steps**:
1. Create `modules/` directory
2. For each feature in `features/`:
   - Create `modules/<feature>/`
   - Move `features/<feature>/` → `modules/<feature>/features/` (or inline into `modules/<feature>/`)
   - Create `modules/<feature>/api/` (move service modules from `lib/<feature>.ts`)
   - Create `modules/<feature>/types/` (move types from `types/<feature>.ts`)
   - Create `modules/<feature>/route.tsx` (extract routes from `App.tsx`)
3. Update `routes.tsx` to aggregate all module `route.tsx` fragments
4. Update path aliases (`@modules/*`)
5. Gradually refactor stores to module-scoped (one module at a time)

**Effort**: Medium (1–2 weeks for 10 features; mostly mechanical refactoring)

### Migrating from REST (A/B) to GraphQL (C)

**When**: Backend adopts GraphQL; REST API becomes legacy; SSR is required.

**Steps**:
1. Install `@apollo/client`, `apollo-upload-client`, `graphql`
2. Create `graphql/client.ts` (authLink + errorLink + httpLink)
3. Wrap `App.tsx` in `<ApolloProvider client={apolloClient}>`
4. For each REST endpoint:
   - Write the GraphQL query/mutation in `graphql/queries/<domain>.ts`
   - Replace `useQuery` (react-query) with `useQuery` (Apollo)
   - Replace `useMutation` (react-query) with `useMutation` (Apollo)
5. Remove react-query (`@tanstack/react-query`) once all endpoints are GraphQL
6. Add SSR if needed (`entry-server.tsx` / `entry-client.tsx`)

**Effort**: High (2–4 weeks for 20+ endpoints; requires backend GraphQL schema)

### Migrating from GraphQL (C) to REST (A/B)

**When**: Backend deprecates GraphQL; REST API is simpler; SSR is not required.

**Steps**:
1. Install `@tanstack/react-query` (or use fetch wrapper pattern from reference service B)
2. Create `lib/api.ts` (axios wrapper or fetch wrapper)
3. For each GraphQL query/mutation:
   - Write the REST endpoint type in `types/<domain>.ts`
   - Replace `useQuery` (Apollo) with `useQuery` (react-query) or custom hook
   - Replace `useMutation` (Apollo) with `useMutation` (react-query) or custom hook
4. Remove `@apollo/client` once all queries are REST
5. Remove SSR entry points if not needed

**Effort**: High (2–4 weeks for 20+ queries; requires REST API endpoints)

---

## Summary: when to use which model

| App size | Backend | SSR? | Team size | Recommendation |
|----------|---------|------|-----------|----------------|
| Small (< 10 features) | REST | No | 1–3 | Feature-sliced (B) |
| Medium (10–20 features) | REST | No | 3–5 | Feature-sliced (B) or Module-scoped (A) if domains are parallel |
| Large (20+ features) | REST | No | 5+ | Module-scoped (A) |
| Medium–Large | GraphQL | Yes | Any | GraphQL-SSR (C) |
| Medium–Large | GraphQL | No | Any | GraphQL (C without SSR) or Feature-sliced (B) with Apollo |

**Golden rule**: Start with Feature-sliced (B) for most projects. Migrate to Module-scoped (A) when domains grow and team scales. Migrate to GraphQL (C) only if backend is GraphQL and SSR is required.
