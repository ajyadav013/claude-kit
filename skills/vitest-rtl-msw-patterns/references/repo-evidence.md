# Repo Evidence (Genericized)

**Source:** Multiple production React frontends with Vitest, RTL, MSW, and Zod-Pydantic contract tests.

All paths, service names, and identifiers have been genericized for public distribution.

## Vitest configuration

**File:** `vitest.config.ts`

```typescript
import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
import { resolve } from 'path';

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': resolve(__dirname, './src'),
    },
  },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/test/**/*.test.{ts,tsx}'],
    css: false,
    coverage: {
      provider: 'v8',
      reporter: ['text', 'html', 'lcov', 'json-summary'],
      reportsDirectory: './coverage',
      include: [
        'src/lib/**/*.{ts,tsx}',
        'src/hooks/**/*.{ts,tsx}',
      ],
      exclude: [
        'src/test/**',
        'src/**/*.test.{ts,tsx}',
        'src/**/*.d.ts',
        'src/lib/api.ts',
      ],
      thresholds: {
        lines: 90,
        functions: 90,
        branches: 90,
        statements: 90,
      },
    },
  },
});
```

## Test setup file

**File:** `src/test/setup.ts`

```typescript
import '@testing-library/jest-dom/vitest';
import { vi } from 'vitest';

// Stub window.matchMedia
Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: vi.fn().mockImplementation((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })),
});

// Stub Element.scrollTo (for Radix Tabs, etc.)
if (typeof Element !== 'undefined' && Element.prototype.scrollTo === undefined) {
  Element.prototype.scrollTo = vi.fn() as unknown as Element['scrollTo'];
}
```

## MSW handlers structure

**File:** `src/__tests__/mocks/handlers.ts`

```typescript
import { http, HttpResponse } from 'msw';

const API_BASE = '/api/v1';

export const mockItems = [
  {
    id: 'item-1',
    name: 'Sample Item',
    description: 'Example description',
    status: 'active',
    created_at: '2024-01-15T10:00:00Z',
  },
];

export const handlers = [
  // GET /api/v1/items
  http.get(`${API_BASE}/items`, () => {
    return HttpResponse.json({
      items: mockItems,
      total: mockItems.length,
    });
  }),

  // GET /api/v1/items/:itemId
  http.get(`${API_BASE}/items/:itemId`, ({ params }) => {
    const { itemId } = params;
    if (itemId === 'item-1') {
      return HttpResponse.json(mockItems[0]);
    }
    return HttpResponse.json(
      { detail: 'Item not found', code: 'ITEM_NOT_FOUND' },
      { status: 404 }
    );
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
];

export const errorHandlers = {
  itemsError: http.get(`${API_BASE}/items`, () => {
    return HttpResponse.json(
      { detail: 'Failed to load items', code: 'ITEMS_ERROR' },
      { status: 500 }
    );
  }),
};

export default handlers;
```

## MSW server setup

**File:** `src/__tests__/mocks/server.ts`

```typescript
import { setupServer } from 'msw/node';
import { handlers } from './handlers';

export const server = setupServer(...handlers);
export { handlers } from './handlers';
```

## Component test with user interactions

**File:** `src/test/components/ui/ToggleGroup.test.tsx`

```typescript
import * as React from 'react';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect } from 'vitest';
import { ToggleGroup, ToggleGroupItem } from '@/components/ui';

function Harness({ initial = 'card' }: { initial?: string }) {
  const [v, setV] = React.useState(initial);
  return (
    <ToggleGroup value={v} onValueChange={setV} aria-label="View">
      <ToggleGroupItem value="card">Cards</ToggleGroupItem>
      <ToggleGroupItem value="table">Table</ToggleGroupItem>
      <ToggleGroupItem value="kanban">Kanban</ToggleGroupItem>
    </ToggleGroup>
  );
}

describe('ToggleGroup', () => {
  it('renders 3 items and marks initial value as active', () => {
    render(<Harness initial="card" />);
    const cardBtn = screen.getByRole('radio', { name: 'Cards' });
    expect(cardBtn).toHaveAttribute('data-state', 'on');
    expect(screen.getByRole('radio', { name: 'Table' })).toHaveAttribute('data-state', 'off');
  });

  it('switches active item on click', async () => {
    const user = userEvent.setup();
    render(<Harness initial="card" />);
    await user.click(screen.getByRole('radio', { name: 'Table' }));
    expect(screen.getByRole('radio', { name: 'Table' })).toHaveAttribute('data-state', 'on');
    expect(screen.getByRole('radio', { name: 'Cards' })).toHaveAttribute('data-state', 'off');
  });
});
```

## Component test with accessibility queries

**File:** `src/test/components/ui/Avatar.test.tsx`

```typescript
import { render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import { Avatar } from '@/components/ui';

describe('Avatar', () => {
  it('renders explicit initials', () => {
    render(<Avatar initials="BB" name="Bob Brown" />);
    expect(screen.getByText('BB')).toBeInTheDocument();
  });

  it('derives initials from a 2-part name', () => {
    render(<Avatar name="Alice Anderson" />);
    expect(screen.getByText('AA')).toBeInTheDocument();
  });

  it('applies size classes correctly', () => {
    const { rerender, container } = render(<Avatar name="X" size="xs" />);
    expect(container.firstChild).toHaveClass('w-6', 'h-6');
    rerender(<Avatar name="X" size="md" />);
    expect(container.firstChild).toHaveClass('w-10', 'h-10');
  });

  it('exposes accessible name when `name` provided', () => {
    render(<Avatar name="Bob Brown" />);
    expect(screen.getByLabelText('Avatar for Bob Brown')).toBeInTheDocument();
  });
});
```

## Contract test helper: strictDeep

**File:** `src/__tests__/contracts/helpers.ts`

```typescript
import { expect } from 'vitest';
import { z } from 'zod';

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

  return schema;
}

export const isoDatetime = z.string().refine(
  (s) => /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})?$/.test(s),
  { message: 'Invalid ISO datetime' },
);

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
```

## Contract test example

**File:** `src/__tests__/contracts/item-api-contract.test.ts`

```typescript
import { describe, it, expect } from 'vitest';
import { z } from 'zod';
import {
  strictDeep,
  isoDatetime,
  expectRequiredFields,
  expectNullableFields,
  expectOptionalFields,
} from './helpers';

// Import generated fixtures
import itemFull from '../../../contracts/fixtures/item/ItemResponse.full.json';
import itemMinimal from '../../../contracts/fixtures/item/ItemResponse.minimal.json';
import itemMeta from '../../../contracts/fixtures/item/ItemResponse.meta.json';

import itemStatusValues from '../../../contracts/fixtures/enums/ItemStatus.json';

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

    it('rejects unknown fields', () => {
      const result = ItemResponseSchema.safeParse({ ...itemFull, unknown_field: true });
      expect(result.success).toBe(false);
    });
  });
});
```

## Dependencies (package.json excerpt)

```json
{
  "scripts": {
    "test": "vitest",
    "test:run": "vitest run",
    "test:coverage": "vitest run --coverage",
    "test:ui": "vitest --ui"
  },
  "devDependencies": {
    "@testing-library/jest-dom": "^6.6.3",
    "@testing-library/react": "^16.3.0",
    "@testing-library/user-event": "^14.6.1",
    "@vitest/coverage-v8": "^3.2.0",
    "@vitest/ui": "^3.2.0",
    "msw": "^2.10.2",
    "vitest": "^3.2.0"
  }
}
```

## Fixture file structure

```
frontend/
├── contracts/
│   └── fixtures/
│       ├── item/
│       │   ├── ItemResponse.full.json      # All fields populated
│       │   ├── ItemResponse.minimal.json   # Only required fields
│       │   └── ItemResponse.meta.json      # { required_fields: [...], nullable_fields: [...], optional_fields: [...] }
│       └── enums/
│           └── ItemStatus.json              # ["active", "pending", "archived"]
└── src/
    ├── test/
    │   └── setup.ts
    ├── __tests__/
    │   ├── mocks/
    │   │   ├── handlers.ts
    │   │   └── server.ts
    │   └── contracts/
    │       ├── helpers.ts
    │       └── item-api-contract.test.ts
    └── components/
        └── ...
```

## Notes

- All patterns are derived from **multiple production React frontends** with Vitest, RTL, MSW v2, and Zod-Pydantic contract tests
- Service names, internal paths, and identifiers have been genericized
- Contract test fixtures are generated by backend scripts (Python/Pydantic → JSON)
- MSW v2 syntax (`http.get`, `HttpResponse.json`) replaces MSW v1 (`rest.get`, `res(ctx.json())`)
- `strictDeep()` is essential for contract tests — Zod is permissive by default
