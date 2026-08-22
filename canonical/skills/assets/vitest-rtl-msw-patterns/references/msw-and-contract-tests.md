# MSW v2 Request Mocking and Contract Tests

Production patterns for MSW v2 API mocking and Zod-Pydantic contract testing.

## MSW v2 handlers (src/__tests__/mocks/handlers.ts)

```typescript
import { http, HttpResponse } from 'msw';

const API_BASE = '/api/v1';

// Mock data fixtures
export const mockItems = [
  {
    id: 'item-1',
    name: 'Summer Collection',
    description: 'Seasonal products',
    status: 'active',
    created_at: '2024-01-15T10:00:00Z',
  },
  {
    id: 'item-2',
    name: 'Winter Collection',
    description: null,
    status: 'pending',
    created_at: '2024-01-16T10:00:00Z',
  },
];

// Default handlers
export const handlers = [
  // GET /api/v1/items
  http.get(`${API_BASE}/items`, () => {
    return HttpResponse.json({
      items: mockItems,
      total: mockItems.length,
    });
  }),

  // GET /api/v1/items/:id
  http.get(`${API_BASE}/items/:id`, ({ params }) => {
    const { id } = params;
    const item = mockItems.find((i) => i.id === id);
    if (!item) {
      return HttpResponse.json(
        { detail: 'Item not found', code: 'ITEM_NOT_FOUND' },
        { status: 404 }
      );
    }
    return HttpResponse.json(item);
  }),

  // POST /api/v1/items
  http.post(`${API_BASE}/items`, async ({ request }) => {
    const body = await request.json();
    return HttpResponse.json(
      {
        id: 'new-item-id',
        ...body,
        created_at: new Date().toISOString(),
      },
      { status: 201 }
    );
  }),

  // POST /api/v1/items/:id/duplicate
  http.post(`${API_BASE}/items/:id/duplicate`, async ({ request, params }) => {
    const body = await request.json();
    const { id } = params;
    return HttpResponse.json(
      {
        id: 'duplicated-item-id',
        ...body,
        source_id: id,
        created_at: new Date().toISOString(),
      },
      { status: 201 }
    );
  }),

  // POST /api/v1/upload (file upload example)
  http.post(`${API_BASE}/upload`, async () => {
    return HttpResponse.json({
      url: 'https://example.com/uploaded-file.jpg',
      filename: 'uploaded-file.jpg',
    });
  }),
];

// Error handlers for testing failure scenarios
export const errorHandlers = {
  listItemsError: http.get(`${API_BASE}/items`, () => {
    return HttpResponse.json(
      { detail: 'Failed to load items', code: 'LIST_ERROR' },
      { status: 500 }
    );
  }),

  itemNotFound: http.get(`${API_BASE}/items/:id`, () => {
    return HttpResponse.json(
      { detail: 'Item not found', code: 'ITEM_NOT_FOUND' },
      { status: 404 }
    );
  }),

  createItemValidationError: http.post(`${API_BASE}/items`, () => {
    return HttpResponse.json(
      {
        detail: 'Validation failed',
        code: 'VALIDATION_ERROR',
        errors: [
          { field: 'name', message: 'Name is required' },
        ],
      },
      { status: 422 }
    );
  }),
};

export default handlers;
```

**Key patterns:**
- Export mock data fixtures for reuse in tests
- Use route parameters (`:id`) for dynamic responses
- Return 404 for unknown IDs
- Return 201 for successful POST
- Export `errorHandlers` object for testing error scenarios
- Access request body with `await request.json()`

## MSW server setup (src/__tests__/mocks/server.ts)

```typescript
import { setupServer } from 'msw/node';
import { handlers } from './handlers';

export const server = setupServer(...handlers);
export { handlers } from './handlers';
```

**Note:** Do NOT manually call `server.listen()`, `server.resetHandlers()`, or `server.close()` in individual tests. This is handled globally (if needed) or at the Vitest configuration level.

## Using MSW in tests

```typescript
import { render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import { ItemList } from '@/components/ItemList';
import { server } from '@/__tests__/mocks/server';
import { errorHandlers } from '@/__tests__/mocks/handlers';
import { http, HttpResponse } from 'msw';

describe('ItemList', () => {
  it('renders list of items from API', async () => {
    render(<ItemList />);
    expect(await screen.findByText('Summer Collection')).toBeInTheDocument();
    expect(screen.getByText('Winter Collection')).toBeInTheDocument();
  });

  it('shows error message when API fails', async () => {
    // Override default handler with error handler
    server.use(errorHandlers.listItemsError);
    render(<ItemList />);
    expect(await screen.findByText(/failed to load/i)).toBeInTheDocument();
  });

  it('handles 404 when item not found', async () => {
    server.use(errorHandlers.itemNotFound);
    render(<ItemDetail id="unknown-id" />);
    expect(await screen.findByText(/not found/i)).toBeInTheDocument();
  });

  it('shows validation errors on submit', async () => {
    server.use(errorHandlers.createItemValidationError);
    const user = userEvent.setup();
    render(<ItemForm />);
    await user.click(screen.getByRole('button', { name: /submit/i }));
    expect(await screen.findByText('Name is required')).toBeInTheDocument();
  });

  it('creates item with custom payload', async () => {
    // Per-test override for specific response
    server.use(
      http.post('/api/v1/items', async ({ request }) => {
        const body = await request.json();
        return HttpResponse.json(
          { id: 'custom-id', ...body },
          { status: 201 }
        );
      })
    );
    const user = userEvent.setup();
    render(<ItemForm />);
    await user.type(screen.getByLabelText(/name/i), 'Test Item');
    await user.click(screen.getByRole('button', { name: /submit/i }));
    expect(await screen.findByText('Test Item')).toBeInTheDocument();
  });
});
```

**Key patterns:**
- Use `server.use()` to override handlers for specific tests
- Prefer exporting `errorHandlers` object over inline overrides (reusable)
- Use `await screen.findByText()` for async API responses

## Contract testing: strictDeep helper

```typescript
// src/__tests__/contracts/helpers.ts
import { expect } from 'vitest';
import { z } from 'zod';

/**
 * Recursively apply .strict() to all nested z.object schemas.
 * Rejects unknown fields at all levels.
 */
export function strictDeep<T extends z.ZodTypeAny>(schema: T): T {
  if (schema instanceof z.ZodObject) {
    const newShape: Record<string, z.ZodTypeAny> = {};
    for (const [key, value] of Object.entries(schema.shape as Record<string, z.ZodTypeAny>)) {
      newShape[key] = strictDeep(value);
    }
    return z.object(newShape).strict() as unknown as T;
  }

  if (schema instanceof z.ZodArray) {
    return z.array(strictDeep(schema.element as z.ZodTypeAny)) as unknown as T;
  }

  if (schema instanceof z.ZodNullable) {
    return z.nullable(strictDeep(schema.unwrap() as z.ZodTypeAny)) as unknown as T;
  }

  if (schema instanceof z.ZodOptional) {
    return z.optional(strictDeep(schema.unwrap() as z.ZodTypeAny)) as unknown as T;
  }

  if (schema instanceof z.ZodDefault) {
    const inner = strictDeep(schema.unwrap() as z.ZodTypeAny);
    const defaultValue = (schema._def as any).defaultValue as unknown;
    return inner.default(
      typeof defaultValue === 'function' ? (defaultValue as () => unknown)() : defaultValue,
    ) as unknown as T;
  }

  if (schema instanceof z.ZodUnion) {
    const options = (schema.options as z.ZodTypeAny[]).map((opt) => strictDeep(opt));
    return z.union(options as [z.ZodTypeAny, z.ZodTypeAny, ...z.ZodTypeAny[]]) as unknown as T;
  }

  return schema;
}

/** Validates ISO 8601 datetime strings (with or without timezone). */
export const isoDatetime = z.string().refine(
  (s) => /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})?$/.test(s),
  { message: 'Invalid ISO datetime' },
);

// Metadata validation helpers
export function expectRequiredFields(
  schema: z.ZodObject<z.ZodRawShape>,
  metadata: { required_fields: string[] },
): void {
  for (const field of metadata.required_fields) {
    const fieldSchema = schema.shape[field] as z.ZodTypeAny | undefined;
    expect(fieldSchema).toBeDefined();
    expect(fieldSchema!.isOptional()).toBe(false);
  }
}

export function expectNullableFields(
  schema: z.ZodObject<z.ZodRawShape>,
  metadata: { nullable_fields: string[] },
): void {
  for (const field of metadata.nullable_fields) {
    const fieldSchema = schema.shape[field] as z.ZodTypeAny | undefined;
    expect(fieldSchema).toBeDefined();
    expect(fieldSchema!.isNullable()).toBe(true);
  }
}

export function expectOptionalFields(
  schema: z.ZodObject<z.ZodRawShape>,
  metadata: { optional_fields: string[] },
): void {
  for (const field of metadata.optional_fields) {
    const fieldSchema = schema.shape[field] as z.ZodTypeAny | undefined;
    expect(fieldSchema).toBeDefined();
    expect(fieldSchema!.isOptional()).toBe(true);
  }
}
```

**Why strictDeep:**
- Zod objects are **permissive by default** — they accept unknown fields
- `strictDeep()` recursively applies `.strict()` to reject unknown fields
- Ensures frontend schemas **exactly match** backend Pydantic models

## Contract test example

```typescript
// src/__tests__/contracts/item-api-contract.test.ts
import { describe, it, expect } from 'vitest';
import { z } from 'zod';
import {
  strictDeep,
  isoDatetime,
  expectRequiredFields,
  expectNullableFields,
  expectOptionalFields,
} from './helpers';

// Import generated fixtures (backend generates these from Pydantic models)
import itemFull from '../../../contracts/fixtures/item/ItemResponse.full.json';
import itemMinimal from '../../../contracts/fixtures/item/ItemResponse.minimal.json';
import itemMeta from '../../../contracts/fixtures/item/ItemResponse.meta.json';

import itemStatusValues from '../../../contracts/fixtures/enums/ItemStatus.json';

// Define Zod schema mirroring backend Pydantic model
const ItemStatusEnum = z.enum(itemStatusValues as [string, ...string[]]);

const ItemResponseSchema = strictDeep(
  z.object({
    id: z.string(),
    name: z.string(),
    description: z.string().nullable(),
    status: ItemStatusEnum,
    tags: z.array(z.string()),
    created_at: isoDatetime,
    updated_at: isoDatetime.nullable(),
  }),
);

describe('Item API Contract', () => {
  describe('ItemResponse', () => {
    it('validates full fixture', () => {
      const result = ItemResponseSchema.safeParse(itemFull);
      expect(result.success).toBe(true);
      if (!result.success) console.error(result.error.format());
    });

    it('validates minimal fixture', () => {
      const result = ItemResponseSchema.safeParse(itemMinimal);
      expect(result.success).toBe(true);
      if (!result.success) console.error(result.error.format());
    });

    it('validates metadata - required fields', () => {
      expectRequiredFields(ItemResponseSchema, itemMeta);
    });

    it('validates metadata - nullable fields', () => {
      expectNullableFields(ItemResponseSchema, itemMeta);
    });

    it('validates metadata - optional fields', () => {
      expectOptionalFields(ItemResponseSchema, itemMeta);
    });

    it('rejects unknown fields', () => {
      const result = ItemResponseSchema.safeParse({ ...itemFull, unknown_field: true });
      expect(result.success).toBe(false);
    });
  });
});
```

## Backend fixture generation (Python)

```python
# backend/scripts/generate_fixtures.py
"""Generate JSON fixtures for frontend contract tests."""

import json
from pathlib import Path
from typing import Any, Dict, List
from pydantic import BaseModel
from app.schemas.item import ItemResponse, ItemStatus

def get_full_fixture(model: type[BaseModel]) -> Dict[str, Any]:
    """Generate fixture with all fields populated."""
    # Implement based on model fields
    pass

def get_minimal_fixture(model: type[BaseModel]) -> Dict[str, Any]:
    """Generate fixture with only required fields."""
    pass

def get_metadata(model: type[BaseModel]) -> Dict[str, List[str]]:
    """Extract required/nullable/optional field lists."""
    return {
        "required_fields": [...],
        "nullable_fields": [...],
        "optional_fields": [...],
    }

def generate_fixtures():
    output_dir = Path("../frontend/contracts/fixtures")
    output_dir.mkdir(exist_ok=True)

    # Generate ItemResponse fixtures
    item_dir = output_dir / "item"
    item_dir.mkdir(exist_ok=True)
    
    with open(item_dir / "ItemResponse.full.json", "w") as f:
        json.dump(get_full_fixture(ItemResponse), f, indent=2)
    
    with open(item_dir / "ItemResponse.minimal.json", "w") as f:
        json.dump(get_minimal_fixture(ItemResponse), f, indent=2)
    
    with open(item_dir / "ItemResponse.meta.json", "w") as f:
        json.dump(get_metadata(ItemResponse), f, indent=2)

    # Generate enum fixtures
    enum_dir = output_dir / "enums"
    enum_dir.mkdir(exist_ok=True)
    
    with open(enum_dir / "ItemStatus.json", "w") as f:
        json.dump([e.value for e in ItemStatus], f, indent=2)
```

## Fixture file structure

```
frontend/
├── contracts/
│   └── fixtures/
│       ├── item/
│       │   ├── ItemResponse.full.json      # All fields populated
│       │   ├── ItemResponse.minimal.json   # Only required fields
│       │   └── ItemResponse.meta.json      # Field metadata
│       ├── item-list/
│       │   ├── ItemListResponse.full.json
│       │   ├── ItemListResponse.minimal.json
│       │   └── ItemListResponse.meta.json
│       └── enums/
│           └── ItemStatus.json              # ["active", "pending", "archived"]
└── src/
    └── __tests__/
        └── contracts/
            ├── helpers.ts
            └── item-api-contract.test.ts
```

## Why contract tests

1. **Frontend-backend schema drift detection** — backend changes a field from optional to required, contract tests fail immediately
2. **Type-safe API contracts** — Zod schemas used for runtime validation AND TypeScript types
3. **Enum synchronization** — backend enum changes are automatically caught
4. **Nullable vs. optional clarity** — metadata tests ensure frontend handles null values correctly
5. **Unknown field rejection** — `strictDeep()` catches backend adding unexpected fields

## Example contract test failure

```typescript
// Backend adds a new required field "priority: int"
// Frontend Zod schema does not include it

it('validates full fixture', () => {
  const result = ItemResponseSchema.safeParse(itemFull);
  expect(result.success).toBe(true);
  if (!result.success) console.error(result.error.format());
});

// Test fails with:
// {
//   "priority": {
//     "_errors": ["Required"]
//   }
// }
```

This forces frontend to update the Zod schema and handle the new field.
