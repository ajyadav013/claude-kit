# Frontend Best Practices

These rules are enforced on all code generated or modified by Claude agents in this project.

## Naming Conventions

### Variables & Functions
- Use the project's established casing convention for variables and functions (commonly `camelCase`)
- Use descriptive names that convey intent: `totalRevenue` not `tr`, `handleApproval` not `ha`
- Boolean variables use `is/has/should/can` prefix: `isLoading`, `hasError`, `canApprove`
- Event handlers use `handle<Event>` pattern: `handleClick`, `handleFilterChange`, `handleSubmit`
- No single-letter variables except loop iterators (`i`, `j`, `k`)

### Components & Types
- Components: follow the project's component naming convention (commonly `PascalCase`)
- Types & interfaces: follow the project's type naming convention (commonly `PascalCase`)
- Enums: follow the project's enum convention
- Generic type parameters: single uppercase letter (`T`, `K`, `V`) or descriptive (`TItem`, `TResponse`)

### Files
- Components: follow the project's file naming convention (e.g., `PascalCase.tsx`, `PascalCase.jsx`, `ComponentName.vue`)
- Hooks: follow the project's hook naming pattern (e.g., `use<Name>.ts`, `use<Name>.js`)
- Utilities: follow the project's utility organization pattern (check for centralized utility files before creating new ones)
- Mock data: co-locate with the feature or centralize as per project convention
- Test files: follow the project's test file pattern (e.g., `<Component>.test.tsx`, `<Component>.spec.ts`)
- Pages/Views: follow the project's page/view naming convention

### Routes
- Use the project's established route naming pattern (commonly `kebab-case` or `snake_case`)
- Use nouns: `/items` not `/view-items`
- Plurals for lists, singular for detail: `/items` -> `/items/:id`

### Constants
- True constants: follow the project's constant naming convention (commonly `UPPER_SNAKE_CASE`)
- Config objects: follow the project's config naming convention (commonly `camelCase`)

## Code Quality

### Type Safety
- Avoid untyped values — use the project's type system to its fullest
- Explicit return types on all exported functions
- Use type-only imports where the language/tooling supports it
- Prefer appropriate type constructs for different scenarios (object shapes vs unions vs utilities)

### Functions
- Maximum ~50 lines per function; extract helpers for longer logic
- Use early returns to reduce nesting
- No nested ternaries — use `if/else` or extract to a variable
- No magic numbers — extract to named constants with context

### Error Handling
- Only validate at system boundaries (user input, API responses)
- Use the project's validation library for runtime validation
- Don't wrap internal code in try/catch unless there's a meaningful recovery

### Console & Debugging
- No debug logging in committed code
- Use appropriate error logging only for genuine errors that need visibility in production
- Remove all debugging artifacts before committing

## Reusable Patterns

### Custom Hooks (or equivalent composables/utilities)
- Extract shared stateful logic into reusable units following the project's pattern
- Return stable references (use memoization for functions returned from hooks/composables)
- Keep hooks/composables focused — one concern per unit

### Compound Components
- Always use existing compound components from the project's component library
- Never inline the layout that a compound component owns
- Check the project's component index/registry for available primitives before building custom

### Higher-Order Components (or equivalent patterns)
- Use sparingly; prefer composition patterns supported by the framework
- Name appropriately following the project convention (e.g., `with<Behavior>`)
- Only use for cross-cutting concerns that wrap component rendering

### Component Composition
- Prefer composition patterns (children props, slots, etc.) over prop drilling
- Use the project's UI library primitives for interactive elements where available
- Keep components pure when possible — derive display values from props

## Import Order

Maintain consistent import ordering in all files following the project's convention. Common pattern:

```typescript
// 1. Framework/runtime imports
import { useState, useCallback } from 'framework';
import { useNavigate, useParams } from 'framework-router';

// 2. Third-party libraries
import { useForm } from 'third-party-lib';
import { z } from 'validation-lib';

// 3. Internal absolute imports (using project's path alias)
import { Button, Badge, Select } from '@/components/ui';
import { cn, formatCurrency } from '@/lib/utils';
import { useFeatureStore } from '@/hooks/useFeatureStore';

// 4. Relative imports
import { FeatureCard } from './FeatureCard';

// 5. Type-only imports (if supported by the language)
import type { FeatureItem } from '@/data/types';
```

## Framework-Specific Patterns

### State Management
- Use the project's state management solution for cross-cutting state; use local component state for UI-only state
- Follow the project's selector pattern when accessing stores (avoid accessing entire store unnecessarily)
- Never create new objects/arrays inside selectors or computed properties (causes infinite loops)
- Store actions are stable references — exclude from dependency arrays where applicable

### Data Fetching
- **Use the project's data-fetching pattern consistently**
- If the project uses a dedicated data-fetching library, all API calls should go through it
- **Never mix patterns** — don't introduce ad-hoc effect-based fetching if a library is in place
- Existing API client functions stay as-is — the data-fetching layer wraps them
- Use query key factories or equivalent cache management patterns for consistent cache behavior
- Use invalidation/refetch mechanisms from the data-fetching library — never manually refetch
- Configure appropriate stale times based on data volatility (reference data vs real-time feeds)
- Global error handling (e.g., 401) lives in the client config — do not add per-query error handling

### Effects (or equivalent lifecycle hooks)
- Mount-only effects: document why the dependency array is intentionally minimal
- Never include stable store actions in dependency arrays
- Use refs for values needed in effects but not as dependencies
- Debounced inputs: depend only on the input value
- **Do not use effects for data fetching** if the project has a dedicated data-fetching library

### Performance
- Use memoization utilities only for demonstrably expensive renders or computations
- Use virtualization libraries for lists > 50 items
- Use code-splitting for route-level lazy loading
- Profile before optimizing — measure actual performance impact

## Error Suppression (Banned)

The following patterns suppress errors instead of fixing them and are **strictly forbidden**:

- Type-system escape hatches (e.g., `any`, `as any`, unsafe casts) — use proper typing or `unknown` with type guards
- Linter disable directives without specific rule names and written justification
- Blanket suppression of entire files or large blocks
- Comment-based suppression of type errors without addressing the root cause

**If you cannot resolve an error properly, STOP and ask the user.**

## Cross-References

For related guidance, see:
- `.claude/rules/code-organization.md` — module structure, file organization
- `.claude/rules/linting-and-formatting.md` — linter/formatter rules, code style
- `.claude/rules/testing.md` — testing standards
- `.claude/rules/responsive-and-accessibility.md` — responsive design, accessibility standards
- `.claude/rules/documentation.md` — documentation requirements
