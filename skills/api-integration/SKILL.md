---
name: api-integration
description: Integrate APIs with proper caching, error handling, type safety, and loading states using the project's data-fetching patterns.
argument-hint: [API endpoint or feature name]
disable-model-invocation: true
---

Integrate API for: $ARGUMENTS.

## Steps

1. **Identify the API**: Determine the endpoint(s), HTTP method(s), request/response shapes, and authentication requirements for $ARGUMENTS.

2. **Define types**: Create typed interfaces for request and response payloads. Co-locate types with the API client module according to the project's conventions.

   ```typescript
   // TypeScript example
   export interface GetItemsParams {
     page: number;
     limit: number;
     status?: 'open' | 'resolved' | 'escalated';
   }

   export interface ItemResponse {
     data: Item[];
     total: number;
     page: number;
   }
   ```

   ```python
   # Python example (Pydantic)
   from pydantic import BaseModel

   class GetItemsParams(BaseModel):
       page: int
       limit: int
       status: str | None = None

   class ItemResponse(BaseModel):
       data: list[Item]
       total: int
       page: int
   ```

3. **Create API client functions**: Place in the project's designated API layer as pure async functions. Use the project's HTTP client.

   ```typescript
   // TypeScript example
   import { httpClient } from '@/lib/httpClient';
   import type { GetItemsParams, ItemResponse } from './types/items';

   export async function getItems(params: GetItemsParams): Promise<ItemResponse> {
     const { data } = await httpClient.get<ItemResponse>('/items', { params });
     return data;
   }

   export async function resolveItem(id: string, resolution: string): Promise<void> {
     await httpClient.post(`/items/${encodeURIComponent(id)}/resolve`, { resolution });
   }
   ```

   ```python
   # Python example (httpx)
   import httpx
   from .schemas import GetItemsParams, ItemResponse

   async def get_items(params: GetItemsParams) -> ItemResponse:
       async with httpx.AsyncClient() as client:
           response = await client.get('/items', params=params.model_dump())
           return ItemResponse.model_validate(response.json())

   async def resolve_item(id: str, resolution: str) -> None:
       async with httpx.AsyncClient() as client:
           await client.post(f'/items/{id}/resolve', json={'resolution': resolution})
   ```

4. **Create data-fetching hooks/functions**: Wrap API calls with the project's caching/state management layer.

   ### Query Pattern (React Query example)
   ```typescript
   import { useQuery } from '@tanstack/react-query';
   import { getItems } from '@/api/items';
   import type { GetItemsParams } from '@/api/types/items';

   export const itemKeys = {
     all: ['items'] as const,
     lists: () => [...itemKeys.all, 'list'] as const,
     list: (params: GetItemsParams) => [...itemKeys.lists(), params] as const,
     details: () => [...itemKeys.all, 'detail'] as const,
     detail: (id: string) => [...itemKeys.details(), id] as const,
   };

   export function useItems(params: GetItemsParams) {
     return useQuery({
       queryKey: itemKeys.list(params),
       queryFn: () => getItems(params),
       staleTime: 5 * 60 * 1000, // 5 minutes
       placeholderData: keepPreviousData,
     });
   }
   ```

   ### Mutation Pattern (React Query example)
   ```typescript
   import { useMutation, useQueryClient } from '@tanstack/react-query';
   import { resolveItem } from '@/api/items';

   export function useResolveItem() {
     const queryClient = useQueryClient();

     return useMutation({
       mutationFn: ({ id, resolution }: { id: string; resolution: string }) =>
         resolveItem(id, resolution),
       onSuccess: () => {
         queryClient.invalidateQueries({ queryKey: itemKeys.all });
       },
     });
   }
   ```

   ### Alternative: Service Layer Pattern (backend or Vue/Angular)
   ```python
   # Python service layer
   from .repository import ItemRepository
   from .schemas import GetItemsParams, ItemResponse

   class ItemService:
       def __init__(self, repo: ItemRepository):
           self.repo = repo

       async def get_items(self, params: GetItemsParams) -> ItemResponse:
           items = await self.repo.find_all(params)
           total = await self.repo.count(params)
           return ItemResponse(data=items, total=total, page=params.page)
   ```

5. **Validate responses at the boundary**: Use a validation library to ensure API responses match expected shapes.

   ```typescript
   // TypeScript with Zod
   import { z } from 'zod';

   const itemResponseSchema = z.object({
     data: z.array(itemSchema),
     total: z.number(),
     page: z.number(),
   });

   export async function getItems(params: GetItemsParams) {
     const { data } = await httpClient.get('/items', { params });
     return itemResponseSchema.parse(data);
   }
   ```

   ```python
   # Python with Pydantic (validation built-in)
   from pydantic import BaseModel, field_validator

   class ItemResponse(BaseModel):
       data: list[Item]
       total: int
       page: int

       @field_validator('total')
       @classmethod
       def total_non_negative(cls, v: int) -> int:
           if v < 0:
               raise ValueError('total must be non-negative')
           return v
   ```

6. **Use in components/views**: Follow the loading/empty/error state pattern.

   ```tsx
   // React example
   function ItemList() {
     const { data, isLoading, error } = useItems({ page: 1, limit: 20 });

     if (isLoading) return <Spinner />;
     if (error) return <EmptyState title="Failed to load items" />;
     if (!data?.data.length) return <EmptyState title="No items found" />;

     return (
       <div className="space-y-3">
         {data.data.map((item) => (
           <ItemCard key={item.id} item={item} />
         ))}
       </div>
     );
   }
   ```

   ```python
   # Python (FastAPI) example
   from fastapi import APIRouter, Depends, HTTPException, status

   @router.get('/items', response_model=ItemResponse)
   async def list_items(
       params: GetItemsParams = Depends(),
       service: ItemService = Depends(),
   ) -> ItemResponse:
       try:
           return await service.get_items(params)
       except Exception as e:
           raise HTTPException(
               status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
               detail='Failed to load items'
           )
   ```

7. **Verify**: Run the project's linter, type checker, and build to confirm all checks pass.

## Data-Fetching Conventions

### Cache Key Factory
Every feature should have a key factory object for consistent cache management (applies to client-side caching libraries like TanStack Query, SWR, Apollo):

```typescript
export const featureKeys = {
  all: ['feature'] as const,
  lists: () => [...featureKeys.all, 'list'] as const,
  list: (params: Params) => [...featureKeys.lists(), params] as const,
  details: () => [...featureKeys.all, 'detail'] as const,
  detail: (id: string) => [...featureKeys.details(), id] as const,
};
```

### Stale Time Defaults (Client-Side Caching)
| Data Type | Stale Time | Rationale |
|-----------|-----------|-----------|
| Reference data (categories, roles) | 30 minutes | Rarely changes |
| Dashboard KPIs | 5 minutes | Moderate freshness |
| Real-time feeds (notifications, alerts) | 1 minute | Needs frequent updates |
| User-specific (preferences) | Infinity | Only changes on mutation |

### Error Handling
- Use the data-fetching layer's built-in error state — avoid wrapping in try/catch at the component level
- Global error handler for auth errors (401 → redirect to login)
- Show empty/error state UI for query failures
- Show toast/notification for mutation failures

### Optimistic Updates (Client-Side)
Use for operations where the user expects instant feedback:

```typescript
// TanStack Query example
onMutate: async (newData) => {
  await queryClient.cancelQueries({ queryKey });
  const previous = queryClient.getQueryData(queryKey);
  queryClient.setQueryData(queryKey, (old) => /* optimistic update */);
  return { previous };
},
onError: (_err, _new, context) => {
  queryClient.setQueryData(queryKey, context?.previous);
},
onSettled: () => {
  queryClient.invalidateQueries({ queryKey });
},
```

```python
# Backend optimistic approach (return before commit)
async def update_item(db: AsyncSession, id: str, update: ItemUpdate) -> Item:
    item = await repo.get_by_id(db, id)
    if not item:
        raise HTTPException(status_code=404)
    
    # Apply changes
    for field, value in update.model_dump(exclude_unset=True).items():
        setattr(item, field, value)
    
    # Flush to get updated state, but don't commit yet
    await db.flush()
    await db.refresh(item)
    
    # Return optimistically (commit happens at end of request)
    return item
```

## Directory Structure

Adapt to your project's conventions. Common patterns:

### Frontend (React/Vue/Angular)
```
src/
  lib/
    httpClient.ts                        # Shared HTTP client (Axios/Fetch)
    queryKeys.ts                         # Shared query key factories (if using client-side caching)
  providers/
    QueryProvider.tsx                    # Data-fetching provider (TanStack Query, SWR, Apollo)
  modules/ (or features/)
    <feature>/
      api/<feature>Api.ts                # Plain async API functions
      hooks/use<Feature>Queries.ts       # Data-fetching hooks wrapping API functions
      types/<feature>.ts                 # Request/response types
```

### Backend (Python/Node/Go/etc.)
```
app/
  api/                                   # HTTP route handlers
    v1/
      <feature>/
        router.py (or routes.ts)         # Route definitions
        schemas.py (or dtos.ts)          # Request/response schemas
        service.py (or service.ts)       # Business logic
        repository.py (or repository.ts) # Data access
```

**Key rules:**
- API client functions (plain async) live in the project's designated API layer
- Data-fetching hooks/wrappers live alongside the module or in a dedicated hooks folder
- Key factories can be co-located or centralized depending on the project's conventions
- Validation happens at system boundaries (API responses in frontend, request payloads in backend)

## Common Patterns by Stack

### React + TanStack Query
- Query hooks: `useQuery` for reads, `useMutation` for writes
- Key factories for cache management
- `invalidateQueries` after mutations
- `placeholderData: keepPreviousData` for pagination

### Vue + Pinia
- API functions in composables (`useItems`)
- Pinia store for caching if needed
- Loading/error state in composable return

### Angular + RxJS
- API functions return Observables
- Service layer manages HTTP calls
- `catchError` for error handling
- `shareReplay` for caching

### Backend (FastAPI/Express/Spring Boot)
- Repository pattern for data access
- Service layer for business logic
- Route handlers delegate to services
- Typed request/response schemas

## References

- HTTP client: Check the project's configuration (Axios, Fetch, httpx, requests)
- Data-fetching library: TanStack Query, SWR, Apollo (frontend), or service/repository pattern (backend)
- Validation: Zod, Yup, io-ts (TypeScript), Pydantic (Python), Joi (Node.js)
- Loading/error patterns: Check `code-organization.md` for the project's UI component conventions
