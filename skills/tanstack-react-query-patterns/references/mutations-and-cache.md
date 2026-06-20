# Mutations and Cache Management

## Mutation Hook Pattern

Production codebases separate mutation hooks by action (create, update, delete, toggle) rather than using one monolithic mutation hook.

### Create Mutation

```typescript
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
      // Invalidate all list queries to show the new item
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
```

**Key points:**

- Typed `options` interface for user callbacks
- `queryClient.invalidateQueries` targets `lists()` level to refetch all list queries
- User `onSuccess` callback fires after cache invalidation
- `onError` callback provides error handling extension point

### Update Mutation

```typescript
export function useUpdateItem(options: UseUpdateItemOptions = {}) {
  const { onSuccess, onError } = options;
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: ItemUpdateRequest }) =>
      itemsApi.update(id, data),
    onSuccess: (item, variables) => {
      // Update the detail in cache immediately
      queryClient.setQueryData(itemKeys.detail(variables.id), item);
      // Invalidate list queries to reflect change
      queryClient.invalidateQueries({
        queryKey: itemKeys.lists(),
      });
      onSuccess?.(item);
    },
    onError,
  });
}
```

**Pattern:**

1. `setQueryData` updates the detail cache with server response
2. `invalidateQueries` refetches lists to show updated item
3. `variables` from `onSuccess` callback provides mutation args for cache key construction

### Delete Mutation

```typescript
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
      // Invalidate lists to remove from grid
      queryClient.invalidateQueries({
        queryKey: itemKeys.lists(),
      });
      onSuccess?.();
    },
    onError,
  });
}
```

**Use `removeQueries` for deletions:**

- `invalidateQueries` marks as stale and refetches
- `removeQueries` evicts from cache entirely
- After deletion, detail query should not exist in cache

## Optimistic Updates

For instant UI feedback before server confirmation:

### Simple Optimistic Update (Toggle)

```typescript
export function useToggleItemStatus(options: UseToggleItemStatusOptions = {}) {
  const { onSuccess, onError } = options;
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ id }: { id: string }) => itemsApi.toggleStatus(id),
    onSuccess: (response, variables) => {
      // Update cache with server response
      queryClient.setQueryData(
        itemKeys.detail(variables.id),
        (old: Item | undefined) =>
          old ? { ...old, is_active: response.is_active } : old
      );
      // Invalidate lists
      queryClient.invalidateQueries({
        queryKey: itemKeys.lists(),
      });
      onSuccess?.(response);
    },
    onError,
  });
}
```

**Simple pattern:**

- Update cache in `onSuccess` after server confirms
- Use updater function `(old) => old ? { ...old, field: newValue } : old` to preserve other fields
- Check `old` exists before spreading to avoid errors

### True Optimistic Update with Rollback

For immediate UI update before API call completes:

```typescript
export function useToggleItemStatus(options: UseToggleItemStatusOptions = {}) {
  const { onSuccess, onError } = options;
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ id }: { id: string }) => itemsApi.toggleStatus(id),
    onMutate: async (variables) => {
      // Cancel outgoing refetches
      await queryClient.cancelQueries({ queryKey: itemKeys.detail(variables.id) });

      // Snapshot current value
      const previousItem = queryClient.getQueryData<Item>(itemKeys.detail(variables.id));

      // Optimistically update cache
      queryClient.setQueryData(
        itemKeys.detail(variables.id),
        (old: Item | undefined) =>
          old ? { ...old, is_active: !old.is_active } : old
      );

      // Return context for rollback
      return { previousItem };
    },
    onSuccess: (response, variables) => {
      // Update with server response
      queryClient.setQueryData(
        itemKeys.detail(variables.id),
        (old: Item | undefined) =>
          old ? { ...old, is_active: response.is_active } : old
      );
      // Invalidate lists
      queryClient.invalidateQueries({ queryKey: itemKeys.lists() });
      onSuccess?.(response);
    },
    onError: (error, variables, context) => {
      // Rollback on error
      if (context?.previousItem) {
        queryClient.setQueryData(itemKeys.detail(variables.id), context.previousItem);
      }
      onError?.(error);
    },
  });
}
```

**Optimistic update steps:**

1. **`onMutate`**: cancel in-flight queries, snapshot current data, optimistically update cache, return context
2. **`onSuccess`**: reconcile with server response, invalidate related queries
3. **`onError`**: restore snapshot from context

### Optimistic Update with Multiple Entities

```typescript
export function useApplyTemplate(options: UseApplyTemplateOptions = {}) {
  const { onSuccess } = options;
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ templateId }: { templateId: string }) =>
      templatesApi.apply(templateId),
    onMutate: async (variables) => {
      // Cancel outgoing queries
      await queryClient.cancelQueries({ queryKey: templateKeys.lists() });

      // Snapshot list
      const previousTemplates = queryClient.getQueryData<Template[]>(
        templateKeys.list()
      );

      // Optimistically increment usage_count
      queryClient.setQueryData<Template[]>(
        templateKeys.list(),
        (old) =>
          old?.map((t) =>
            t.id === variables.templateId
              ? { ...t, usage_count: t.usage_count + 1 }
              : t
          )
      );

      return { previousTemplates };
    },
    onSuccess: (response, variables) => {
      // Invalidate to refetch with server state
      queryClient.invalidateQueries({ queryKey: templateKeys.lists() });
      onSuccess?.(response);
    },
    onError: (error, variables, context) => {
      if (context?.previousTemplates) {
        queryClient.setQueryData(templateKeys.list(), context.previousTemplates);
      }
    },
  });
}
```

**Multi-entity pattern:**

- Snapshot entire list in `onMutate`
- Update specific item(s) in the list
- Restore full list on error

## Cache Invalidation Strategies

### Targeted Invalidation

```typescript
// Invalidate all list queries (all filter combinations)
queryClient.invalidateQueries({ queryKey: itemKeys.lists() });

// Invalidate specific filtered list
queryClient.invalidateQueries({ queryKey: itemKeys.list({ status: 'active' }) });

// Invalidate single detail
queryClient.invalidateQueries({ queryKey: itemKeys.detail(id) });

// Invalidate all queries for a domain
queryClient.invalidateQueries({ queryKey: itemKeys.all });
```

**Best practice:** Use the most specific key possible. `itemKeys.lists()` is better than `itemKeys.all` if you only changed list data.

### Invalidation vs SetQueryData

- **`invalidateQueries`**: marks queries as stale, triggers refetch if query is active
- **`setQueryData`**: updates cache directly without refetch
- **Pattern**: use `setQueryData` for optimistic updates or when server returns full new state, then `invalidateQueries` for related queries

Example:

```typescript
onSuccess: (item, variables) => {
  // Update detail with server response (no refetch needed)
  queryClient.setQueryData(itemKeys.detail(variables.id), item);
  // Invalidate lists to refetch (server might have computed fields)
  queryClient.invalidateQueries({ queryKey: itemKeys.lists() });
}
```

## Polling Queries

For async job status or real-time updates:

```typescript
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
    staleTime: 0, // Always fresh
  });

  // Detect terminal states
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

**Polling pattern details:**

1. **`refetchInterval`**: set to `pollingInterval` when polling, `false` when stopped
2. **`staleTime: 0`**: force fresh fetch every interval (default staleTime would skip refetch)
3. **Callback refs**: store `onComplete`/`onError` in refs, update in `useEffect` to avoid stale closures
4. **Callback tracking**: use `calledCallbackForRef` to ensure callbacks fire exactly once per terminal state
5. **Reset on jobId change**: clear tracking ref and restart polling when job changes
6. **Manual controls**: expose `stopPolling` and `startPolling` for user control

## Bulk Upload with Status Polling

Common pattern for CSV/file upload jobs:

```typescript
export function useBulkUpload() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ file }: { file: File }) => itemsApi.bulkUpload(file),
    onSuccess: () => {
      // Don't invalidate immediately; wait for job completion
      // Job polling hook will invalidate after job completes
    },
  });
}

export function useBulkUploadStatus(
  jobId: string | null,
  options?: {
    onComplete?: (status: BulkUploadStatus) => void;
  }
) {
  const { onComplete } = options ?? {};
  const queryClient = useQueryClient();

  const query = useJobStatus(jobId, {
    pollingInterval: 2000,
    onComplete: (job) => {
      // Invalidate items after successful upload
      queryClient.invalidateQueries({ queryKey: itemKeys.lists() });
      onComplete?.(job);
    },
  });

  return query;
}
```

**Component usage:**

```tsx
function BulkUploadDialog() {
  const [jobId, setJobId] = useState<string | null>(null);
  const bulkUpload = useBulkUpload();
  const { status, isCompleted, isFailed } = useBulkUploadStatus(jobId, {
    onComplete: () => toast.success('Upload complete'),
  });

  const handleUpload = async (file: File) => {
    const job = await bulkUpload.mutateAsync({ file });
    setJobId(job.job_id);
  };

  return (
    <>
      <FileInput onChange={handleUpload} disabled={Boolean(jobId)} />
      {jobId && (
        <ProgressBar
          value={status?.progress ?? 0}
          status={status?.status}
        />
      )}
    </>
  );
}
```

## QueryClient Global Config

Set defaults in `main.tsx`:

```typescript
function shouldRetry(failureCount: number, error: unknown): boolean {
  if (failureCount >= 3) return false;

  // Check for HTTP errors
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
      gcTime: 30 * 60 * 1000,         // 30 minutes (v5: formerly cacheTime)
      retry: shouldRetry,
      refetchOnWindowFocus: true,
    },
    mutations: {
      retry: shouldRetry,
    },
  },
});
```

**Config notes:**

- **`staleTime`**: how long data is considered fresh; queries won't refetch during this window
- **`gcTime`**: how long inactive query data stays in cache before garbage collection (v5 renamed from `cacheTime`)
- **`retry`**: custom function or number; `false` disables retries, `shouldRetry` function provides granular control
- **`refetchOnWindowFocus`**: refetch when user returns to tab; set `false` for polling queries to avoid double-fetch

Individual queries can override global defaults:

```typescript
useQuery({
  queryKey: itemKeys.detail(id),
  queryFn: () => itemsApi.get(id),
  staleTime: 60000, // Override global 5min with 1min
  retry: false,     // Never retry this query
});
```
