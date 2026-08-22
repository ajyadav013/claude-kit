# Vitest + React Testing Library Setup

Production patterns for configuring Vitest with jsdom, React Testing Library, and coverage.

## Vitest configuration (vitest.config.ts)

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
    css: false, // Skip CSS parsing for faster tests
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
        'src/lib/api.ts', // Example: API client with side effects
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

**Key settings:**
- `globals: true` — no need to import `describe`, `it`, `expect` in each test
- `environment: 'jsdom'` — DOM simulation for React components
- `setupFiles` — global setup runs before each test file
- `css: false` — skip CSS module parsing (faster tests)
- `coverage.provider: 'v8'` — fast native coverage (vs. istanbul)
- `coverage.thresholds` — enforce minimum coverage levels

## Test setup file (src/test/setup.ts)

```typescript
import '@testing-library/jest-dom/vitest';
import { cleanup } from '@testing-library/react';
import { afterEach, vi } from 'vitest';

// Cleanup DOM after each test
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

// Stub window.matchMedia (not implemented in jsdom)
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

// Stub Element.scrollIntoView
Element.prototype.scrollIntoView = vi.fn();

// Stub Element.scrollTo (if needed for Radix Tabs, etc.)
if (typeof Element !== 'undefined' && Element.prototype.scrollTo === undefined) {
  Element.prototype.scrollTo = vi.fn() as unknown as Element['scrollTo'];
}

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

// Stub sessionStorage (same implementation)
Object.defineProperty(window, 'sessionStorage', {
  value: localStorageMock,
});

// Stub URL.createObjectURL (for file upload tests)
URL.createObjectURL = vi.fn(() => 'mock-object-url');
URL.revokeObjectURL = vi.fn();

// Optionally stub global fetch
global.fetch = vi.fn();
```

**Why these stubs:**
- jsdom does not implement browser APIs like `matchMedia`, `IntersectionObserver`, `ResizeObserver`
- Components using these APIs (e.g., Radix UI, Tailwind responsive hooks) will crash without stubs
- `cleanup()` ensures no DOM state leaks between tests
- `vi.clearAllMocks()` resets all `vi.fn()` call counts

## React Testing Library patterns

```typescript
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect } from 'vitest';
import { MyComponent } from '@/components/MyComponent';

describe('MyComponent', () => {
  it('renders with initial state', () => {
    render(<MyComponent />);
    expect(screen.getByRole('heading', { name: 'Title' })).toBeInTheDocument();
  });

  it('toggles visibility on button click', async () => {
    const user = userEvent.setup();
    render(<MyComponent />);
    await user.click(screen.getByRole('button', { name: 'Toggle' }));
    expect(screen.queryByText('Hidden')).not.toBeInTheDocument();
  });

  it('calls onChange when input changes', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<MyComponent onChange={onChange} />);
    await user.type(screen.getByRole('textbox'), 'Hello');
    expect(onChange).toHaveBeenCalledWith('Hello');
  });
});
```

**Key patterns:**
- `const user = userEvent.setup()` at the start of async interaction tests
- Prefer `getByRole()` over `getByTestId()` for accessibility
- Use `queryBy*` for asserting absence
- Use `findBy*` for async appearance (`await screen.findByText('Loaded')`)
- Always `await` user interactions (`await user.click()`, `await user.type()`)

## Test harness for context/router

```typescript
import { render } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';

const renderWithRouter = (
  initialPath: string,
  element: React.ReactNode,
) => {
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <Routes>
        <Route path="/login" element={<div>Login</div>} />
        <Route path="/dashboard" element={element} />
      </Routes>
    </MemoryRouter>,
  );
};

describe('Dashboard', () => {
  it('redirects to login when not authenticated', () => {
    renderWithRouter('/dashboard', <Dashboard />);
    expect(screen.getByText('Login')).toBeInTheDocument();
  });
});
```

## Test scripts (package.json)

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
    "vitest": "^3.2.0"
  }
}
```

**Script usage:**
- `npm test` — watch mode for development
- `npm run test:run` — single run for CI
- `npm run test:coverage` — generate coverage report
- `npm run test:ui` — visual test runner at `http://localhost:5173/__vitest__/`

## Common assertions (jest-dom)

```typescript
// Presence
expect(element).toBeInTheDocument();
expect(element).not.toBeInTheDocument();

// Visibility
expect(element).toBeVisible();
expect(element).not.toBeVisible();

// Text content
expect(element).toHaveTextContent('Hello');

// Attributes
expect(element).toHaveAttribute('aria-label', 'Submit');
expect(element).toHaveClass('active');
expect(element).toHaveStyle({ display: 'flex' });

// Form state
expect(input).toHaveValue('test');
expect(checkbox).toBeChecked();
expect(button).toBeDisabled();
expect(select).toHaveFormValues({ name: 'value' });

// Accessibility
expect(element).toHaveAccessibleName('Submit');
expect(element).toHaveAccessibleDescription('Description');
```

## Example: Component with state

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

**Pattern:** wrap component + state in a test harness function for easy setup/reuse.
