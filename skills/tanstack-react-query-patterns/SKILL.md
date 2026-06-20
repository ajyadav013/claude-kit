---
name: tanstack-react-query-patterns
description: Encodes production TanStack Query (React Query) conventions covering query-key factories, typed custom hooks, QueryClient configuration, cache invalidation, optimistic updates with rollback, and computed selectors. Use when building data-fetching hooks, implementing mutations with cache updates, configuring pagination with placeholderData, setting up polling queries, or structuring cache invalidation strategies.
---

Standardize TanStack Query data fetching, caching, and mutations following production patterns for maintainable, type-safe React applications.

## When to use

- Building custom hooks that wrap `useQuery` or `useMutation` with domain-specific logic
- Creating query-key factories for consistent cache key management
- Configuring QueryClient with stale time, garbage collection, and retry logic
- Implementing cache invalidation strategies after mutations
- Setting up optimistic updates with rollback in `onMutate` and `onError`
- Building paginated queries with `placeholderData` for smooth transitions
- Creating polling queries with conditional `refetchInterval` and terminal-state detection
- Extracting computed values from query data with `useMemo` selectors
- Prefetching data for anticipated navigation or hover interactions
- Integrating with typed API client layers for end-to-end type safety

## Core conventions

1. **Query-key factory pattern**: define a `<domain>Keys` object exporting hierarchical query keys as const arrays. Structure: `all → lists() → list(filters) → details() → detail(id)`. Each level narrows scope. Use spread syntax to build child keys from parent keys. Co-locate factory with the primary query hook in the same file.

2. **Custom hook wrapper with typed options**: wrap `useQuery` in a domain hook like `use<Domain>s(filters, options)` that accepts typed `options` interface with `enabled?: boolean` and `keepPreviousData?: boolean`. Pass `queryKey` from factory, `queryFn` from API client, and merge user options with defaults. Return spread query result plus computed selectors (`isEmpty`, `pagination`, domain-specific arrays).

3. **QueryClient global config in `main.tsx`**: instantiate `new QueryClient({ defaultOptions: { queries: { staleTime, gcTime, retry, refetchOnWindowFocus }, mutations: { retry } } })`. Common values: `staleTime: 5 * 60 * 1000` (5 min), `gcTime: 30 * 60 * 1000` (30 min). Custom `retry` function checks `error.status` or `error.response?.status` to skip retries on 4xx/5xx, retry only network errors. Wrap app in `<QueryClientProvider client={queryClient}>`.

4. **Cache invalidation after mutations**: in `useMutation` `onSuccess`, call `queryClient.invalidateQueries({ queryKey: domainKeys.lists() })` to refetch all list queries, and optionally invalidate `domainKeys.detail(id)` for the mutated item. Use `invalidateQueries` for server-driven updates where the server returns canonical state. Use `removeQueries` for deleted items.

5. **Optimistic cache updates in toggle/patch mutations**: in `onSuccess`, call `queryClient.setQueryData(domainKeys.detail(id), (old) => old ? { ...old, field: newValue } : old)` to update the cache immediately without waiting for refetch. Invalidate list queries afterward to propagate the change. For true optimistic updates, move `setQueryData` to `onMutate` and store previous value in context for rollback in `onError`.

6. **Pagination with `placeholderData`**: for paginated list queries, pass `placeholderData: keepPreviousData ? (previousData) => previousData : undefined` to `useQuery`. This shows stale data while fetching the next page, preventing layout shift. TanStack Query v5 replaced the deprecated `keepPreviousData` boolean with the `placeholderData` function.

7. **Polling queries with conditional `refetchInterval`**: use `refetchInterval: shouldPoll ? pollingInterval : false` in `useQuery` options. Track `shouldPoll` in local state; set to `false` when terminal state detected (`status === 'completed' || status === 'failed'`). Use `staleTime: 0` for polling to force fresh fetch every interval. Expose `stopPolling` and `startPolling` callbacks from the hook.

8. **Computed selectors with `useMemo`**: derive domain-specific arrays or flags from `query.data` using `useMemo(() => query.data?.items ?? [], [query.data])` to avoid recomputation on every render. Return these alongside the query result spread (`{ ...query, items, isEmpty }`). Common selectors: `items`, `pagination`, `isEmpty`, terminal state flags (`isCompleted`, `isFailed`, `isProcessing`).

9. **Typed mutation hooks with callback options**: define `Use<Action>Options` interface with `onSuccess?: (data) => void` and `onError?: (error) => void`. Wrap `useMutation` and call user callbacks after internal cache logic. Accept mutation variables as typed object `{ id, brandId, data }` in `mutationFn` to support multi-arg mutations.

10. **Prefetch hook with `queryClient.prefetchQuery`**: export a `usePrefetch<Domain>()` hook that returns a callback invoking `queryClient.prefetchQuery({ queryKey, queryFn, staleTime })`. Use for hover or navigation anticipation. The prefetched data populates the cache and will be used by subsequent `useQuery` calls.

11. **Custom retry logic**: define `shouldRetry(failureCount: number, error: unknown): boolean` that returns `false` if `failureCount >= 3` or if `error.status >= 400` (checks `error.status`, `error.response?.status`, `error instanceof Response`). Return `true` only for network errors (no response). Pass as `retry` to `QueryClient` defaults or individual query options.

12. **Separate mutation hooks by action**: create individual hooks `useCreate<Domain>()`, `useUpdate<Domain>()`, `useDelete<Domain>()`, `useToggle<Domain>Status()` rather than one monolithic mutation hook. Each hook invalidates/updates only relevant cache keys. Export all from a `<domain>Mutations.ts` file.

13. **Type-safe API client integration**: mutation hooks call typed API client functions `apiClient.<action>(params)` that return `Promise<DomainType>`. The API client handles fetch, auth headers, error parsing, and type deserialization. Query hooks similarly call typed `apiClient.list(filters)` or `apiClient.get(id)`.

14. **Callback refs for polling hooks**: use `useRef` to store `onComplete` and `onError` callbacks in polling hooks, and update refs in `useEffect` to avoid stale closures. Track `calledCallbackForRef` to ensure callbacks fire exactly once per terminal state transition. Reset tracking when `jobId` changes.

15. **Response structure awareness**: if API returns `{ items: [...], pagination: {...} }`, destructure in the custom hook and expose `items` and `pagination` as separate fields. If API returns plain array, wrap in `items` array yourself or return directly. Normalize inconsistent API shapes in custom hooks, not in components.

## Skeleton / example

```typescript
// features/items/hooks/useItems.ts
import { useQuery, useMutation, useQueryClient, useCallback } from '@tanstack/react-query';
import { useMemo } from 'react';
import { itemsApi } from '../api/itemsApi';
import type { Item, ItemFilters, ItemCreateRequest } from '@/types';

// ============================================================================
// Query Keys
// ============================================================================

export const itemKeys = {
  /** Base key for all item queries */
  all: ['items'] as const,

  /** Key for item list queries */
  lists: () => [...itemKeys.all, 'list'] as const,

  /** Key for item list with filters */
  list: (filters?: ItemFilters) => [...itemKeys.lists(), filters] as const,

  /** Key for single item queries */
  details: () => [...itemKeys.all, 'detail'] as const,

  /** Key for single item detail */
  detail: (id: string) => [...itemKeys.details(), id] as const,

  /** Key for item stats */
  stats: (id: string) => [...itemKeys.all, 'stats', id] as const,
};

// ============================================================================
// Hook Options
// ============================================================================

export interface UseItemsOptions {
  /** Enable/disable the query (default: true) */
  enabled?: boolean;

  /** Keep previous data while fetching new data (for pagination) */
  keepPreviousData?: boolean;
}

// ============================================================================
// Query Hook
// ============================================================================

/**
 * Hook for listing items with filtering and pagination.
 *
 * @example
 * ```tsx
 * function ItemList() {
 *   const { items, isLoading, pagination, isEmpty } = useItems({
 *     status: 'active',
 *     page: 1,
 *   });
 *
 *   if (isLoading) return <Spinner />;
 *   if (isEmpty) return <EmptyState />;
 *
 *   return <ItemGrid items={items} pagination={pagination} />;
 * }
 * ```
 */
export function useItems(
  filters: ItemFilters = {},
  options: UseItemsOptions = {}
) {
  const { enabled = true, keepPreviousData = true } = options;

  const query = useQuery({
    queryKey: itemKeys.list(filters),
    queryFn: () => itemsApi.list(filters),
    enabled,
    placeholderData: keepPreviousData ? (previousData) => previousData : undefined,
    staleTime: 30000, // 30 seconds
  });

  // Computed selectors
  const items = useMemo(() => query.data?.items ?? [], [query.data]);
  const pagination = useMemo(() => query.data?.pagination ?? null, [query.data]);

  return {
    ...query,
    items,
    pagination,
    isEmpty: items.length === 0 && !query.isLoading,
  };
}

/**
 * Hook for fetching a single item
 */
export function useItem(id: string | null, options?: { enabled?: boolean }) {
  return useQuery({
    queryKey: itemKeys.detail(id ?? ''),
    queryFn: () => itemsApi.get(id!),
    enabled: Boolean(id) && (options?.enabled ?? true),
  });
}

/**
 * Hook for prefetching items
 */
export function usePrefetchItems() {
  const queryClient = useQueryClient();

  return useCallback(
    async (filters: ItemFilters = {}) => {
      await queryClient.prefetchQuery({
        queryKey: itemKeys.list(filters),
        queryFn: () => itemsApi.list(filters),
        staleTime: 30000,
      });
    },
    [queryClient]
  );
}
```

```typescript
// features/items/hooks/useItemMutations.ts
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { itemsApi } from '../api/itemsApi';
import { itemKeys } from './useItems';
import type { Item, ItemCreateRequest, ItemUpdateRequest } from '@/types';

// ============================================================================
// Create Hook
// ============================================================================

export interface UseCreateItemOptions {
  onSuccess?: (item: Item) => void;
  onError?: (error: Error) => void;
}

export function useCreateItem(options: UseCreateItemOptions = {}) {
  const { onSuccess, onError } = options;
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (request: ItemCreateRequest) => itemsApi.create(request),
    onSuccess: (item) => {
      // Invalidate list queries
      queryClient.invalidateQueries({
        queryKey: itemKeys.lists(),
      });
      onSuccess?.(item);
    },
    onError: (error: Error) => {
      onError?.(error);
    },
  });
}

// ============================================================================
// Update Hook
// ============================================================================

export interface UseUpdateItemOptions {
  onSuccess?: (item: Item) => void;
  onError?: (error: Error) => void;
}

export function useUpdateItem(options: UseUpdateItemOptions = {}) {
  const { onSuccess, onError } = options;
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: ItemUpdateRequest }) =>
      itemsApi.update(id, data),
    onSuccess: (item, variables) => {
      // Update detail in cache
      queryClient.setQueryData(itemKeys.detail(variables.id), item);
      // Invalidate list queries
      queryClient.invalidateQueries({
        queryKey: itemKeys.lists(),
      });
      onSuccess?.(item);
    },
    onError: (error: Error) => {
      onError?.(error);
    },
  });
}

// ============================================================================
// Toggle Status Hook (Optimistic Update)
// ============================================================================

export interface UseToggleItemStatusOptions {
  onSuccess?: (item: Item) => void;
  onError?: (error: Error) => void;
}

export function useToggleItemStatus(options: UseToggleItemStatusOptions = {}) {
  const { onSuccess, onError } = options;
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ id }: { id: string }) => itemsApi.toggleStatus(id),
    onSuccess: (response, variables) => {
      // Optimistically update cache
      queryClient.setQueryData(
        itemKeys.detail(variables.id),
        (old: Item | undefined) =>
          old ? { ...old, is_active: response.is_active } : old
      );
      // Invalidate list to reflect change
      queryClient.invalidateQueries({
        queryKey: itemKeys.lists(),
      });
      onSuccess?.(response);
    },
    onError: (error: Error) => {
      onError?.(error);
    },
  });
}

// ============================================================================
// Delete Hook
// ============================================================================

export interface UseDeleteItemOptions {
  onSuccess?: () => void;
  onError?: (error: Error) => void;
}

export function useDeleteItem(options: UseDeleteItemOptions = {}) {
  const { onSuccess, onError } = options;
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ id }: { id: string }) => itemsApi.delete(id),
    onSuccess: (_, variables) => {
      // Remove detail from cache
      queryClient.removeQueries({
        queryKey: itemKeys.detail(variables.id),
      });
      // Invalidate list queries
      queryClient.invalidateQueries({
        queryKey: itemKeys.lists(),
      });
      onSuccess?.();
    },
    onError: (error: Error) => {
      onError?.(error);
    },
  });
}
```

```typescript
// main.tsx (QueryClient config)
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import App from './App';

/**
 * Custom retry logic: only retry network errors, not HTTP 4xx/5xx
 */
function shouldRetry(failureCount: number, error: unknown): boolean {
  if (failureCount >= 3) return false;

  // Check for HTTP error with status
  if (error && typeof error === 'object') {
    if ('status' in error && typeof error.status === 'number') {
      if (error.status >= 400) return false;
    }
    if ('response' in error && error.response && typeof error.response === 'object') {
      if ('status' in error.response && typeof error.response.status === 'number') {
        if (error.response.status >= 400) return false;
      }
    }
  }

  if (error instanceof Response && error.status >= 400) {
    return false;
  }

  // Only retry network errors
  return true;
}

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 5 * 60 * 1000,       // 5 minutes
      gcTime: 30 * 60 * 1000,         // 30 minutes (formerly cacheTime)
      retry: shouldRetry,
      refetchOnWindowFocus: true,
    },
    mutations: {
      retry: shouldRetry,
    },
  },
});

const rootEl = document.getElementById('root');
if (!rootEl) throw new Error('Root element not found');

createRoot(rootEl).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>
  </StrictMode>
);
```

```typescript
// Polling hook example
export function useJobStatus(
  jobId: string | null,
  options?: {
    enabled?: boolean;
    pollingInterval?: number;
    onComplete?: (job: Job) => void;
    onError?: (job: Job) => void;
  }
) {
  const { enabled = true, pollingInterval = 2000, onComplete, onError } = options ?? {};
  const [shouldPoll, setShouldPoll] = useState(true);
  const queryClient = useQueryClient();

  // Use refs to avoid stale closures
  const onCompleteRef = useRef(onComplete);
  const onErrorRef = useRef(onError);
  const calledCallbackForRef = useRef<string | null>(null);

  useEffect(() => {
    onCompleteRef.current = onComplete;
    onErrorRef.current = onError;
  });

  // Reset when jobId changes
  useEffect(() => {
    calledCallbackForRef.current = null;
    setShouldPoll(true);
  }, [jobId]);

  const query = useQuery({
    queryKey: jobKeys.status(jobId ?? ''),
    queryFn: () => jobsApi.getStatus(jobId!),
    enabled: Boolean(jobId) && enabled,
    refetchInterval: shouldPoll ? pollingInterval : false,
    staleTime: 0, // Always fresh for polling
  });

  // Handle terminal states
  useEffect(() => {
    if (query.data) {
      const isTerminal = query.data.status === 'completed' || query.data.status === 'failed';

      if (isTerminal) {
        setShouldPoll(false);

        const callbackKey = `${jobId}:${query.data.status}`;
        if (calledCallbackForRef.current !== callbackKey) {
          calledCallbackForRef.current = callbackKey;

          if (query.data.status === 'completed' && onCompleteRef.current) {
            onCompleteRef.current(query.data);
            queryClient.invalidateQueries({ queryKey: itemKeys.lists() });
          } else if (query.data.status === 'failed' && onErrorRef.current) {
            onErrorRef.current(query.data);
          }
        }
      }
    }
  }, [query.data, jobId, queryClient]);

  return {
    ...query,
    status: query.data,
    isPolling: shouldPoll,
    stopPolling: useCallback(() => setShouldPoll(false), []),
    startPolling: useCallback(() => setShouldPoll(true), []),
    isCompleted: query.data?.status === 'completed',
    isFailed: query.data?.status === 'failed',
  };
}
```

## Anti-patterns to avoid

1. **Not using query-key factories**: hardcoding query keys as strings in each hook leads to invalidation mismatches and stale data. Use a centralized factory with hierarchical const arrays.
2. **Invalidating with `queryKey: itemKeys.all`**: too broad; invalidates unrelated queries. Use `itemKeys.lists()` or `itemKeys.list(filters)` to target relevant queries.
3. **Using deprecated `keepPreviousData: true`**: TanStack Query v5 removed this; use `placeholderData: (previousData) => previousData` instead.
4. **Mutating `query.data` directly**: React Query data is read-only. Use `queryClient.setQueryData` with a pure updater function.
5. **Not handling null/undefined in custom hooks**: check `Boolean(id)` in `enabled` to prevent queries with null IDs. Use `id!` assertion only after enabled guard.
6. **Polling without terminal-state detection**: queries with `refetchInterval` will poll forever unless you conditionally set it to `false` when done.
7. **Using `refetchInterval` with non-zero `staleTime`**: stale data won't refetch. Set `staleTime: 0` for polling queries.
8. **Stale closures in polling callbacks**: store callbacks in refs and update them in `useEffect` to avoid capturing stale state.
9. **Calling `invalidateQueries` before optimistic update**: do optimistic `setQueryData` first, then `invalidateQueries` to avoid flicker.
10. **Not prefetching on hover**: for anticipated navigation, use `usePrefetchItems()` in `onMouseEnter` to load data before click.
11. **Returning raw `query` object**: custom hooks should expose domain-specific fields (`items`, `pagination`, `isEmpty`) alongside the query result spread.
12. **Mixing query keys with different filter structures**: always pass filters in the same shape (object with optional fields) to avoid cache misses.

## References

- [query-keys-and-hooks.md](references/query-keys-and-hooks.md) — query-key factory pattern, custom hook structure, typed options, prefetch hooks
- [mutations-and-cache.md](references/mutations-and-cache.md) — mutation hooks, cache invalidation, optimistic updates, polling patterns
- [repo-evidence.md](references/repo-evidence.md) — source patterns from production codebases

Cross-reference: [frontend-repo-architecture](../frontend-repo-architecture/SKILL.md) for overall React project structure; [graphql-patterns](../graphql-patterns/SKILL.md) for Apollo cache comparison (Apollo normalized cache vs React Query key-based cache).
