# frontend-repo-architecture

A Claude Code skill encoding three production-proven React frontend architectures: **module-scoped**, **feature-sliced**, and **GraphQL-based**.

## What this skill covers

- **Three organizational models** — module-scoped monolith, feature-sliced, GraphQL-SSR; when to use each
- **API layer strategies** — axios + react-query hooks, fetch wrapper + token refresh race-guard, Apollo links
- **State management** — server-state vs client-state split (react-query/Apollo for server data; zustand/context for client state)
- **Hand-written types convention** — no OpenAPI/GraphQL codegen; manual API type transcription
- **Runtime config via `window._conf`** — multi-tenant environment variable injection
- **Path aliases** — `@/*`, `@components/*`, `@features/*`, `@lib/*`, `@stores/*`, `@types/*`, `@pages/*`
- **Tailwind + Radix/Headless UI** — `cn()` helper with `twMerge(clsx())`
- **Testing patterns** — vitest + @testing-library/react + msw contract tests; Apollo MockedProvider for GraphQL
- **Sentry integration** — 5xx-only error reporting

## Patterns derived from production services

- **Module-scoped model** (reference service A): `src/modules/<feature>/{api,components,hooks,stores,types,pages,route.tsx}` + `src/routes.tsx` aggregator; axios + react-query; runtime config via `window._conf` injected by Vite plugin; `apiFetch/apiPost` wrappers with `DYNAMIC_HEADERS` proxy; 401 → clear session + `/login`, 403 → `/unauthorized`; Radix + Tailwind + `cn()` helper; Capacitor mobile.
- **Feature-sliced model** (reference service B): `src/{features,pages,lib,stores,types,components/{ui,domain}}`; fetch wrapper in `lib/api.ts` with token refresh race-guard (single `refreshPromise`); zustand with persist middleware; rich path aliases; msw-based contract tests; `APIError` class with `.is(code)` helpers; anti-pattern: stores fetching directly (bypasses react-query cache).
- **GraphQL-SSR model** (reference service C): `@apollo/client` + `apollo-upload-client`; `authLink` (setContext adds Bearer + x-org-id) + `errorLink` (UNAUTHENTICATED → `/login`); Headless UI + Tailwind; zustand + React Contexts (Auth/Org/Theme/Config); SSR (`entry-server.tsx` / `ssr-server.ts`); Vite dev proxy forwards `/graphql` to backend; anti-patterns: 80+ inline routes in `App.tsx`, flat 50+ file `components/` directory, mixed default/named exports.

## How to apply

1. **Choose a model** based on project shape:
   - Module-scoped for large multi-domain apps with parallel verticals (reference service A pattern)
   - Feature-sliced for medium-sized apps with cross-cutting features (reference service B pattern)
   - GraphQL-based for schema-driven apps with SSR (reference service C pattern)

2. **Set up the API layer** to match your backend:
   - REST envelope-based (e.g., `{ data: T }` wrapper) → axios + react-query hooks + `apiFetch/apiPost` wrappers
   - REST flat JSON → fetch wrapper + token refresh race-guard + `APIError` class
   - GraphQL → Apollo client + authLink + errorLink + upload support

3. **Split server vs client state**:
   - Server state (GET-equivalent, cache/refetch/dedup) → react-query or Apollo cache
   - Client state (UI toggles, filters, form drafts) → zustand or React Context
   - NEVER store fetched data in zustand (bypasses caching)

4. **Hand-write API types** in `types/<domain>.ts` or `modules/<feature>/types/`; no codegen.

5. **Use runtime config** for multi-tenant/env-specific values (`window._conf` injected by Vite plugin or `/env-config` endpoint); build-time `VITE_*` vars are less flexible.

6. **Configure path aliases** in `tsconfig.app.json` and `vite.config.ts` for cleaner imports.

7. **Implement token refresh race-guard** if using fetch + JWT (reference service B `lib/api.ts` pattern).

8. **Report only 5xx errors to Sentry**; exclude 4xx (user errors).

## Provenance

### Codebase-derived

- **All three models**: folder structure, API layer implementations, state management patterns, token refresh logic, error handling, path aliases, hand-written types convention, Tailwind + Radix/Headless UI setup, vitest + testing-library + msw patterns, Sentry 5xx-only filter.
- **Exact snippets**: `lib/api.ts` (all three services), `routes.tsx` aggregator (reference service A), `environment.ts` (reference service A), `graphql/client.ts` (reference service C), zustand store examples (all three), `cn()` helper (reference service A).

### Internet-confirmed

- **React Query vs zustand split**: The server-state vs client-state pattern is a community best practice confirmed across React Query documentation and TanStack guidance.

> Confirmed against: https://tanstack.com/query/latest/docs/framework/react/guides/does-this-replace-client-state (React Query is for server state; client state tools like zustand are complementary, not replacements)

- **Apollo link composition**: The `authLink` + `errorLink` + `httpLink` pattern is canonical Apollo Client setup.

> Confirmed against: https://www.apollographql.com/docs/react/api/link/introduction (Apollo link documentation: composition via `from([errorLink, authLink, httpLink])`)

- **Token refresh race-guard**: The single `refreshPromise` pattern is a standard solution to concurrent refresh requests.

> Confirmed against: https://www.rfc-editor.org/rfc/rfc6749#section-6 (OAuth 2.0 token refresh flow; race condition handling is implementation-specific but widely documented in auth libraries)

All other patterns (module-scoped vs feature-sliced structure, `DYNAMIC_HEADERS` proxy, `APIError` class, `window._conf` runtime config, anti-patterns like storing server data in zustand) are unique to these codebases.
