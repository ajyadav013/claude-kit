# Query Keys and Custom Hooks

## Query-Key Factory Pattern

Production React Query codebases use a **hierarchical query-key factory** to ensure consistent cache keys across queries and invalidations.

### Structure

```typescript
export const domainKeys = {
  /** Base key for all domain queries */
  all: ['domain'] as const,

  /** Keys for list queries */
  lists: () => [...domainKeys.all, 'list'] as const,

  /** Key for list with specific filters */
  list: (filters?: DomainFilters) => [...domainKeys.lists(), filters] as const,

  /** Keys for detail queries */
  details: () => [...domainKeys.all, 'detail'] as const,

  /** Key for single detail */
  detail: (id: string) => [...domainKeys.details(), id] as const,

  /** Key for stats or related entities */
  stats: (id: string) => [...domainKeys.all, 'stats', id] as const,

  /** Key for selection views (filtered subset) */
  selection: (filters?: Record<string, unknown>) =>
    [...domainKeys.all, 'selection', filters] as const,
};
```

### Why Hierarchical?

- **Targeted invalidation**: `queryClient.invalidateQueries({ queryKey: domainKeys.lists() })` invalidates all list queries but not detail queries
- **Type safety**: `as const` ensures arrays are readonly tuples, preventing accidental mutation
- **Consistency**: single source of truth for cache keys; avoids string typos across hooks
- **Debuggability**: keys appear in React Query DevTools with clear hierarchy

### Co-location

Query-key factories live in the same file as the primary query hook (e.g., `useItems.ts` exports `itemKeys` and `useItems`). Mutation hooks in a separate file (`useItemMutations.ts`) import the factory.

## Custom Query Hook Pattern

Wrap `useQuery` with domain-specific logic:

```typescript
export interface UseItemsOptions {
  enabled?: boolean;
  keepPreviousData?: boolean;
}

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
    staleTime: 30000,
  });

  const items = useMemo(() => query.data?.items ?? [], [query.data]);
  const pagination = useMemo(() => query.data?.pagination ?? null, [query.data]);

  return {
    ...query,
    items,
    pagination,
    isEmpty: items.length === 0 && !query.isLoading,
  };
}
```

### Key Features

1. **Typed options interface**: explicit `UseItemsOptions` for hook configuration
2. **Default values**: `enabled = true`, `keepPreviousData = true` for sensible defaults
3. **Computed selectors**: `useMemo` for `items`, `pagination`, `isEmpty` to avoid recomputation
4. **Spread query result**: return `{ ...query, items, pagination, isEmpty }` so callers get both raw query state and domain-specific fields
5. **Stale time override**: per-query `staleTime` can differ from global default

### Detail Hook

```typescript
export function useItem(id: string | null, options?: { enabled?: boolean }) {
  return useQuery({
    queryKey: itemKeys.detail(id ?? ''),
    queryFn: () => itemsApi.get(id!),
    enabled: Boolean(id) && (options?.enabled ?? true),
  });
}
```

- **Null-safe**: accepts `id: string | null`, guards with `enabled: Boolean(id)`
- **Non-null assertion**: `id!` in `queryFn` is safe because `enabled` ensures it's non-null when called

## Prefetch Hooks

Enable prefetching for hover or navigation anticipation:

```typescript
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

Usage in component:

```tsx
function ItemCard({ id }: { id: string }) {
  const prefetchItem = usePrefetchItem();

  return (
    <Link
      to={`/items/${id}`}
      onMouseEnter={() => prefetchItem(id)}
    >
      View Item
    </Link>
  );
}
```

The prefetched data populates the cache; when the user navigates, `useItem(id)` reads from cache instantly.

## Pagination with placeholderData

TanStack Query v5 replaced the boolean `keepPreviousData` with a `placeholderData` function:

```typescript
// v4 (deprecated)
useQuery({
  queryKey: itemKeys.list(filters),
  queryFn: () => itemsApi.list(filters),
  keepPreviousData: true, // ❌ Removed in v5
});

// v5 (current)
useQuery({
  queryKey: itemKeys.list(filters),
  queryFn: () => itemsApi.list(filters),
  placeholderData: (previousData) => previousData, // ✅ Shows stale data while fetching
});
```

### Why Use placeholderData?

- **Smooth pagination**: when user clicks "Next Page", old data stays visible until new data arrives
- **No layout shift**: prevents empty state flash between page transitions
- **Configurable**: can return `previousData`, partial data, or `undefined` based on logic

### Example in Custom Hook

```typescript
export function useItems(filters: ItemFilters, options: UseItemsOptions = {}) {
  const { keepPreviousData = true } = options;

  const query = useQuery({
    queryKey: itemKeys.list(filters),
    queryFn: () => itemsApi.list(filters),
    placeholderData: keepPreviousData ? (previousData) => previousData : undefined,
  });

  return { ...query, items: query.data?.items ?? [] };
}
```

Component usage:

```tsx
function ItemList() {
  const [page, setPage] = useState(1);
  const { items, isLoading, isFetching } = useItems({ page }, { keepPreviousData: true });

  return (
    <>
      {isFetching && <LoadingSpinner />} {/* Shows while fetching next page */}
      <ItemGrid items={items} /> {/* Shows previous page data during fetch */}
      <Pagination page={page} onPageChange={setPage} />
    </>
  );
}
```

## Multi-Level Filters

For complex filtering, normalize filter structure:

```typescript
export interface ItemFilters {
  status?: 'active' | 'inactive';
  category?: string;
  search?: string;
  page?: number;
  pageSize?: number;
  sortBy?: string;
  sortOrder?: 'asc' | 'desc';
}

export const itemKeys = {
  list: (filters?: ItemFilters) => [...itemKeys.lists(), filters] as const,
};
```

React Query serializes the filter object into the query key, so `{ page: 1, status: 'active' }` and `{ status: 'active', page: 1 }` are **different keys**. Normalize filter order in the API client or use a custom serializer.

### Filter Normalization

```typescript
function normalizeFilters(filters: ItemFilters): ItemFilters {
  const { status, category, search, page = 1, pageSize = 20, sortBy, sortOrder } = filters;
  return { status, category, search, page, pageSize, sortBy, sortOrder };
}

export const itemKeys = {
  list: (filters?: ItemFilters) => [...itemKeys.lists(), normalizeFilters(filters ?? {})] as const,
};
```

Now `{ page: 1, status: 'active' }` and `{ status: 'active', page: 1 }` resolve to the same cache entry.

## Selection Hooks

For dropdown/select components that need a filtered subset:

```typescript
export function useItemsForSelection(
  filters?: { category?: string },
  options?: { enabled?: boolean }
) {
  return useQuery({
    queryKey: itemKeys.selection(filters),
    queryFn: () => itemsApi.listForSelection(filters),
    enabled: options?.enabled ?? true,
    staleTime: 60000, // Longer stale time for relatively static data
  });
}
```

Used in forms:

```tsx
function ItemSelector({ category }: { category: string }) {
  const { data: items, isLoading } = useItemsForSelection({ category });

  return (
    <Select disabled={isLoading}>
      {items?.map(item => (
        <Option key={item.id} value={item.id}>{item.name}</Option>
      ))}
    </Select>
  );
}
```

## Stats and Derived Queries

For related data like statistics:

```typescript
export const itemKeys = {
  stats: (id: string) => [...itemKeys.all, 'stats', id] as const,
};

export function useItemStats(id: string | null) {
  return useQuery({
    queryKey: itemKeys.stats(id ?? ''),
    queryFn: () => itemsApi.getStats(id!),
    enabled: Boolean(id),
    staleTime: 60000,
  });
}
```

Invalidation after mutation:

```typescript
// After updating an item, also invalidate its stats
queryClient.invalidateQueries({ queryKey: itemKeys.detail(id) });
queryClient.invalidateQueries({ queryKey: itemKeys.stats(id) });
```
