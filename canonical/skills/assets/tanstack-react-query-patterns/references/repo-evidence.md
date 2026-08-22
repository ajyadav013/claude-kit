# Repository Evidence

This document shows genericized patterns extracted from production React frontends. All internal service names, paths, and identifiable details have been removed.

## QueryClient Configuration

From application entry point:

```typescript
// frontend/src/main.tsx
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

/**
 * Determine if a failed request should be retried.
 * Never retry on 4xx/5xx errors - only retry on network errors.
 */
function shouldRetry(failureCount: number, error: unknown): boolean {
  // Max 3 retries
  if (failureCount >= 3) return false;

  // Check if it's an HTTP error (has status property)
  if (error && typeof error === 'object' && 'status' in error) {
    const status = (error as { status: number }).status;
    // Don't retry on 4xx or 5xx errors
    if (status >= 400) return false;
  }

  // Check for Response-like errors
  if (error instanceof Response) {
    if (error.status >= 400) return false;
  }

  // Check for axios-like errors
  if (error && typeof error === 'object' && 'response' in error) {
    const response = (error as { response?: { status?: number } }).response;
    if (response?.status && response.status >= 400) return false;
  }

  // Only retry network errors (no response at all)
  return true;
}

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 5 * 60 * 1000,
      gcTime: 30 * 60 * 1000,
      retry: shouldRetry,
      refetchOnWindowFocus: true,
    },
    mutations: {
      retry: shouldRetry,
    },
  },
});

createRoot(rootElement).render(
  <StrictMode>
    <ErrorBoundary>
      <QueryClientProvider client={queryClient}>
        <BrowserRouter>
          <App />
        </BrowserRouter>
      </QueryClientProvider>
    </ErrorBoundary>
  </StrictMode>
);
```

Alternative minimal config from another service:

```typescript
// apps/web/src/main.tsx
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 5 * 60 * 1000,
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
});
```

## Query-Key Factories

From resource management hook:

```typescript
// features/resources/hooks/useResources.ts

/**
 * Query key factory for resource-related queries
 */
export const resourceKeys = {
  /** Base key for all resource queries */
  all: ['resources'] as const,

  /** Key for resource list queries */
  lists: () => [...resourceKeys.all, 'list'] as const,

  /** Key for resource list with specific filters */
  list: (tenantId: string, filters?: ResourceFilters) =>
    [...resourceKeys.lists(), tenantId, filters] as const,

  /** Key for single resource queries */
  details: () => [...resourceKeys.all, 'detail'] as const,

  /** Key for single resource detail */
  detail: (resourceId: string, tenantId: string) =>
    [...resourceKeys.details(), resourceId, tenantId] as const,

  /** Key for resource generation jobs */
  jobs: () => [...resourceKeys.all, 'jobs'] as const,

  /** Key for single job status */
  job: (jobId: string) => [...resourceKeys.jobs(), jobId] as const,

  /** Key for resource selection queries */
  selection: (tenantId: string, options?: Record<string, unknown>) =>
    [...resourceKeys.all, 'selection', tenantId, options] as const,
};
```

From product catalog hook:

```typescript
// features/products/hooks/useProducts.ts

export const productKeys = {
  all: ['products'] as const,

  list: (tenantId: string, filters?: ProductFilters) =>
    [...productKeys.all, 'list', tenantId, filters] as const,

  detail: (productId: string, tenantId: string) =>
    [...productKeys.all, 'detail', productId, tenantId] as const,

  forSelection: (tenantId: string, category?: ProductCategory) =>
    [...productKeys.all, 'selection', tenantId, category] as const,

  bulkUploadStatus: (jobId: string, tenantId: string) =>
    [...productKeys.all, 'bulk-upload', jobId, tenantId] as const,
};
```

## Custom Query Hooks with Options

From list hook with pagination support:

```typescript
// features/resources/hooks/useResources.ts

export interface UseResourcesOptions {
  /** Enable/disable the query (default: true) */
  enabled?: boolean;

  /** Keep previous data while fetching new data */
  keepPreviousData?: boolean;
}

/**
 * Hook for listing resources with filtering and pagination.
 */
export function useResources(
  tenantId: string | null,
  filters: ResourceFilters = {},
  options: UseResourcesOptions = {}
) {
  const { enabled = true, keepPreviousData = true } = options;

  const query = useQuery({
    queryKey: resourceKeys.list(tenantId ?? '', filters),
    queryFn: () => resourceApi.list(tenantId!, filters),
    enabled: Boolean(tenantId) && enabled,
    placeholderData: keepPreviousData ? (previousData) => previousData : undefined,
    staleTime: 30000, // 30 seconds
  });

  // Computed values
  const resources = useMemo(() => query.data?.items ?? [], [query.data]);
  const pagination = useMemo(() => query.data?.pagination ?? null, [query.data]);

  return {
    ...query,
    resources,
    pagination,
    isEmpty: resources.length === 0 && !query.isLoading,
  };
}
```

From product list hook:

```typescript
// features/products/hooks/useProducts.ts

export function useProducts(
  tenantId: string | null,
  filters: ProductFilters = {},
  options?: { enabled?: boolean }
) {
  return useQuery({
    queryKey: productKeys.list(tenantId ?? '', filters),
    queryFn: () => productsService.listProducts(tenantId!, filters),
    enabled: Boolean(tenantId) && (options?.enabled ?? true),
  });
}
```

## Prefetch Hooks

```typescript
// features/resources/hooks/useResources.ts

export function usePrefetchResources() {
  const queryClient = useQueryClient();

  return useCallback(
    async (tenantId: string, filters: ResourceFilters = {}) => {
      await queryClient.prefetchQuery({
        queryKey: resourceKeys.list(tenantId, filters),
        queryFn: () => resourceApi.list(tenantId, filters),
        staleTime: 30000,
      });
    },
    [queryClient]
  );
}
```

## Mutation Hooks with Cache Invalidation

From update mutation:

```typescript
// features/resources/hooks/useResourceMutations.ts

export interface UseUpdateResourceOptions {
  onSuccess?: (resource: Resource) => void;
  onError?: (error: Error) => void;
}

export function useUpdateResource(options: UseUpdateResourceOptions = {}) {
  const { onSuccess, onError } = options;
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({
      resourceId,
      tenantId,
      data,
    }: {
      resourceId: string;
      tenantId: string;
      data: ResourceUpdateRequest;
    }) => resourceApi.update(resourceId, tenantId, data),
    onSuccess: (resource, variables) => {
      // Invalidate related queries
      queryClient.invalidateQueries({
        queryKey: resourceKeys.lists(),
      });
      queryClient.invalidateQueries({
        queryKey: resourceKeys.detail(variables.resourceId, variables.tenantId),
      });
      onSuccess?.(resource);
    },
    onError: (error: Error) => {
      onError?.(error);
    },
  });
}
```

From delete mutation:

```typescript
export function useDeleteResource(options: UseDeleteResourceOptions = {}) {
  const { onSuccess, onError } = options;
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ resourceId, tenantId }: { resourceId: string; tenantId: string }) =>
      resourceApi.delete(resourceId, tenantId),
    onSuccess: (_, variables) => {
      // Invalidate list and remove detail from cache
      queryClient.invalidateQueries({
        queryKey: resourceKeys.lists(),
      });
      queryClient.removeQueries({
        queryKey: resourceKeys.detail(variables.resourceId, variables.tenantId),
      });
      onSuccess?.();
    },
    onError: (error: Error) => {
      onError?.(error);
    },
  });
}
```

## Optimistic Updates

From toggle status mutation:

```typescript
// features/resources/hooks/useResourceMutations.ts

export function useToggleResourceStatus(options: UseToggleResourceStatusOptions = {}) {
  const { onSuccess, onError } = options;
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ resourceId, tenantId }: { resourceId: string; tenantId: string }) =>
      resourceApi.toggleStatus(resourceId, tenantId),
    onSuccess: (response, variables) => {
      // Update cache optimistically
      queryClient.setQueryData(
        resourceKeys.detail(variables.resourceId, variables.tenantId),
        (old: Resource | undefined) =>
          old ? { ...old, is_active: response.is_active } : old
      );
      // Invalidate list to reflect change
      queryClient.invalidateQueries({
        queryKey: resourceKeys.lists(),
      });
      onSuccess?.(response);
    },
    onError: (error: Error) => {
      onError?.(error);
    },
  });
}
```

From product update with cache sync:

```typescript
// features/products/hooks/useProducts.ts

export function useUpdateProduct() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({
      productId,
      tenantId,
      request,
    }: {
      productId: string;
      tenantId: string;
      request: ProductUpdateRequest;
    }) => productsService.updateProduct(productId, tenantId, request),
    onSuccess: (product, variables) => {
      // Update the product in cache
      queryClient.setQueryData(
        productKeys.detail(variables.productId, variables.tenantId),
        product
      );
      // Invalidate list queries
      queryClient.invalidateQueries({
        queryKey: productKeys.list(variables.tenantId),
      });
      // Also invalidate selection queries
      queryClient.invalidateQueries({
        queryKey: productKeys.forSelection(variables.tenantId),
      });
    },
  });
}
```

From spec refresh with cache update:

```typescript
// features/resources/hooks/useResourceMutations.ts

export function useRefreshResourceSpec(options: UseRefreshResourceSpecOptions = {}) {
  const { onSuccess, onError } = options;
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ resourceId, tenantId }: { resourceId: string; tenantId: string }) =>
      resourceApi.refreshResourceSpec(resourceId, tenantId),
    onSuccess: (response, variables) => {
      // Update the resource in cache with new spec
      queryClient.setQueryData(
        resourceKeys.detail(variables.resourceId, variables.tenantId),
        (old: ResourceWithUsage | undefined) =>
          old
            ? {
                ...old,
                resource_spec: response.resource_spec,
                consistency_prompt: response.consistency_prompt,
                resource_spec_generated_at: response.generated_at,
              }
            : undefined
      );
      // Also invalidate list queries to update the grid
      queryClient.invalidateQueries({
        queryKey: resourceKeys.lists(),
      });
      onSuccess?.(response);
    },
    onError: (error: Error) => {
      onError?.(error);
    },
  });
}
```

## Optimistic Update with Usage Tracking

From template application hook:

```typescript
// features/templates/hooks/useCTATemplates.ts

export function useApplyTemplate(tenantId: string) {
  const queryClient = useQueryClient();

  const apply = useCallback(
    (template: CTATemplate): CTAFrame => {
      // Optimistically update the cache to reflect incremented usage
      queryClient.setQueryData<CTATemplate[]>(
        ctaTemplateKeys.list(tenantId),
        (old) =>
          old?.map((t) =>
            t.id === template.id
              ? {
                  ...t,
                  usage_count: t.usage_count + 1,
                  last_used_at: new Date().toISOString(),
                }
              : t
          )
      );
      return template.config;
    },
    [tenantId, queryClient]
  );

  return { apply };
}
```

## Polling with Terminal State Detection

From bulk upload status hook:

```typescript
// features/products/hooks/useProducts.ts

export function useBulkUploadStatus(
  jobId: string | null,
  tenantId: string | null,
  options?: {
    enabled?: boolean;
    pollingInterval?: number;
    onComplete?: (status: BulkUploadStatusResponse) => void;
    onError?: (status: BulkUploadStatusResponse) => void;
  }
) {
  const {
    enabled = true,
    pollingInterval = 2000,
    onComplete,
    onError,
  } = options ?? {};

  const [shouldPoll, setShouldPoll] = useState(true);
  const queryClient = useQueryClient();

  // Use refs for callbacks to avoid useEffect re-runs
  const onCompleteRef = useRef(onComplete);
  const onErrorRef = useRef(onError);
  const calledCallbackForRef = useRef<string | null>(null);

  // Keep refs updated
  useEffect(() => {
    onCompleteRef.current = onComplete;
    onErrorRef.current = onError;
  });

  // Reset callback tracking when jobId changes
  useEffect(() => {
    calledCallbackForRef.current = null;
    setShouldPoll(true);
  }, [jobId]);

  const query = useQuery({
    queryKey: productKeys.bulkUploadStatus(jobId ?? '', tenantId ?? ''),
    queryFn: () => productsService.getBulkUploadStatus(jobId!, tenantId!),
    enabled: Boolean(jobId) && Boolean(tenantId) && enabled,
    refetchInterval: shouldPoll ? pollingInterval : false,
    staleTime: 0,
  });

  // Handle terminal states and callbacks
  useEffect(() => {
    if (query.data) {
      const status = query.data.status;
      const isTerminal = status === 'completed' || status === 'failed';

      if (isTerminal) {
        setShouldPoll(false);

        const callbackKey = `${jobId}:${status}`;
        if (calledCallbackForRef.current !== callbackKey) {
          calledCallbackForRef.current = callbackKey;

          if (status === 'completed' && onCompleteRef.current) {
            onCompleteRef.current(query.data);
            // Invalidate product lists after successful upload
            if (tenantId) {
              queryClient.invalidateQueries({
                queryKey: productKeys.list(tenantId),
              });
              queryClient.invalidateQueries({
                queryKey: productKeys.forSelection(tenantId),
              });
            }
          } else if (status === 'failed' && onErrorRef.current) {
            onErrorRef.current(query.data);
          }
        }
      }
    }
  }, [query.data, jobId, tenantId, queryClient]);

  const stopPolling = useCallback(() => {
    setShouldPoll(false);
  }, []);

  const startPolling = useCallback(() => {
    setShouldPoll(true);
  }, []);

  return {
    ...query,
    status: query.data,
    isPolling: shouldPoll,
    stopPolling,
    startPolling,
    isCompleted: query.data?.status === 'completed',
    isFailed: query.data?.status === 'failed',
    isProcessing: query.data?.status === 'processing' || query.data?.status === 'pending',
  };
}
```

## File Organization

Typical structure from production frontends:

```
frontend/src/
├── main.tsx                          # QueryClient config and provider setup
├── features/
│   ├── products/
│   │   ├── api/
│   │   │   └── productsApi.ts        # API client functions
│   │   ├── hooks/
│   │   │   ├── useProducts.ts        # Query hooks + key factory
│   │   │   └── useProductMutations.ts # Mutation hooks
│   │   └── components/
│   │       └── ProductList.tsx       # Components using hooks
│   └── templates/
│       ├── api/
│       │   └── ctaTemplates.ts
│       └── hooks/
│           └── useCTATemplates.ts
└── types/
    └── index.ts                      # Shared TypeScript types
```

Key conventions:

- `main.tsx` sets up global QueryClient
- Each feature has `api/` (typed API clients) and `hooks/` (query/mutation hooks)
- Query-key factory exports from the same file as primary query hook
- Mutation hooks in separate file to avoid circular imports
- Types shared across features live in top-level `types/`
