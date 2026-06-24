# Vitest Frontend Testing

Vitest configuration and testing patterns for React/TypeScript frontends.

## Vitest Configuration

**Pattern** (example):

```typescript
// vitest.config.ts
import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
import path from 'path';

export default defineConfig({
  plugins: [react()],
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/test/**/*.test.{ts,tsx}'],
    coverage: {
      provider: 'v8',
      include: ['src/lib/**', 'src/hooks/**'],
      exclude: [
        'src/test/**',
        'src/**/*.test.{ts,tsx}',
        'src/lib/api.ts',  // Exclude API clients (mocked in tests)
        'src/modules/analytics/components/AnalyticsPanel.tsx',  // Hard-to-test component
      ],
      thresholds: {
        lines: 90,
        functions: 90,
        branches: 90,
        statements: 90,
      },
    },
  },
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
});
```

**Key settings**:
- `globals: true` — Enables global `describe`, `it`, `expect` without imports
- `environment: 'jsdom'` — Simulates browser environment for React components
- `setupFiles` — Runs test utilities/mocks before each test file
- `include` — Test file discovery pattern
- `coverage.provider: 'v8'` — Fast coverage via V8 (alternative: 'istanbul')
- `coverage.include` — Only measure coverage for these paths
- `coverage.exclude` — Exclude test files, hard-to-test components, generated files
- `coverage.thresholds` — Fail if coverage drops below 90%

## Setup File

**Pattern** (example):

```typescript
// src/test/setup.ts
import { expect, afterEach } from 'vitest';
import { cleanup } from '@testing-library/react';
import * as matchers from '@testing-library/jest-dom/matchers';

// Extend Vitest's expect with jest-dom matchers
expect.extend(matchers);

// Cleanup after each test
afterEach(() => {
  cleanup();
});

// Mock window.matchMedia (not available in jsdom)
Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: vi.fn().mockImplementation((query) => ({
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

**Key utilities**:
- `@testing-library/jest-dom/matchers` — Provides `toBeInTheDocument`, `toHaveClass`, etc.
- `cleanup()` — Unmounts React components after each test (prevents memory leaks)
- `window.matchMedia` mock — Required for responsive components

## Hook Testing Pattern

**Example** (useToast hook):

```typescript
// src/test/hooks/useToast.test.ts
import { renderHook, act } from '@testing-library/react';
import { useToast } from '@/hooks/useToast';

describe('useToast', () => {
  it('should add a toast', () => {
    const { result } = renderHook(() => useToast());

    act(() => {
      result.current.toast({
        title: 'Success',
        description: 'Operation completed',
        variant: 'success',
      });
    });

    expect(result.current.toasts).toHaveLength(1);
    expect(result.current.toasts[0].title).toBe('Success');
  });

  it('should remove a toast by id', () => {
    const { result } = renderHook(() => useToast());

    let toastId: string;
    act(() => {
      toastId = result.current.toast({ title: 'Test' });
    });

    act(() => {
      result.current.dismiss(toastId);
    });

    expect(result.current.toasts).toHaveLength(0);
  });
});
```

**Key utilities**:
- `renderHook()` — Renders a hook in isolation
- `act()` — Wraps state updates to flush React effects
- `result.current` — Access hook's return value

## Component Testing Pattern

**Example** (Badge component):

```typescript
// src/test/components/ui/Badge.test.tsx
import { render, screen } from '@testing-library/react';
import { Badge } from '@/components/ui/Badge';

describe('Badge', () => {
  it('should render with default variant', () => {
    render(<Badge>Default</Badge>);
    const badge = screen.getByText('Default');
    expect(badge).toBeInTheDocument();
    expect(badge).toHaveClass('bg-primary');
  });

  it('should render with secondary variant', () => {
    render(<Badge variant="secondary">Secondary</Badge>);
    const badge = screen.getByText('Secondary');
    expect(badge).toHaveClass('bg-secondary');
  });

  it('should render with outline variant', () => {
    render(<Badge variant="outline">Outline</Badge>);
    const badge = screen.getByText('Outline');
    expect(badge).toHaveClass('border');
  });
});
```

**Key utilities**:
- `render()` — Renders a React component
- `screen.getByText()` — Queries DOM by text content
- `toBeInTheDocument()` — jest-dom matcher (checks element exists)
- `toHaveClass()` — jest-dom matcher (checks CSS class)

## API Client Testing Pattern

**Example** (tasksApi client):

```typescript
// src/test/modules/tasks/api/tasksApi.test.ts
import { vi } from 'vitest';
import { tasksApi } from '@/modules/tasks/api/tasksApi';

// Mock fetch
global.fetch = vi.fn();

describe('tasksApi', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('should fetch tasks', async () => {
    const mockTasks = [
      { id: '1', title: 'Task 1', status: 'pending' },
      { id: '2', title: 'Task 2', status: 'done' },
    ];

    (global.fetch as any).mockResolvedValueOnce({
      ok: true,
      json: async () => mockTasks,
    });

    const tasks = await tasksApi.getTasks();

    expect(global.fetch).toHaveBeenCalledWith('/api/tasks');
    expect(tasks).toEqual(mockTasks);
  });

  it('should throw error on fetch failure', async () => {
    (global.fetch as any).mockResolvedValueOnce({
      ok: false,
      statusText: 'Not Found',
    });

    await expect(tasksApi.getTasks()).rejects.toThrow('Not Found');
  });
});
```

**Key patterns**:
- Mock `global.fetch` with `vi.fn()`
- `mockResolvedValueOnce()` — Mock async response for single call
- `vi.clearAllMocks()` — Reset mocks between tests
- `toHaveBeenCalledWith()` — Verify fetch called with correct URL
- `rejects.toThrow()` — Verify async function throws

## Coverage Strategy

**Prioritize**:
1. **Hooks** — State management, side effects, custom logic (high ROI)
2. **Lib/utils** — Pure functions, helpers, transformations (easy to test)
3. **API clients** — Request/response contracts (mock fetch)
4. **Components** — Variant rendering, prop passing (medium ROI)

**Defer/Exclude**:
1. **Complex UI components** — Layout-heavy, hard-to-mock (e.g., AnalyticsPanel)
2. **Third-party integrations** — API clients that wrap external SDKs (mock at boundary)
3. **Generated code** — Auto-generated types, configs

**Set thresholds incrementally**:
- Start: 60-70% (hooks + utils)
- Mature: 80-85% (hooks + utils + components)
- Production: 90%+ (all critical paths)

Exclude specific hard-to-test files rather than lowering global thresholds.

## Anti-Patterns

- **Testing implementation details** — Don't test component state, internal functions; test user-visible behavior.
- **Not mocking window/global APIs** — jsdom doesn't provide `matchMedia`, `IntersectionObserver`, etc.; mock them.
- **Skipping cleanup** — Always use `afterEach(cleanup)` to prevent memory leaks.
- **Aggressive thresholds without exclusions** — 90% coverage is achievable if you exclude hard-to-test components; don't lower standards for everything.
- **Not using act()** — State updates in hooks must be wrapped in `act()` or tests will warn/fail.

## References

- Vitest docs: https://vitest.dev/guide/
- Testing Library: https://testing-library.com/docs/react-testing-library/intro/
