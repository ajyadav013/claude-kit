# Testing Standards

All new code and modified code MUST have accompanying unit tests with a minimum **90% coverage** threshold across all metrics (or as defined by the project's coverage policy).

## Coverage Thresholds (Enforced)

| Metric | Minimum |
|--------|---------|
| Statements | 90% |
| Branches | 90% |
| Functions | 90% |
| Lines | 90% |

These thresholds should be configured in the project's test runner configuration and enforced via the test coverage command. **Do not lower them without justification.**

## Stack-Specific Setup

The project uses:
- The project's test runner (check package.json/pyproject.toml/build config for the test framework)
- The project's coverage provider
- Testing libraries appropriate to the stack (component testing libraries for UI, mocking libraries, assertion libraries)

Refer to the project's test configuration files for exact setup and command reference.

## Commands

Run the project's test commands:
- Run all tests once
- Run in watch mode during development
- Run with coverage report (enforces coverage threshold)

Check the project's package manager scripts or test runner documentation for exact commands.

## File Organization

Tests should mirror the source structure. Common patterns:

**Option 1: Co-located tests**
```
src/
├── module/
│   ├── feature.ts
│   └── feature.test.ts
```

**Option 2: Separate test directory**
```
src/
├── module/
│   └── feature.ts
└── test/
    └── module/
        └── feature.test.ts
```

**Backend projects often use:**
```
backend/
├── app/
│   └── module/
│       └── service.py
└── tests/
    └── module/
        └── test_service.py
```

- Test file naming: `<source-file-name>.test.<ext>` or `test_<source-file-name>.<ext>`
- Mirror the source directory structure
- Test setup/fixtures in a dedicated setup file or conftest

## What to Test

### Always Test

| Category | Examples |
|----------|---------|
| **Pure functions** | Formatters, validators, transformers, utility helpers |
| **State management** | Store actions, state mutations, derived state, edge cases |
| **Custom abstractions** | Custom hooks, decorators, middleware, utilities |
| **Component/view rendering** | Renders without crashing, displays correct content based on inputs |
| **User interactions** | Click handlers, form submissions, input changes |
| **Conditional logic** | Loading, empty, error, and success states |
| **Edge cases** | Null/undefined inputs, empty collections, boundary values |
| **Accessibility** | Correct ARIA attributes, roles, labels (for UI components) |
| **API contracts** | Request/response shapes, error handling, validation |
| **Business logic** | Service layer functions, domain rules, calculations |

### Never Test

| Category | Why |
|----------|-----|
| Implementation details | Internal state values, private methods — test behavior, not internals |
| Third-party libraries | Trust the library; test your usage, not the library itself |
| Exact styling/CSS classes | Brittle, changes don't affect behavior |
| Snapshot tests | Fragile, noisy diffs, false positives (use sparingly if at all) |
| Type definitions | The type checker handles this at compile/build time |
| Console output | Not user-visible behavior unless it's logging/monitoring specific |

## Writing Tests

### Test Structure

**General pattern (language-agnostic concept):**
```
describe/group tests by module or feature
  describe/group by function/class/component
    setup/teardown hooks to reset state between tests
    
    test case: valid input produces expected output
    test case: edge case handling
    test case: error handling
```

**Example (JavaScript/TypeScript style):**
```typescript
import { describe, it, expect, beforeEach } from '<test-framework>';

describe('ModuleName', () => {
  describe('functionName', () => {
    beforeEach(() => {
      // Reset state between tests
    });

    it('returns expected value for valid input', () => {
      expect(functionName('input')).toBe('expected');
    });

    it('handles edge case', () => {
      expect(functionName('')).toBe('default');
    });

    it('throws for invalid input', () => {
      expect(() => functionName(null)).toThrow();
    });
  });
});
```

**Example (Python style):**
```python
import pytest

class TestModuleName:
    def setup_method(self):
        # Reset state before each test
        pass

    def test_returns_expected_value_for_valid_input(self):
        assert function_name('input') == 'expected'

    def test_handles_edge_case(self):
        assert function_name('') == 'default'

    def test_raises_for_invalid_input(self):
        with pytest.raises(ValueError):
            function_name(None)
```

### Testing Pure Functions

```typescript
// Example: Utility functions
describe('formatCurrency', () => {
  it('formats positive numbers with currency symbol', () => {
    expect(formatCurrency(1234.5)).toBe('$1,234.50');
  });

  it('handles zero', () => {
    expect(formatCurrency(0)).toBe('$0.00');
  });

  it('handles negative numbers', () => {
    expect(formatCurrency(-500)).toBe('-$500.00');
  });
});
```

### Testing State Management

Test stores/state containers by:
1. Verifying initial state
2. Testing actions/mutations
3. Testing derived/computed state
4. Resetting state between tests

```typescript
// Example: Client-side state store
describe('AppStore', () => {
  beforeEach(() => {
    // Reset store to initial state
    store.reset();
  });

  it('has correct initial state', () => {
    const state = store.getState();
    expect(state.currentUser).toBeNull();
  });

  it('updates user via setUser action', () => {
    store.setUser({ id: 1, name: 'Test' });
    expect(store.getState().currentUser).toEqual({ id: 1, name: 'Test' });
  });
});
```

### Testing Components/Views

For UI frameworks, test:
1. Rendering with required props/inputs
2. User interactions (clicks, form submissions)
3. Conditional rendering (loading, empty, error states)
4. Accessibility attributes

```typescript
// Example: UI component testing
describe('ComponentName', () => {
  it('renders with required props', () => {
    render(<ComponentName title="Test" value={42} />);
    expect(screen.getByText('Test')).toBeInTheDocument();
    expect(screen.getByText('42')).toBeInTheDocument();
  });

  it('calls onClick when button is clicked', async () => {
    const handleClick = mockFunction();
    render(<ComponentName onClick={handleClick} />);
    
    await userInteraction.click(screen.getByRole('button'));
    expect(handleClick).toHaveBeenCalledOnce();
  });

  it('shows empty state when no data', () => {
    render(<ComponentName data={[]} />);
    expect(screen.getByText(/no.*found/i)).toBeInTheDocument();
  });
});
```

### Testing API/Service Layer

For backend services and API clients:

```python
# Example: Backend service testing
class TestUserService:
    async def test_create_user_with_valid_data(self, db_session):
        payload = {"email": "test@example.com", "password": "secure123"}
        user = await user_service.create_user(db_session, payload)
        
        assert user.id is not None
        assert user.email == "test@example.com"
        # Never leak sensitive fields in responses
        assert not hasattr(user, 'password')
    
    async def test_create_user_duplicate_email_raises_conflict(self, db_session):
        payload = {"email": "test@example.com", "password": "secure123"}
        await user_service.create_user(db_session, payload)
        
        with pytest.raises(ConflictError):
            await user_service.create_user(db_session, payload)
```

## Query/Selection Priority (UI Testing)

When testing UI components, use the most accessible/semantic selector first:

| Priority | Method | When |
|----------|--------|------|
| 1 | By role | Buttons, headings, links, form elements (semantic HTML) |
| 2 | By label | Form inputs with labels |
| 3 | By text content | Non-interactive text |
| 4 | By current value | Form input values |
| 5 | By test ID | Last resort — add `data-testid` or similar attribute |

**Never query by CSS class, tag name, or DOM structure.** These are implementation details.

## Mocking

### Module/Import Mocks

Mock external dependencies at module boundaries:

```typescript
// Mock an entire module
mock('@/external/service');

// Mock with custom implementation
mock('@/lib/utils', () => ({
  formatCurrency: mockFn((v: number) => `$${v}`),
}));
```

```python
# Mock with pytest/unittest
from unittest.mock import patch, MagicMock

@patch('app.external.service.make_api_call')
def test_service_with_mocked_api(mock_api_call):
    mock_api_call.return_value = {'status': 'ok'}
    # test code
```

### State Store Mocks

```typescript
// Mock state container/store
mock('@/stores/appStore');

beforeEach(() => {
  mockedStore.mockImplementation((selector) =>
    selector({
      currentUser: { id: 1, name: 'Test' },
      logout: mockFn(),
    })
  );
});
```

### Time/Timer Mocks

For testing debouncing, throttling, or time-dependent behavior:

```typescript
beforeEach(() => {
  useFakeTimers();
});

afterEach(() => {
  useRealTimers();
});

it('debounces input', () => {
  // trigger input
  advanceTimersByTime(300);
  // assert debounced result
});
```

## Rules

1. **Write tests for every new function, module, and component** — no exceptions
2. **Run coverage checks before finishing work** — all metrics must meet the threshold
3. **Test behavior, not implementation** — assert what the user/caller sees, not internal state
4. **One assertion concept per test** — multiple assertions are fine if they test the same concept
5. **Use descriptive test names** — `it('shows error message when form is invalid')` not `it('test 3')`
6. **Mock at boundaries** — mock external APIs, stores, and I/O; not internal functions
7. **Reset state between tests** — use setup/teardown hooks to clear mocks and reset state
8. **No test interdependence** — each test must pass in isolation and in any order
9. **Cover edge cases** — empty collections, null values, boundary numbers, long strings
10. **Cover all branches** — if there's an `if/else`, test both paths; if there's a switch, test all cases
11. **For multi-tenant systems** — test tenant/authorization scoping on every query/operation that should be scoped

## Adding Tests for Bug Fixes

When fixing a bug:

1. **Write the failing test first** — reproduce the bug in a test
2. **Verify it fails** — confirm the test catches the actual bug
3. **Fix the bug** — make the test pass
4. **Keep the test** — it prevents regression

```typescript
// Example: Bug #123 — formatCurrency returns NaN for undefined
it('handles undefined input without NaN (bug #123)', () => {
  expect(formatCurrency(undefined as unknown as number)).toBe('$0.00');
});
```

## Coverage Report

After running the coverage command:

- Check terminal output for summary of all metrics
- Check the coverage report directory (often `coverage/` or `htmlcov/`) for detailed line-by-line coverage
- Uncovered lines are usually highlighted in the terminal or HTML report

If coverage drops below the threshold on any metric, the test run **fails**. Add tests to cover the gap before committing.

## Stack-Specific Guidance

### Async/Event-Loop Systems

For systems with async I/O or event loops (Node.js, Python asyncio, Go goroutines):
- Mock all I/O operations (database, HTTP, file system)
- Use the test framework's async support (`async/await` in tests)
- Never use blocking I/O in tests for async systems — mock it or use async equivalents

### Multi-Tenant/Authorization Systems

For systems with tenant isolation or fine-grained authorization:
- Every test for a scoped query/operation must verify scoping is correct
- Test cross-tenant access attempts (should fail with 404 or 403)
- Test missing authorization (should fail with 401 or 403)

### API/HTTP Testing

For REST/GraphQL/RPC APIs:
- Test all response status codes (200, 201, 400, 401, 403, 404, 409, 422, 429, 500)
- Test request validation (missing fields, wrong types, out-of-range values)
- Test authentication and authorization
- Test rate limiting if applicable

### Frontend/UI Testing

For component-based UI frameworks:
- Test all UI states: loading, empty, error, success
- Test user interactions with proper event simulation
- Test accessibility (ARIA attributes, keyboard navigation, screen reader support)
- Test responsive behavior if applicable (different viewport sizes)

See `.claude/rules/responsive-and-accessibility.md` for UI-specific accessibility requirements.

## Integration with Workflow

This file defines unit testing standards. Integration and end-to-end testing are covered separately:
- Unit tests run in the development pipeline (lint → type-check → unit tests → build)
- Integration/E2E tests run in the testing phase of the SDLC pipeline (see `.claude/rules/mandatory-workflow.md`)
- Coverage requirements apply to unit tests; integration tests have separate success criteria
