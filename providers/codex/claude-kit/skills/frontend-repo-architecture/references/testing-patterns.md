# Testing Patterns

This file covers the testing conventions across the three frontend architectures: unit tests, contract tests with msw, and testing-library patterns.

---

## Shared testing stack

All three repos use the same core testing stack:

- **vitest** — test runner (Vite-native alternative to Jest)
- **@testing-library/react** — component testing utilities (queries, user events, assertions)
- **@testing-library/user-event** — realistic user interaction simulation
- **msw (Mock Service Worker)** — API mocking for contract tests (reference service B only; observed pattern)

**Configuration files:**
- `vitest.config.ts` — test environment setup, globals, coverage
- `src/__tests__/setup.ts` — global test setup (msw handlers, cleanup, polyfills)

---

## Testing patterns by model

### Module-scoped model (reference service A)

**Test file locations:**
- Unit tests: `modules/<feature>/__tests__/<ComponentName>.test.tsx`
- Hook tests: `modules/<feature>/__tests__/hooks/<hookName>.test.ts`
- API hook tests: `modules/<feature>/api/__tests__/<apiHook>.test.ts`

**Pattern:**
```typescript
// modules/inventory/components/__tests__/InventoryTable.test.tsx
import { render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { InventoryTable } from '../InventoryTable';

describe('InventoryTable', () => {
  it('renders inventory items', async () => {
    const queryClient = new QueryClient();
    render(
      <QueryClientProvider client={queryClient}>
        <InventoryTable storeId="store-123" />
      </QueryClientProvider>
    );
    
    expect(await screen.findByText('Loading...')).toBeInTheDocument();
  });
});
```

**react-query testing pattern:**
```typescript
// modules/inventory/api/__tests__/inventoryApi.test.ts
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { useInventoryQuery } from '../inventoryApi';

const createWrapper = () => {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
};

describe('useInventoryQuery', () => {
  it('fetches inventory data', async () => {
    const { result } = renderHook(() => useInventoryQuery('store-123'), {
      wrapper: createWrapper(),
    });
    
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toHaveLength(10);
  });
});
```

---

### Feature-sliced model (reference service B)

**Test file locations:**
- Contract tests: `src/__tests__/contracts/<domain>.test.ts`
- Component tests: `src/__tests__/components/<ComponentName>.test.tsx`
- Store tests: `src/__tests__/stores/<storeName>.test.ts`
- Hook tests: `src/__tests__/hooks/<hookName>.test.ts`
- Page tests: `src/__tests__/pages/<PageName>.test.tsx`

**msw contract test pattern:**
```typescript
// __tests__/contracts/video.test.ts
import { describe, it, expect, beforeAll, afterEach, afterAll } from 'vitest';
import { setupServer } from 'msw/node';
import { http, HttpResponse } from 'msw';
import { api } from '@/lib/api';

const server = setupServer();

beforeAll(() => server.listen({ onUnhandledRequest: 'error' }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

describe('Video API contract', () => {
  it('generates video successfully', async () => {
    server.use(
      http.post('/api/v1/videos/generate', async () => {
        return HttpResponse.json({
          id: 'video-123',
          document_id: 'document-456',
          status: 'pending',
          url: null,
          created_at: '2024-01-01T00:00:00Z',
          updated_at: '2024-01-01T00:00:00Z',
        });
      })
    );

    const result = await api.post('/videos/generate', { document_id: 'document-456' });
    
    expect(result).toMatchObject({
      id: 'video-123',
      document_id: 'document-456',
      status: 'pending',
    });
  });

  it('handles 500 errors', async () => {
    server.use(
      http.post('/api/v1/videos/generate', async () => {
        return HttpResponse.json(
          { detail: 'Internal server error', code: 'INTERNAL_ERROR' },
          { status: 500 }
        );
      })
    );

    await expect(
      api.post('/videos/generate', { document_id: 'document-456' })
    ).rejects.toThrow('Internal server error');
  });
});
```

**Store testing pattern:**
```typescript
// __tests__/stores/video.test.ts
import { describe, it, expect, beforeEach } from 'vitest';
import { act, renderHook } from '@testing-library/react';
import { useVideoStore } from '@/stores/video';

describe('useVideoStore', () => {
  beforeEach(() => {
    // Reset store state before each test
    const { resetState } = useVideoStore.getState();
    act(() => resetState());
  });

  it('initializes with null video', () => {
    const { result } = renderHook(() => useVideoStore());
    expect(result.current.currentVideo).toBeNull();
    expect(result.current.isLoading).toBe(false);
  });

  it('loads video successfully', async () => {
    const { result } = renderHook(() => useVideoStore());
    
    await act(async () => {
      await result.current.loadVideo('video-123');
    });

    expect(result.current.currentVideo).toMatchObject({
      id: 'video-123',
    });
    expect(result.current.isLoading).toBe(false);
  });
});
```

**Component testing with user events:**
```typescript
// __tests__/components/VideoPlayer.test.tsx
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { VideoPlayer } from '@/components/domain/VideoPlayer';

describe('VideoPlayer', () => {
  it('plays video on play button click', async () => {
    const user = userEvent.setup();
    const mockOnPlay = vi.fn();
    
    render(<VideoPlayer videoUrl="https://example.com/video.mp4" onPlay={mockOnPlay} />);
    
    const playButton = screen.getByRole('button', { name: /play/i });
    await user.click(playButton);
    
    expect(mockOnPlay).toHaveBeenCalledOnce();
  });

  it('displays loading state while video loads', () => {
    render(<VideoPlayer videoUrl="https://example.com/video.mp4" isLoading />);
    
    expect(screen.getByText(/loading/i)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /play/i })).not.toBeInTheDocument();
  });
});
```

---

### GraphQL-SSR model (reference service C)

**Test file locations:**
- Component tests: `src/__tests__/components/<ComponentName>.test.tsx` (inferred; pattern expected)
- GraphQL query tests: `src/__tests__/graphql/<queryName>.test.ts` (inferred)

**Apollo MockedProvider pattern:**
```typescript
// __tests__/components/JobsPage.test.tsx (inferred pattern)
import { render, screen } from '@testing-library/react';
import { MockedProvider } from '@apollo/client/testing';
import { JobsPage } from '@/pages/JobsPage';
import { GET_JOBS } from '@/graphql/queries/jobs';

const mocks = [
  {
    request: {
      query: GET_JOBS,
      variables: { status: 'active' },
    },
    result: {
      data: {
        jobs: [
          { id: 'job-1', title: 'Software Engineer', status: 'active', location: 'Remote' },
          { id: 'job-2', title: 'Product Manager', status: 'active', location: 'NYC' },
        ],
      },
    },
  },
];

describe('JobsPage', () => {
  it('renders jobs list', async () => {
    render(
      <MockedProvider mocks={mocks} addTypename={false}>
        <JobsPage />
      </MockedProvider>
    );

    expect(await screen.findByText('Software Engineer')).toBeInTheDocument();
    expect(screen.getByText('Product Manager')).toBeInTheDocument();
  });

  it('handles loading state', () => {
    render(
      <MockedProvider mocks={[]} addTypename={false}>
        <JobsPage />
      </MockedProvider>
    );

    expect(screen.getByText(/loading/i)).toBeInTheDocument();
  });
});
```

**GraphQL error testing:**
```typescript
// __tests__/graphql/jobs.test.ts (inferred pattern)
import { MockedProvider } from '@apollo/client/testing';
import { GraphQLError } from 'graphql';
import { GET_JOBS } from '@/graphql/queries/jobs';

const errorMock = {
  request: {
    query: GET_JOBS,
    variables: { status: 'active' },
  },
  error: new GraphQLError('UNAUTHENTICATED', {
    extensions: { code: 'UNAUTHENTICATED' },
  }),
};

describe('Jobs GraphQL error handling', () => {
  it('handles UNAUTHENTICATED error', async () => {
    // Test that errorLink redirects to /login
    // (requires integration test setup with mocked window.location)
  });
});
```

---

## Common testing patterns (all models)

### 1. Testing-library queries (order of preference)

Use queries in this order (from most to least preferred):

1. **Accessible queries** (best):
   - `getByRole('button', { name: /submit/i })`
   - `getByLabelText(/email/i)`
   - `getByPlaceholderText(/search/i)`
   - `getByText(/welcome/i)`

2. **Semantic queries**:
   - `getByAltText(/profile picture/i)`
   - `getByTitle(/close/i)`

3. **Test ID queries** (last resort):
   - `getByTestId('video-player')`

**Anti-pattern:** Using `container.querySelector()` or `container.getElementsByClassName()` — these bypass accessibility and are fragile.

### 2. Async testing

Use `findBy*` for elements that appear asynchronously:

```typescript
// ✅ Correct
expect(await screen.findByText('Data loaded')).toBeInTheDocument();

// ❌ Wrong (race condition)
await waitFor(() => {
  expect(screen.getByText('Data loaded')).toBeInTheDocument();
});
```

### 3. User interaction testing

Use `@testing-library/user-event` for realistic interactions:

```typescript
import userEvent from '@testing-library/user-event';

const user = userEvent.setup();

// Click
await user.click(screen.getByRole('button', { name: /submit/i }));

// Type
await user.type(screen.getByLabelText(/email/i), 'test@example.com');

// Clear and type
await user.clear(screen.getByLabelText(/password/i));
await user.type(screen.getByLabelText(/password/i), 'newpassword');

// Select option
await user.selectOptions(screen.getByLabelText(/status/i), 'active');

// Upload file
const file = new File(['content'], 'test.png', { type: 'image/png' });
await user.upload(screen.getByLabelText(/upload/i), file);
```

### 4. Testing zustand stores

```typescript
import { renderHook, act } from '@testing-library/react';
import { useMyStore } from '@/stores/myStore';

describe('useMyStore', () => {
  beforeEach(() => {
    // Reset store state
    const { reset } = useMyStore.getState();
    act(() => reset());
  });

  it('updates state', () => {
    const { result } = renderHook(() => useMyStore());
    
    act(() => {
      result.current.increment();
    });

    expect(result.current.count).toBe(1);
  });
});
```

### 5. Testing React Context

```typescript
import { render } from '@testing-library/react';
import { AuthProvider, useAuth } from '@/contexts/AuthContext';

const TestComponent = () => {
  const { user, login } = useAuth();
  return <div>{user ? `Logged in as ${user.name}` : 'Not logged in'}</div>;
};

describe('AuthContext', () => {
  it('provides auth state', () => {
    render(
      <AuthProvider>
        <TestComponent />
      </AuthProvider>
    );
    
    expect(screen.getByText('Not logged in')).toBeInTheDocument();
  });
});
```

---

## Test setup patterns

### vitest.config.ts (shared pattern)

```typescript
import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
import path from 'path';

export default defineConfig({
  plugins: [react()],
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: './src/__tests__/setup.ts',
    coverage: {
      provider: 'v8',
      reporter: ['text', 'json', 'html'],
      exclude: ['node_modules/', 'src/__tests__/'],
    },
  },
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
      '@components': path.resolve(__dirname, './src/components'),
      '@lib': path.resolve(__dirname, './src/lib'),
      '@stores': path.resolve(__dirname, './src/stores'),
      '@types': path.resolve(__dirname, './src/types'),
    },
  },
});
```

### __tests__/setup.ts (reference service B pattern)

```typescript
import '@testing-library/jest-dom';
import { cleanup } from '@testing-library/react';
import { afterEach, beforeAll, afterAll } from 'vitest';
import { setupServer } from 'msw/node';
import { http, HttpResponse } from 'msw';

// MSW server setup
export const server = setupServer();

beforeAll(() => {
  server.listen({ onUnhandledRequest: 'warn' });
});

afterEach(() => {
  cleanup();
  server.resetHandlers();
});

afterAll(() => {
  server.close();
});

// Mock localStorage
const localStorageMock = (() => {
  let store: Record<string, string> = {};
  return {
    getItem: (key: string) => store[key] || null,
    setItem: (key: string, value: string) => { store[key] = value; },
    removeItem: (key: string) => { delete store[key]; },
    clear: () => { store = {}; },
  };
})();

Object.defineProperty(window, 'localStorage', { value: localStorageMock });

// Mock window.matchMedia
Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: vi.fn().mockImplementation(query => ({
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
```

---

## Coverage and CI patterns

### Coverage thresholds (vitest.config.ts)

```typescript
export default defineConfig({
  test: {
    coverage: {
      statements: 80,
      branches: 75,
      functions: 80,
      lines: 80,
      exclude: [
        'node_modules/',
        'src/__tests__/',
        'src/main.tsx',
        'src/vite-env.d.ts',
        '**/*.d.ts',
        '**/*.config.ts',
      ],
    },
  },
});
```

### CI test command (package.json)

```json
{
  "scripts": {
    "test": "vitest",
    "test:ui": "vitest --ui",
    "test:coverage": "vitest run --coverage",
    "test:ci": "vitest run --reporter=verbose --coverage"
  }
}
```

---

## Testing anti-patterns to avoid

1. **Testing implementation details** — Don't test internal state; test user-facing behavior:
   ```typescript
   // ❌ Wrong
   expect(component.state.count).toBe(1);
   
   // ✅ Correct
   expect(screen.getByText('Count: 1')).toBeInTheDocument();
   ```

2. **Using `container.querySelector()`** — Bypasses accessibility; use testing-library queries:
   ```typescript
   // ❌ Wrong
   const button = container.querySelector('.submit-button');
   
   // ✅ Correct
   const button = screen.getByRole('button', { name: /submit/i });
   ```

3. **Mixing act() and async/await incorrectly** — Use `act()` only for synchronous state updates; async updates use `findBy*`:
   ```typescript
   // ❌ Wrong
   act(() => {
     user.click(button); // user.click is async, returns a Promise
   });
   
   // ✅ Correct
   await user.click(button);
   ```

4. **Not resetting store state between tests** — Leads to test pollution:
   ```typescript
   // ❌ Wrong
   describe('useMyStore', () => {
     it('test 1', () => { /* ... */ });
     it('test 2', () => { /* test 2 sees state from test 1 */ });
   });
   
   // ✅ Correct
   beforeEach(() => {
     const { reset } = useMyStore.getState();
     act(() => reset());
   });
   ```

5. **Not cleaning up after tests** — Use `@testing-library/react`'s auto-cleanup or manual cleanup in `afterEach`:
   ```typescript
   import { cleanup } from '@testing-library/react';
   
   afterEach(() => {
     cleanup();
   });
   ```

6. **Hardcoding wait times** — Use `findBy*` or `waitFor` instead of `setTimeout`:
   ```typescript
   // ❌ Wrong
   await new Promise(resolve => setTimeout(resolve, 1000));
   expect(screen.getByText('Loaded')).toBeInTheDocument();
   
   // ✅ Correct
   expect(await screen.findByText('Loaded')).toBeInTheDocument();
   ```

---

## Summary: testing best practices

1. **Use msw for contract tests** — Mock API responses at the network layer (reference service B pattern)
2. **Test user behavior, not implementation** — Focus on what users see and do
3. **Prefer accessible queries** — `getByRole`, `getByLabelText` over `getByTestId`
4. **Reset store state between tests** — Use `beforeEach` to clear zustand/context state
5. **Use `findBy*` for async assertions** — Don't use `waitFor` with `getBy*`
6. **Mock providers for react-query/Apollo** — Wrap components in `QueryClientProvider` or `MockedProvider`
7. **Test error states and edge cases** — Not just happy paths
8. **Maintain 80% coverage threshold** — Lines, statements, branches, functions

---

## References

- **reference service B `__tests__/` directory** — production contract tests, store tests, component tests, hook tests, page tests
- **reference service A module-scoped pattern** — `modules/<feature>/__tests__/` structure (inferred; conventional)
- **reference service C Apollo MockedProvider pattern** — GraphQL query/mutation testing (inferred; conventional Apollo pattern)
