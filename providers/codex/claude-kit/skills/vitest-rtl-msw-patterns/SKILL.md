---
name: vitest-rtl-msw-patterns
description: Frontend testing with Vitest, React Testing Library, MSW v2, plus contract tests where Zod schemas mirror backend Pydantic models. Use for test infra setup, component tests, or mocking API requests.
---

Standardize frontend testing with Vitest runner, React Testing Library, MSW v2 request mocking, and Zod-Pydantic contract testing.

## When to use

- Setting up Vitest configuration and test infrastructure for a React frontend
- Writing component tests with render, screen queries, and user interactions
- Mocking API requests with MSW v2 (setupServer, http.get/post, HttpResponse)
- Creating contract tests to validate frontend Zod schemas match backend Pydantic models
- Overriding mock handlers in specific tests using server.use()
- Setting up test coverage with @vitest/coverage-v8
- Configuring jsdom environment and global test setup (matchMedia, IntersectionObserver stubs)
- Generating and validating against fixture files (full/minimal/meta) for contract tests
- Testing error scenarios by replacing success handlers with error handlers
- Ensuring type-safe API contracts between frontend and backend

## Core conventions

1. **Vitest configuration in `vitest.config.ts`**: use `defineConfig()` from `vitest/config` with `@vitejs/plugin-react`, set `test.globals: true`, `test.environment: 'jsdom'`, `test.setupFiles: ['./src/test/setup.ts']`, include path like `src/test/**/*.test.{ts,tsx}`, coverage provider `v8` with reporters `['text', 'html', 'lcov', 'json-summary']`, and coverage thresholds (90% lines/functions/branches/statements). Set `test.css: false` to skip CSS parsing in tests.

2. **Test setup file at `src/test/setup.ts`**: import `@testing-library/jest-dom/vitest` for matchers, import `cleanup` and call in `afterEach()`, stub browser APIs missing from jsdom (`window.matchMedia`, `IntersectionObserver`, `ResizeObserver`, `Element.prototype.scrollIntoView`, `Element.prototype.scrollTo`, `localStorage`, `sessionStorage`, `URL.createObjectURL`), and reset mocks with `vi.clearAllMocks()` in `afterEach()`.

3. **MSW handlers in `src/__tests__/mocks/handlers.ts`**: export default array of handlers using `http.get()`, `http.post()`, etc., define `API_BASE` constant for base path, use route parameters like `:briefId`, return `HttpResponse.json()` with mock data, support conditional responses (404 for unknown IDs), export mock data fixtures, and optionally export `errorHandlers` object mapping scenario names to error-response handlers for testing failure paths.

4. **MSW server in `src/__tests__/mocks/server.ts`**: import `setupServer` from `msw/node`, import handlers, export `export const server = setupServer(...handlers)`, and re-export handlers for convenience.

5. **MSW lifecycle integration**: do NOT manually call server.listen/resetHandlers/close in individual tests. This is handled at the Vitest configuration level or in a global setup file when needed. For per-test handler overrides, use `server.use(http.get('/api/path', () => HttpResponse.json({...})))` before the action.

6. **React Testing Library patterns**: import `{ render, screen }` from `@testing-library/react`, import `userEvent` from `@testing-library/user-event`, use `const user = userEvent.setup()` at the start of async interaction tests, prefer `screen.getByRole()` over getByTestId for accessibility, use `await user.click()` / `await user.type()` for interactions, wrap components requiring context/router in a test harness function, and use `rerender()` for prop update tests.

7. **Queries and assertions**: prefer role-based queries (`getByRole('button', { name: 'Submit' })`) over test IDs, use `queryBy*` when asserting absence (`expect(screen.queryByText('Gone')).not.toBeInTheDocument()`), use `findBy*` for async appearance (`await screen.findByText('Loaded')`), and rely on jest-dom matchers (`toBeInTheDocument()`, `toHaveClass()`, `toHaveAttribute()`, `toBeDisabled()`, etc.).

8. **Component test structure**: define test harnesses for stateful components (encapsulate state + component in a wrapper function), group tests by feature using `describe()`, test initial render state, test user interactions, test error states, and test accessibility (aria labels, role attributes).

9. **Contract tests in `src/__tests__/contracts/*.test.ts`**: create Zod schemas mirroring backend Pydantic models using `strictDeep()` helper (rejects unknown fields), import generated fixtures from `contracts/fixtures/<domain>/<ModelName>.{full,minimal,meta}.json`, import enum values from `contracts/fixtures/enums/<EnumName>.json`, validate full/minimal fixtures with `schema.safeParse()`, validate metadata with `expectRequiredFields()`, `expectNullableFields()`, `expectOptionalFields()`, and test unknown field rejection.

10. **strictDeep() helper in `src/__tests__/contracts/helpers.ts`**: recursively apply `.strict()` to all nested `z.object()` schemas to reject unknown fields, handle `z.array()`, `z.nullable()`, `z.optional()`, `z.default()`, `z.union()`, and `z.discriminatedUnion()`, export `isoDatetime` validator for ISO 8601 strings, export metadata assertion helpers (`expectRequiredFields`, `expectNullableFields`, `expectOptionalFields`) that introspect Zod schema and verify field optionality/nullability matches metadata.

11. **Fixture-driven contract tests**: backend generates three fixture files per Pydantic model—`*.full.json` (all fields populated), `*.minimal.json` (only required fields), `*.meta.json` (metadata listing `required_fields`, `nullable_fields`, `optional_fields`)—frontend imports these as JSON modules and validates them against Zod schemas. Enums are exported as JSON arrays and converted to `z.enum()`.

12. **Test scripts in `package.json`**: `"test": "vitest"` (watch mode), `"test:run": "vitest run"` (CI), `"test:coverage": "vitest run --coverage"` (coverage report), `"test:ui": "vitest --ui"` (visual test runner).

13. **MSW v2 API**: use `http.get()`, `http.post()`, etc., from `msw`, return `HttpResponse.json(data, { status: 200 })`, access route params via `{ params }` in handler, access request body via `await request.json()`, and use `setupServer` from `msw/node` (not `msw` or `msw/browser`).

14. **All async interactions must await**: `await user.click()`, `await user.type()`, `await screen.findByText()`. Missing awaits cause flaky tests and false positives.

15. **Coverage exclusions**: exclude test files (`src/test/**`, `src/**/*.test.{ts,tsx}`), type definitions (`src/**/*.d.ts`), and any files that cannot be tested in isolation (e.g., top-level API client with side effects, specific components requiring full environment).

## Skeleton / example

```typescript
// vitest.config.ts
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
        'src/components/**/*.{ts,tsx}',
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

```typescript
// src/test/setup.ts
import '@testing-library/jest-dom/vitest';
import { cleanup } from '@testing-library/react';
import { afterEach, vi } from 'vitest';

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

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

// Stub IntersectionObserver
const mockIntersectionObserver = vi.fn();
mockIntersectionObserver.mockReturnValue({
  observe: () => null,
  unobserve: () => null,
  disconnect: () => null,
});
window.IntersectionObserver = mockIntersectionObserver;

// Stub ResizeObserver
const mockResizeObserver = vi.fn();
mockResizeObserver.mockReturnValue({
  observe: () => null,
  unobserve: () => null,
  disconnect: () => null,
});
window.ResizeObserver = mockResizeObserver;

// Stub localStorage
const localStorageMock = (() => {
  let store: Record<string, string> = {};
  return {
    getItem: (key: string) => store[key] || null,
    setItem: (key: string, value: string) => {
      store[key] = value.toString();
    },
    removeItem: (key: string) => {
      delete store[key];
    },
    clear: () => {
      store = {};
    },
  };
})();
Object.defineProperty(window, 'localStorage', {
  value: localStorageMock,
});
```

```typescript
// src/__tests__/mocks/handlers.ts
import { http, HttpResponse } from 'msw';

const API_BASE = '/api/v1';

export const mockItems = [
  { id: '1', name: 'Item One', status: 'active' },
  { id: '2', name: 'Item Two', status: 'pending' },
];

export const handlers = [
  http.get(`${API_BASE}/items`, () => {
    return HttpResponse.json({
      items: mockItems,
      total: mockItems.length,
    });
  }),

  http.get(`${API_BASE}/items/:id`, ({ params }) => {
    const { id } = params;
    const item = mockItems.find((i) => i.id === id);
    if (!item) {
      return HttpResponse.json(
        { detail: 'Not found', code: 'ITEM_NOT_FOUND' },
        { status: 404 }
      );
    }
    return HttpResponse.json(item);
  }),

  http.post(`${API_BASE}/items`, async ({ request }) => {
    const body = await request.json();
    return HttpResponse.json(
      {
        id: 'new-id',
        ...body,
        created_at: new Date().toISOString(),
      },
      { status: 201 }
    );
  }),
];

export const errorHandlers = {
  listItemsError: http.get(`${API_BASE}/items`, () => {
    return HttpResponse.json(
      { detail: 'Failed to load items', code: 'LIST_ERROR' },
      { status: 500 }
    );
  }),
};

export default handlers;
```

```typescript
// src/__tests__/mocks/server.ts
import { setupServer } from 'msw/node';
import { handlers } from './handlers';

export const server = setupServer(...handlers);
export { handlers } from './handlers';
```

```typescript
// src/test/components/ItemList.test.tsx
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect } from 'vitest';
import { ItemList } from '@/components/ItemList';
import { server } from '@/__tests__/mocks/server';
import { errorHandlers } from '@/__tests__/mocks/handlers';
import { http, HttpResponse } from 'msw';

describe('ItemList', () => {
  it('renders list of items from API', async () => {
    render(<ItemList />);
    expect(await screen.findByText('Item One')).toBeInTheDocument();
    expect(screen.getByText('Item Two')).toBeInTheDocument();
  });

  it('shows error message when API fails', async () => {
    server.use(errorHandlers.listItemsError);
    render(<ItemList />);
    expect(await screen.findByText(/failed to load/i)).toBeInTheDocument();
  });

  it('filters items on search', async () => {
    const user = userEvent.setup();
    render(<ItemList />);
    await screen.findByText('Item One');
    await user.type(screen.getByRole('textbox', { name: /search/i }), 'Two');
    expect(screen.queryByText('Item One')).not.toBeInTheDocument();
    expect(screen.getByText('Item Two')).toBeInTheDocument();
  });

  it('creates new item on submit', async () => {
    const user = userEvent.setup();
    render(<ItemList />);
    await user.type(screen.getByRole('textbox', { name: /name/i }), 'New Item');
    await user.click(screen.getByRole('button', { name: /add/i }));
    expect(await screen.findByText('New Item')).toBeInTheDocument();
  });
});
```

```typescript
// src/__tests__/contracts/helpers.ts
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

## Anti-patterns to avoid

1. **Not awaiting async user interactions**: forgetting `await` before `user.click()` or `user.type()` causes tests to pass when they should fail.
2. **Manually calling server.listen/resetHandlers/close in tests**: MSW lifecycle should be managed globally, not per-test. Use `server.use()` for test-specific overrides.
3. **Overusing getByTestId**: prefer accessible queries (`getByRole`, `getByLabelText`, `getByText`) over test IDs.
4. **Not stubbing jsdom-missing APIs**: tests will crash if `matchMedia`, `IntersectionObserver`, etc., are not stubbed in setup.
5. **Duplicating Zod schemas without contract tests**: frontend schemas drift from backend unless validated with fixture-driven contract tests.
6. **Forgetting .strict() on Zod schemas in contract tests**: schemas accept unknown fields by default; use `strictDeep()` to enforce exact shape match.
7. **Not testing error states**: only testing happy paths leaves error handling code untested. Use `server.use()` to inject error responses.
8. **Hardcoding API responses in component tests**: use MSW handlers to centralize mock data and make tests resilient to API changes.
9. **Not using userEvent.setup()**: calling `userEvent.click()` directly (v14+ syntax) skips setup and may cause timing issues; always call `const user = userEvent.setup()` first.
10. **Mixing MSW v1 and v2 APIs**: MSW v2 uses `http.get()` and `HttpResponse.json()`, not `rest.get()` and `res()` / `ctx.json()` from v1.
11. **Not cleaning up after each test**: forgetting `cleanup()` in `afterEach()` causes DOM state leakage between tests.
12. **Not resetting mocks in afterEach**: `vi.clearAllMocks()` is required to reset vi.fn() state between tests.

## References

- [repo-evidence.md](references/repo-evidence.md) — source patterns and file locations (genericized)
- [vitest-rtl-setup.md](references/vitest-rtl-setup.md) — Vitest config, test setup, jsdom stubs, MSW integration
- [msw-and-contract-tests.md](references/msw-and-contract-tests.md) — MSW v2 handlers, fixture-driven contract tests, strictDeep helper
- [testing-conventions.md](../testing-conventions/SKILL.md) — backend pytest patterns (cross-reference)
- [frontend-repo-architecture.md](../frontend-repo-architecture/SKILL.md) — frontend project structure (cross-reference)
