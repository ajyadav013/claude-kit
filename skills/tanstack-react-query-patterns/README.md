# TanStack React Query Patterns

A Claude Code skill capturing production patterns for TanStack Query (React Query) data fetching, caching, and state management in React applications.

## What this covers

This skill encodes battle-tested patterns for:

- **Query-key factories** — hierarchical const-array factories (`domainKeys.all → lists() → list(filters) → details() → detail(id)`) for consistent cache key management
- **Custom typed hooks** — domain-specific wrappers around `useQuery` and `useMutation` with typed option interfaces, computed selectors, and sensible defaults
- **QueryClient configuration** — global setup for `staleTime`, `gcTime`, custom retry logic (skip 4xx/5xx, retry network errors only), and refetch behavior
- **Cache invalidation strategies** — targeted `invalidateQueries` after mutations, `removeQueries` for deletions, `setQueryData` for optimistic updates
- **Optimistic updates with rollback** — immediate UI updates in `onMutate` with snapshot/restore in `onError`, plus server reconciliation in `onSuccess`
- **Pagination with `placeholderData`** — smooth page transitions using `placeholderData: (previousData) => previousData` (v5 replacement for deprecated `keepPreviousData`)
- **Polling queries** — conditional `refetchInterval` with terminal-state detection, callback refs to avoid stale closures, exposed `stopPolling`/`startPolling` controls
- **Computed selectors** — `useMemo` derivations for domain arrays, pagination metadata, and status flags (`isEmpty`, `isCompleted`, `isFailed`)
- **Prefetch hooks** — `queryClient.prefetchQuery` for hover/navigation anticipation
- **Type-safe API integration** — typed mutation variables and API client functions

## Origins

This skill derives from real production services built with TanStack Query v4 and v5, including:

- Multi-tenant SaaS frontends with paginated resource lists, filtering, and real-time updates
- Video generation workflows with polling job status and optimistic avatar toggles
- Product catalog management with bulk upload, CSV validation, and spec regeneration
- CTA template libraries with usage tracking and incremental cache updates

All patterns are genericized and safe for public use. No internal service names, credentials, or proprietary logic are included.

## Usage

Invoke this skill when:

- Scaffolding data-fetching hooks for a new React feature
- Migrating from v4 `keepPreviousData` to v5 `placeholderData`
- Implementing cache invalidation after create/update/delete mutations
- Building polling queries for async job status
- Setting up QueryClient defaults with custom retry logic
- Structuring query keys to support targeted invalidation
- Adding optimistic updates for toggle/patch mutations
- Creating prefetch hooks for performance optimization

## Cross-references

- **frontend-repo-architecture** — overall React project structure and feature organization
- **graphql-patterns** — Apollo cache comparison (normalized vs key-based caching)
