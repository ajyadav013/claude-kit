---
name: unit-test
description: Write unit tests for frontend components and hooks. Follows testing best practices focusing on user behavior over implementation details. Adapts to the project's test runner and component framework.
argument-hint: [component or hook name]
disable-model-invocation: true
---

Write unit tests for: $ARGUMENTS.

## Steps

1. **Read the target code**: Read the component or hook file for `$ARGUMENTS` to understand its props, behavior, state, and edge cases.

2. **Identify what to test**:

   ### Always Test
   - Component renders without crashing (smoke test)
   - Props produce expected visible output
   - User interactions trigger expected behavior (click, type, submit)
   - Conditional rendering: loading state, empty state, error state, data state
   - Accessibility: correct roles, labels, ARIA attributes

   ### Never Test
   - Implementation details (internal state values, private functions)
   - Third-party library behavior (UI libraries, chart libraries, state management internals)
   - Exact CSS classes or styling utilities
   - Mock data structure (the type checker handles this)
   - Snapshot tests (fragile, noisy diffs)

3. **Write the test file**: Create the test file following the project's test file naming convention (e.g., `<ComponentName>.test.tsx`, `<ComponentName>.spec.tsx`, or `__tests__/<ComponentName>.test.tsx`).

   ### Test File Template (Component Testing Library Pattern)
   ```typescript
   import { render, screen } from '@testing-library/react';
   import userEvent from '@testing-library/user-event';
   import { describe, it, expect, vi } from 'vitest';  // or jest
   import { ComponentName } from './ComponentName';

   // Wrap in providers if needed (router, state management, etc.)
   function renderComponent(props: Partial<ComponentNameProps> = {}) {
     const defaultProps: ComponentNameProps = {
       // sensible defaults
     };
     return render(<ComponentName {...defaultProps} {...props} />);
   }

   describe('ComponentName', () => {
     it('renders with default props', () => {
       renderComponent();
       expect(screen.getByRole('...')).toBeInTheDocument();
     });

     it('displays the provided title', () => {
       renderComponent({ title: 'Test Title' });
       expect(screen.getByText('Test Title')).toBeInTheDocument();
     });

     it('calls onClick when button is clicked', async () => {
       const user = userEvent.setup();
       const handleClick = vi.fn();
       renderComponent({ onClick: handleClick });

       await user.click(screen.getByRole('button', { name: /action/i }));
       expect(handleClick).toHaveBeenCalledOnce();
     });

     it('shows empty state when no data', () => {
       renderComponent({ data: [] });
       expect(screen.getByText(/no.*found/i)).toBeInTheDocument();
     });

     it('shows loading spinner when loading', () => {
       renderComponent({ isLoading: true });
       expect(screen.getByRole('status')).toBeInTheDocument();
     });
   });
   ```

4. **Follow query priority** (from Testing Library best practices):

   | Priority | Method | When to Use |
   |----------|--------|-------------|
   | 1 | `getByRole` | Accessible elements (buttons, headings, links) |
   | 2 | `getByLabelText` | Form inputs |
   | 3 | `getByText` | Non-interactive text content |
   | 4 | `getByDisplayValue` | Current input values |
   | 5 | `getByTestId` | Last resort — add `data-testid` to element |

5. **Handle providers and wrappers**:

   ### Router Context (React Router example)
   ```typescript
   import { MemoryRouter } from 'react-router-dom';

   function renderWithRouter(ui: React.ReactElement, { route = '/' } = {}) {
     return render(
       <MemoryRouter initialEntries={[route]}>{ui}</MemoryRouter>
     );
   }
   ```

   ### State Store Mocking (example for a state management library)
   ```typescript
   import { useAppStore } from '@/hooks/useAppStore';

   vi.mock('@/hooks/useAppStore');

   beforeEach(() => {
     vi.mocked(useAppStore).mockImplementation((selector) =>
       selector({
         currentUser: { id: '1', name: 'Test User' },
         // ... other store values
       })
     );
   });
   ```

6. **Test async behavior**:
   ```typescript
   it('loads and displays data', async () => {
     renderComponent();
     // Wait for async content
     expect(await screen.findByText('Expected Content')).toBeInTheDocument();
   });
   ```

7. **Test accessibility**:
   ```typescript
   it('has accessible button labels', () => {
     renderComponent();
     expect(screen.getByRole('button', { name: 'Close dialog' })).toBeInTheDocument();
   });

   it('supports keyboard navigation', async () => {
     const user = userEvent.setup();
     renderComponent();
     await user.tab();
     expect(screen.getByRole('button')).toHaveFocus();
   });
   ```

8. **Run tests**: Execute the project's test command (check `package.json` scripts or the project's test runner docs).

## Test Organization

```
src/
  components/
    ui/
      Button.tsx
      Button.test.tsx         # Co-located test
    FeatureCard.tsx
    FeatureCard.test.tsx      # Co-located test
  hooks/
    useAppStore.ts
    useAppStore.test.ts       # Hook tests
  pages/
    DashboardPage.tsx
    DashboardPage.test.tsx    # Page-level tests (lighter, focused on integration)
```

## Conventions

### Naming
- Test files: Follow project convention (e.g., `<Component>.test.tsx`, `<Component>.spec.tsx`, or `<hook>.test.ts`)
- Describe blocks: component/hook name
- Test names: describe behavior in plain English — `it('shows error message when form is invalid')`

### Assertions
- Prefer `toBeInTheDocument()` over `toBeTruthy()`
- Prefer `toHaveTextContent()` over checking `.textContent`
- Use `toHaveAttribute()` for ARIA and HTML attributes
- Use `not.toBeInTheDocument()` to assert absence (with `queryBy*`)

### Mocking
- Mock external dependencies, not internal logic
- Use the test runner's mock function (e.g., `vi.fn()`, `jest.fn()`) for callback props
- Use module-level mocks for state stores and API calls
- Reset mocks in `beforeEach` or use the test runner's clear/reset utilities

### Coverage Targets
| Metric | Target |
|--------|--------|
| Statements | 70% |
| Branches | 65% |
| Functions | 70% |
| Lines | 70% |

Focus coverage on business logic and user-facing behavior, not boilerplate.

## Setup Requirements

The project's test runner and assertion library should be configured. Common stacks:

### Example: Vitest + React Testing Library
```bash
# Install test dependencies (if not already installed)
npm install -D vitest @testing-library/react @testing-library/jest-dom @testing-library/user-event jsdom @vitest/coverage-v8
```

### Example: Jest + React Testing Library
```bash
npm install -D jest @testing-library/react @testing-library/jest-dom @testing-library/user-event jest-environment-jsdom
```

### Test Runner Config (Vitest example)
```typescript
// vitest.config.ts
import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
import path from 'path';

export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: './src/test/setup.ts',
    include: ['src/**/*.test.{ts,tsx}'],
    coverage: {
      provider: 'v8',
      reporter: ['text', 'html'],
      include: ['src/**/*.{ts,tsx}'],
      exclude: ['src/**/*.test.*', 'src/data/**', 'src/test/**'],
    },
  },
  resolve: {
    alias: { '@': path.resolve(__dirname, './src') },
  },
});
```

### Test Setup File (Testing Library example)
```typescript
// src/test/setup.ts
import '@testing-library/jest-dom/vitest';  // or '@testing-library/jest-dom' for Jest
```
