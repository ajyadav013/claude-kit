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
- **Wait on conditions, never on the clock.** A fixed delay ("sleep" to let the async work finish)
  is the single biggest source of flaky tests — too short and it fails under load, too long and it
  drags out the whole suite. Instead, **poll for the observable condition you actually care about**
  (the value, state, or side effect) and continue the instant it holds:
  - Use your framework's condition waiter — e.g. `waitFor` / `expect.poll` (JS), `Awaitility` (JVM),
    `tenacity` or a polling fixture (Python), `Eventually` (Go) — or a small generic
    `wait_for(condition, timeout)` that re-checks the live value on a short interval.
  - Three mistakes that quietly re-introduce flakiness: (1) **no timeout** — the test hangs forever
    instead of failing; (2) **interval too tight** — a busy-loop that pegs the CPU; (3) **stale
    reads** — re-evaluate the live value on every poll, never assert against a snapshot captured once.

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

## Parameterized / Table-Driven Tests

When the *same* assertion logic runs across many input/expectation pairs, don't copy-paste the test
body — drive one test template from a table of cases. It cuts duplication, makes the covered cases
visible at a glance, and makes adding a case a one-line change. Use your framework's mechanism:
`@pytest.mark.parametrize` (Python), `it.each` / `test.each` (Jest/Vitest), JUnit `@ParameterizedTest`,
Go table-driven subtests (`for _, tc := range cases { t.Run(... ) }`), RSpec shared examples.

```python
@pytest.mark.parametrize("raw, expected", [
    (1234.5, "$1,234.50"),   # positive
    (0,      "$0.00"),       # zero
    (-500,   "-$500.00"),    # negative
])
def test_format_currency(raw, expected):
    assert format_currency(raw) == expected
```

- **Name each case** (or include the input in the assertion message) so a failure says *which* row
  failed, not just "case 3."
- Reach for it especially on pure functions, validators, and boundary tables (see *Cover edge cases*).

> Stack-agnostic adaptation of parameterized/table-driven testing (one template, many input/expectation
> rows) from the Apache-2.0 [`google/patrick`](https://github.com/google/patrick). Re-derived in prose;
> not vendored — the pattern is supported natively across test frameworks.

## Semantic Equality and Structured Assertions

Asserting deep equality with the default operator is brittle: floating-point results need *tolerance*,
some fields are legitimately unordered, and a raw "expected != actual" failure on a big struct is
unreadable. Assert on the *meaning*, and surface a readable diff:

- **Use tolerant comparison for floats** (`abs(a-b) < eps` / `pytest.approx` / `assertAlmostEqual`),
  and define explicit equality for domain types (NaN handling, set-vs-list, ignore server-set
  timestamps/ids) rather than comparing raw representations.
- **Prefer a structured diff** on failure — assert with a matcher that prints *what differs*
  (field-by-field), not two opaque blobs. Most ecosystems have one (`assertEqual` deep-diff,
  `jest`'s object diff, `deepdiff` in Python, custom comparers).
- **Don't snapshot-compare to dodge this** — a tolerant, intention-revealing comparator beats a
  brittle golden file (see *Never Test → Snapshot tests*).

> Stack-agnostic adaptation of semantic-equality testing (custom comparators with float tolerance /
> domain equality, structured diffs over raw deep-equality) from the BSD-3-Clause
> [`google/go-cmp`](https://github.com/google/go-cmp). Re-derived in prose; not vendored.

## Fuzzing (and continuous fuzzing in CI)

Example-based and even property-based tests (see the property-based testing section in
`.claude/skills/test-driven-development`) only exercise inputs you *thought of*. **Fuzzing** generates
inputs you didn't — it mutates a seed corpus under **coverage feedback**, steering toward new code
paths, and flags any input that crashes, hangs, or trips an assertion/sanitizer. It is the highest-value
technique for code that parses or decodes **untrusted input** (parsers, deserializers, protocol/codec
handlers, anything taking bytes from the network or a file) and complements the ReDoS / input-validation
hardening in `.claude/skills/security-and-hardening`.

- **Write a fuzz target:** a single entry point that takes an arbitrary byte string / structured input
  and feeds it through the code under test. Most ecosystems ship a coverage-guided fuzzer — Go
  `testing.F`, Rust `cargo-fuzz`, Python `atheris`, JS `jazzer.js`, JVM `Jazzer`, C/C++ libFuzzer/AFL++.
- **Seed and grow a corpus.** Start from valid example inputs; the fuzzer evolves them. Keep the corpus
  (and any crash reproducers) in the repo so findings are reproducible and regressions are caught.
- **Structure-aware fuzzing for structured inputs.** For inputs behind a schema (protobuf, JSON Schema,
  a typed AST), generate *semantically valid* inputs from the schema so the fuzzer spends its budget on
  logic, not on getting past the parser.
- **Make it continuous, as a CI gate.** Run a short, code-change-scoped fuzz pass on each PR (catches
  regressions cheaply — a few minutes), and a longer batch run on a schedule to build the corpus and
  reach deeper bugs. Every crash becomes a regression test. (Wire the PR pass into CI with the
  `.claude/skills/ci-cd-and-automation/SKILL.md` skill alongside lint/test.)

> Stack-agnostic adaptation of coverage-guided fuzzing and **continuous fuzzing as a CI gate**
> (PR-scoped code-change runs + scheduled batch + corpus/crash management) from the Apache-2.0
> [`google/atheris`](https://github.com/google/atheris),
> [`google/honggfuzz`](https://github.com/google/honggfuzz), and
> [`google/clusterfuzzlite`](https://github.com/google/clusterfuzzlite). Re-derived in prose; not
> vendored — the discipline maps onto each ecosystem's native fuzzer.

## Parallel Execution and Flakiness Detection

As a suite grows, two things matter beyond correctness: it must run **fast** and it must be
**deterministic**.

- **Run tests in parallel.** Shard across workers (≈ CPU cores) — most runners do this with a flag
  (`pytest -n auto`, `go test` package parallelism + `t.Parallel()`, `jest`/`vitest` default workers).
  Parallelism is only safe if tests are **isolated**: no shared mutable global, DB row, temp file, or
  port between tests (see *No test interdependence*). Flakiness that appears *only* under parallelism is
  a hidden shared-state bug — fix the isolation, don't serialize to hide it.
- **Hunt flakiness deliberately.** A test that passes 99 % of the time is a latent failure. Periodically
  **repeat** the suite (or a suspect test) many times and treat any nondeterministic result as a defect
  to fix, not a flake to retry. Run with repetition and randomized ordering (`--count=N` /
  `pytest-repeat` / `--shuffle`) so order-dependence and timing races surface in CI, not in production.
- The usual root causes: time/clock assumptions (use the condition-waiting discipline in *Async/
  Event-Loop Systems*, never `sleep`), order dependence, shared fixtures, and unawaited async work.

> Stack-agnostic adaptation of parallel test sharding + repeated-run flakiness detection from the
> Apache-2.0 [`google/gtest-parallel`](https://github.com/google/gtest-parallel). Re-derived in prose;
> not vendored.

## Deterministic Simulation Testing (concurrency & distributed-system bugs)

Fuzzing and property-based testing explore *inputs*; they don't reliably find **concurrency and
distributed-system** bugs — races, message reordering, partition-then-heal, crash-at-the-wrong-moment —
because those depend on *timing and interleaving*, which a normal test run can't control or reproduce.
A race that shows up once in 10,000 runs is undebuggable when you can't replay the run that failed.

**Deterministic simulation testing (DST)** makes those bugs reproducible: run the system (or a seam of
it) inside a simulation where **every source of nondeterminism is injected from a single seed**, so the
same seed replays the same execution bit-for-bit.

- **Funnel all nondeterminism through injectable seams.** Time/clock, random numbers, thread/task
  scheduling, network, and disk I/O must come from interfaces the test controls — not from the OS
  directly. This is an **architecture requirement** (dependency-inject the clock, the RNG, the
  transport), and it's the main cost of DST; design for it up front on systems that need it.
- **Drive it from one seed, in virtual time.** A single-threaded scheduler advances a *logical* clock
  and chooses the next event, so there's no wall-clock waiting and no real concurrency — yet it exercises
  real interleavings. The seed *is* the reproduction: a failing seed replays identically every time, and
  goes straight into the suite as a regression test.
- **Inject faults aggressively (the "buggify" idea).** Within the simulation, randomly kill and restart
  processes, partition and heal the network, delay/reorder/drop messages, fail disk writes, and skew
  clocks — at decision points seeded by the run. Searching the fault space deterministically surfaces, in
  minutes, edge cases that would take months of real-cluster runtime to hit.
- **Scope it.** DST earns its architectural cost for **stateful concurrent/distributed** components
  (consensus, replication, schedulers, queues, transaction logic). *Skip (note why in `CONTINUITY.md`)*
  for stateless request/response code and pure functions — fuzzing + property-based testing cover those.

It complements, not replaces, the techniques above (fuzzing = untrusted-input crashes; property-based =
invariants over inputs; DST = interleaving/fault bugs in stateful systems) and the *real*-environment
fault injection of chaos engineering (`.claude/rules/resilience-engineering.md`).

> Stack-agnostic adaptation of deterministic simulation testing (single-seed control of all
> nondeterminism, single-threaded virtual-time scheduling, aggressive in-sim fault injection) from the
> Apache-2.0 [`apple/foundationdb`](https://github.com/apple/foundationdb). Re-derived in prose; not
> vendored — the discipline applies to any system whose IO/time/scheduling can be made injectable.

## Integration with Workflow

This file defines unit testing standards. Integration and end-to-end testing are covered separately:
- Unit tests run in the development pipeline (lint → type-check → unit tests → build)
- Integration/E2E tests run in the testing phase of the SDLC pipeline (see `.claude/rules/mandatory-workflow.md`)
- Coverage requirements apply to unit tests; integration tests have separate success criteria
