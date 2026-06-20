# Structure and State Management

This file details the three folder structure models and their state-management approaches.

---

## Model A: Module-scoped (Reference Service A)

**Use when**: Large multi-domain applications with parallel verticals (e.g., inventory + sourcing + store-view + planogram + AOP) that evolve independently. Each module is a mini-app with its own API, components, hooks, stores, types, pages, and routes.

### Folder structure

```
src/
  modules/
    auth/
      api/
        authApi.ts              # exports useLoginMutation, useSessionQuery (react-query hooks)
      components/
        LoginForm.tsx
        BiometricToggle.tsx
      hooks/
        useAuthGuard.ts
        useBiometric.ts
      stores/
        authStore.ts            # zustand slice for client state (e.g., biometric enrollment)
      types/
        auth.types.ts           # SessionUser, Workspace, Organization
      pages/
        LoginPage.tsx
        UnauthorizedPage.tsx
      route.tsx                 # exports authRoutes: <Route path="/login" element={<LoginPage />} /> ...
    inventory/
      api/inventoryApi.ts
      components/...
      hooks/...
      stores/inventoryStore.ts
      types/inventory.types.ts
      pages/InventoryPage.tsx
      route.tsx                 # exports inventoryRoutes
    store-view/
      api/storeViewApi.ts
      components/...
      stores/
        intelligence.store.ts   # zustand for client state (UI filters, handoff state)
        unified-planning.store.ts
      types/
        storeIntelligence.types.ts
      pages/StoreViewPage.tsx
      route.tsx
    # ... 17 more modules (otb, range, planogram, aop, agents, calendar, sourcing, ...)
  lib/
    api.ts                      # ApiService wrapper + apiFetch/apiPost helpers + API_HEADERS proxy
    utils.ts                    # cn() helper, getActiveTenantId, getActiveOrgUuid
  routes.tsx                    # aggregates all module route.tsx fragments into appRoutes
  environment.ts                # window._conf runtime config reader
  main.tsx                      # ReactDOM.createRoot entry
  App.tsx                       # top-level shell with <Routes>{appRoutes}</Routes>
  index.css                     # Tailwind directives + CSS variables
  components/                   # shared primitives (Button, Input, Radix components)
  hooks/                        # shared hooks (useDebounce, useLocalStorage)
  pages/                        # non-module pages (PlaceholderPage, UnauthorizedPage)
  permissions/                  # permission logic (inferred)
  data/                         # mock data / constants
  test/                         # test utilities
```

### State management

- **Server state** → `@tanstack/react-query` hooks exported from `modules/<feature>/api/<x>Api.ts`
  - Example: `useSessionQuery()` in `auth/api/authApi.ts` fetches session via `apiFetch('/session')`, caches the result, handles refetching
  - Example: `useInventoryQuery()` in `inventory/api/inventoryApi.ts` fetches inventory data via `apiFetch('/inventory', params)`
- **Client state** → zustand stores in `modules/<feature>/stores/<x>.store.ts`
  - Example: `authStore.ts` might track biometric enrollment state (UI-only, not server-persisted)
  - Example: `intelligence.store.ts` tracks AOP decisions, space planning handoffs, recommendation status (UI workflow state)
- **Global API config** → `API_HEADERS` proxy in `lib/api.ts` dynamically reads `X-Tenant-ID` + `X-Org-ID` from session store at access time (solves multi-tenant header injection)

### Route aggregation pattern

Each module exports a route fragment in `route.tsx`:

```typescript
// modules/inventory/route.tsx
import { Route } from 'react-router-dom';
import InventoryPage from './pages/InventoryPage';

export const inventoryRoutes = (
  <>
    <Route path="/inventory" element={<InventoryPage />} />
    <Route path="/inventory/:id" element={<InventoryDetailPage />} />
  </>
);
```

Top-level `src/routes.tsx` aggregates:

```typescript
import { dashboardRoutes } from '@/modules/dashboard/route';
import { inventoryRoutes } from '@/modules/inventory/route';
import { otbRoutes } from '@/modules/otb/route';
// ... 17 more imports

export const appRoutes = (
  <>
    {dashboardRoutes}
    {inventoryRoutes}
    {otbRoutes}
    {/* ... 17 more fragments */}
    {placeholderRoutes}
  </>
);
```

`App.tsx` renders `<Routes>{appRoutes}</Routes>`.

### Pros/Cons

**Pros:**
- Clear domain boundaries; modules can be developed/tested in parallel
- Easy to scale to 20+ features without folder explosion
- Route aggregation keeps module routes colocated with the module
- Straightforward to extract a module into a micro-frontend later

**Cons:**
- More boilerplate (each module needs an `api/`, `stores/`, `types/`, `route.tsx`)
- Harder to share logic across modules (common components must live in top-level `components/` or a shared module)
- Overkill for small apps (use feature-sliced instead)

---

## Model B: Feature-sliced (Reference Service B)

**Use when**: Medium-sized apps (10–20 features) with cross-cutting concerns (e.g., analytics, briefs, templates, trends, grading) where features share UI components and state. Optimizes for code reuse and lazy-loading.

### Folder structure

```
src/
  features/
    auth/                       # domain logic, service, hooks
      useAuth.ts
      authService.ts
    analytics/
      useAnalytics.ts
      analyticsService.ts
    briefs/
      useBriefs.ts
      briefsService.ts
    templates/
      useTemplates.ts
    trends/
      useTrends.ts
    # ... 10 more features
  pages/                        # route containers (lazy-loaded)
    LoginPage.tsx
    DashboardPage.tsx
    BriefsPage.tsx
    TemplatesPage.tsx
    # ... 20 more pages
  lib/
    api.ts                      # fetch wrapper + refreshAccessToken race-guard + APIError class
    video.ts                    # service modules (domain-specific HTTP calls)
    analytics.ts
    briefs.ts
    # ... 15+ service modules
  stores/
    video.ts                    # zustand with persist middleware
    analytics.ts
    trends.ts
    # ... 10+ stores
  types/
    video.ts
    analytics.ts
    briefs.ts
    error-codes.ts
    # ... 20+ type files
  components/
    ui/                         # generic primitives (Button, Input, Card, Modal)
      Button.tsx
      Input.tsx
      Card.tsx
    domain/                     # feature-specific composed components
      VideoPlayer.tsx
      BriefCard.tsx
      TrendChart.tsx
  hooks/                        # shared hooks (useDebounce, useLocalStorage, useClipboard)
  assets/                       # images, icons
  __tests__/
    contracts/                  # msw-based contract tests
  main.tsx
  App.tsx                       # router with lazy-loaded pages
  index.css
  vite-env.d.ts
```

### State management

- **Server state** → `lib/<domain>.ts` service modules call `api.get/post/put/delete` from `lib/api.ts`; features wrap these in custom hooks or call directly (anti-pattern: bypasses react-query cache; observed in reference service B)
  - Example: `lib/video.ts` exports `videoService.generate(briefId)` → calls `api.post('/videos', { brief_id: briefId })`
  - Example: `features/briefs/useBriefs.ts` might call `api.get('/briefs')` directly (bypasses cache)
- **Client state** → zustand stores in `stores/<domain>.ts` with persist middleware for UI workflow state
  - Example: `stores/video.ts` tracks `currentVideo`, `isLoading`, `isGenerating`, `isPolling`, polling interval
  - Example: `stores/analytics.ts` tracks active filters, selected date range, chart type

**Note**: reference service B has react-query installed but underuses it; many stores fetch directly from `lib/api`, which bypasses caching/deduplication. This is an anti-pattern; prefer wrapping `api.*` calls in react-query hooks for GET-equivalent requests.

### Path aliases

`tsconfig.app.json` and `vite.config.ts` define rich aliases:

```json
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
```

Enables imports like `import { Button } from '@components/ui/Button';` instead of `../../components/ui/Button`.

### Lazy-loaded pages

`App.tsx` uses `React.lazy` + `Suspense` for code-splitting:

```typescript
import { lazy, Suspense } from 'react';

const DashboardPage = lazy(() => import('@pages/DashboardPage'));
const BriefsPage = lazy(() => import('@pages/BriefsPage'));

function App() {
  return (
    <Suspense fallback={<LoadingScreen />}>
      <Routes>
        <Route path="/dashboard" element={<DashboardPage />} />
        <Route path="/briefs" element={<BriefsPage />} />
        {/* ... */}
      </Routes>
    </Suspense>
  );
}
```

### Pros/Cons

**Pros:**
- Optimized for code reuse (shared components in `components/ui`, shared hooks in `hooks/`)
- Lazy-loading reduces initial bundle size
- Flat feature structure is easier to navigate for smaller teams
- Rich path aliases simplify imports

**Cons:**
- As features grow, `lib/` and `types/` become grab-bags (15+ service modules, 20+ type files)
- No clear domain boundaries; features can cross-pollinate unintentionally
- Anti-pattern risk: bypassing react-query cache by calling `api.*` directly in stores

---

## Model C: GraphQL-SSR (Reference Service C)

**Use when**: Schema-driven apps with SSR requirements, file uploads, and complex multi-entity relationships (e.g., ATS with jobs, candidates, interviews, projects). GraphQL eliminates the API-layer boilerplate and Apollo cache handles server state automatically.

### Folder structure

```
src/
  graphql/
    client.ts                   # apolloClient with authLink + errorLink + createUploadLink
    queries/
      jobs.ts                   # gql`` tagged templates
      candidates.ts
      interviews.ts
      # ... 15+ query files
  pages/
    JobsPage.tsx
    CandidatesPage.tsx
    InterviewsPage.tsx
    # ... 46+ page files
  components/                   # FLAT (anti-pattern: 50+ files in one directory)
    Button.tsx
    Input.tsx
    JobCard.tsx
    CandidateCard.tsx
    InterviewTimeline.tsx
    # ... 50+ components (should be split into ui/ + domain/ subdirectories)
  contexts/
    AuthContext.tsx             # useAuth hook + ME_QUERY + LOGIN_MUTATION
    OrgContext.tsx              # useOrg hook + org selection logic
    ThemeContext.tsx
    ConfigContext.tsx
  stores/
    authStore.ts                # zustand for client state (theme, sidebar open/closed)
  utils/
    desktopBridge.ts            # Electron integration
    webStorage.ts
    # ... 15+ utilities
  services/
    # ... (inferred; minimal; most logic in contexts/hooks)
  constants/
    # ... (inferred)
  hooks/
    # ... (inferred; GraphQL hooks via Apollo)
  lib/
    # ... (inferred)
  entry-client.tsx              # client-side hydration entry
  entry-server.tsx              # SSR entry (renderToString)
  main.tsx                      # dev entry (no SSR)
  App.tsx                       # 80+ inline routes (anti-pattern; should be split into route modules)
  index.css
  vite-env.d.ts
```

**SSR-specific files:**
- `entry-server.tsx` — exports `render(url)` that returns `{ html: string }` via `ReactDOMServer.renderToString`
- `entry-client.tsx` — hydrates the server-rendered HTML via `ReactDOM.hydrateRoot`
- `ssr-server.ts` (inferred; not in scan) — Express/Fastify server that calls `render(req.url)` and injects the HTML into an HTML template

### State management

- **Server state** → Apollo cache (InMemoryCache with typePolicies for jobs/candidates merge strategies)
  - Example: `useQuery(ME_QUERY)` in `AuthContext.tsx` fetches user data; Apollo caches it automatically
  - Example: `useMutation(LOGIN_MUTATION)` in `AuthContext.tsx` performs login and updates cache
  - No need for react-query; Apollo handles caching, refetching, deduplication
- **Client state** → React Contexts (AuthContext, OrgContext, ThemeContext, ConfigContext) + zustand for UI toggles
  - Example: `AuthContext` provides `{ user, login, logout, loading }` to the tree
  - Example: `OrgContext` provides `{ currentOrg, switchOrg, orgs }` for multi-tenancy
  - Example: `authStore.ts` (zustand) might track sidebar open/closed state, theme preference
- **Apollo client setup**:
  - `authLink` (setContext) injects `Bearer reference service C_token` + `x-org-id` header into every request
  - `errorLink` (onError) catches `UNAUTHENTICATED` errors and redirects to `/login` (unless already on `/login`, `/register`, `/sso/*`)
  - `createUploadLink` (apollo-upload-client) enables file uploads via GraphQL multipart request spec
  - `InMemoryCache` with custom `typePolicies` to merge jobs/candidates arrays (prevents cache duplication)

### API layer (GraphQL)

**`src/graphql/client.ts`:**

```typescript
import { ApolloClient, InMemoryCache, from } from '@apollo/client';
import { setContext } from '@apollo/client/link/context';
import { onError } from '@apollo/client/link/error';
import { createUploadLink } from 'apollo-upload-client';

const httpLink = createUploadLink({
  uri: getGraphqlUrl(),
  headers: { 'apollo-require-preflight': 'true' }, // Apollo Server 4 CSRF protection
});

const authLink = setContext((_, { headers }) => {
  const token = localStorage.getItem('reference service C_token');
  const orgId = localStorage.getItem('reference service C_org_id');
  return {
    headers: {
      ...headers,
      authorization: token ? `Bearer ${token}` : '',
      ...(orgId && { 'x-org-id': orgId }),
    },
  };
});

const errorLink = onError(({ graphQLErrors }) => {
  graphQLErrors?.forEach(({ extensions }) => {
    if (extensions?.code === 'UNAUTHENTICATED') {
      const isAuthPage = ['/login', '/register'].includes(window.location.pathname) || window.location.pathname.startsWith('/sso');
      if (!isAuthPage) {
        localStorage.removeItem('reference service C_token');
        window.location.href = '/login';
      }
    }
  });
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

**Usage in components:**

```typescript
import { useQuery, useMutation, gql } from '@apollo/client';

const GET_JOBS = gql`
  query GetJobs($status: String) {
    jobs(status: $status) { id title status location }
  }
`;

function JobsPage() {
  const { data, loading, error } = useQuery(GET_JOBS, { variables: { status: 'active' } });
  // Apollo cache handles caching/refetching automatically
}
```

### Pros/Cons

**Pros:**
- GraphQL eliminates REST API boilerplate (no manual type transcription for queries; schema-first)
- Apollo cache handles server-state management automatically (no need for react-query)
- SSR improves SEO and initial load performance
- File upload support via `createUploadLink` (multipart GraphQL spec)
- Multi-tenancy via `x-org-id` header (clean separation)

**Cons:**
- 80+ inline routes in `App.tsx` is an anti-pattern (refactor to route modules or route config array)
- 50+ components in a flat directory is hard to navigate (split into `ui/` + `domain/` or feature folders)
- Mixed default/named exports creates inconsistency (stick to named exports)
- SSR adds complexity (requires server setup, hydration logic, build tooling)
- GraphQL adds backend complexity (schema design, resolver logic, N+1 query risk)

---

## Comparison: when to use which model

| Criterion | Module-scoped (A) | Feature-sliced (B) | GraphQL-SSR (C) |
|-----------|-------------------|--------------------|--------------------|
| **App size** | Large (20+ domains) | Medium (10–20 features) | Medium–Large (schema-driven) |
| **Domain boundaries** | Strong (each module is a mini-app) | Weak (flat features folder) | Weak (flat pages/components) |
| **Code reuse** | Shared components in top-level `components/` | Optimized (`components/ui`, shared hooks) | Moderate (flat structure limits reuse) |
| **State management** | react-query + zustand | fetch + zustand (anti-pattern: bypasses cache) | Apollo cache + contexts + zustand |
| **API layer** | Axios + manual wrappers | Fetch + token refresh race-guard | Apollo links (authLink + errorLink) |
| **Route organization** | Aggregated fragments (route.tsx per module) | Lazy-loaded pages | Inline (anti-pattern in reference service C) |
| **SSR support** | No | No | Yes (entry-server.tsx / ssr-server.ts) |
| **File uploads** | Manual FormData + axios | Manual FormData + fetch | GraphQL multipart (createUploadLink) |
| **Multi-tenancy** | Dynamic headers (API_HEADERS proxy) | X-Brand-ID header | x-org-id header (authLink) |
| **Best for** | Parallel domains (inventory, OTB, planogram) | Cross-cutting features (analytics, templates) | Schema-first apps (ATS, CMS, CRM) |

**Rule of thumb:**
- **< 10 features, simple REST API** → Start with feature-sliced (B); it's the most conventional
- **10–20 parallel domains, REST API** → Use module-scoped (A) if domains are independent; feature-sliced (B) if they share a lot of components
- **GraphQL backend, SSR required** → Use GraphQL-SSR (C); Apollo cache eliminates the need for react-query
- **20+ domains, monolith** → Use module-scoped (A); feature-sliced will become a grab-bag

---

## State-management best practices (all models)

1. **Server state** — Use react-query (models A/B) or Apollo cache (model C) for all GET-equivalent requests. These libraries handle caching, refetching, deduplication, and invalidation.
2. **Client state** — Use zustand or React Context for UI toggles, active filters, form drafts, sidebar open/closed, theme preference. NEVER store fetched data here (bypasses cache).
3. **Zustand patterns**:
   - Export the hook: `export const useVideoStore = create<VideoState>((set, get) => ({ /* ... */ }))`
   - Use immer middleware for nested updates: `import { immer } from 'zustand/middleware/immer'`
   - Use persist middleware for localStorage: `import { persist } from 'zustand/middleware'`
   - Split stores by domain (one store per feature/module, not a global store)
4. **React Context patterns**:
   - Export a custom hook: `export function useAuth() { const ctx = useContext(AuthContext); if (!ctx) throw new Error('useAuth must be used within AuthProvider'); return ctx; }`
   - Wrap the app in providers at the top level (App.tsx or main.tsx)
   - Use contexts for cross-cutting concerns (auth, org, theme, feature flags)
5. **Avoid the anti-pattern**: Storing server data in zustand/context and fetching manually in stores. Example from reference service B: `stores/video.ts` calls `videoService.generate()` which calls `api.post()` directly. This bypasses react-query cache. Instead, wrap `api.post()` in a `useMutation` hook and call the mutation from the component.

**Correct pattern (model A, react-query):**

```typescript
// modules/video/api/videoApi.ts
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { apiPost } from '@/lib/api';

export function useGenerateVideoMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (briefId: string) => apiPost<Video>('/videos/generate', { brief_id: briefId }),
    onSuccess: () => queryClient.invalidateQueries(['videos']),
  });
}

// modules/video/components/GenerateButton.tsx
import { useGenerateVideoMutation } from '../api/videoApi';

function GenerateButton({ briefId }: { briefId: string }) {
  const { mutate, isLoading } = useGenerateVideoMutation();
  return <button onClick={() => mutate(briefId)} disabled={isLoading}>Generate Video</button>;
}
```

**Incorrect pattern (reference service B anti-pattern):**

```typescript
// stores/video.ts
export const useVideoStore = create<VideoState>((set) => ({
  generateVideo: async (briefId: string) => {
    set({ isGenerating: true });
    const video = await videoService.generate(briefId); // bypasses cache
    set({ currentVideo: video, isGenerating: false });
  },
}));

// lib/video.ts
export const videoService = {
  generate: (briefId: string) => api.post<Video>('/videos/generate', { brief_id: briefId }),
};
```

Why is this wrong? Every call to `generateVideo()` hits the API, even if the video was just generated 5 seconds ago. react-query would cache the result and deduplicate concurrent requests.
