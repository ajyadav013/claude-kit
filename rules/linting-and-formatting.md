# Linting and Formatting Rules

All code MUST pass the project's linter with **zero warnings and zero errors** before committing. The pre-commit hook (if configured) should enforce this.

## Linting Configuration

The project uses a linter configured to enforce code quality, style consistency, and accessibility. Configure enforcement layers appropriate to your stack:

| Layer | Typical Scope | Purpose |
|-------|---------------|---------|
| Base | All source files | Language rules, framework patterns, common anti-patterns |
| Accessibility | UI component files | Accessibility rules for web UIs (e.g., ARIA, keyboard nav, alt text) |
| Design System | Application code (excl. low-level primitives) | Project-specific patterns, banned primitives, import conventions |
| Code Quality | Application code | Code smells, performance, security patterns |

## Zero-Warning Policy

Pre-commit hooks should run the linter with auto-fix enabled and a zero-warning threshold. This means:

- **Errors** block the commit — must be fixed
- **Warnings** also block the commit — must be fixed or suppressed with justification
- Auto-fix corrects what it can (formatting, import order, simple violations) before checking

## Common Linting Rules

These patterns are enforced across many stacks. Adapt to your project's specifics.

### Primitive Bans (error)

Never use low-level primitives directly in application code when higher-level abstractions exist:

**UI Frameworks:**
- Raw HTML form elements outside the UI component library (e.g., `<input>` vs. a typed `Input` component)
- Raw CSS classes outside the design system (e.g., arbitrary color values vs. semantic tokens)

**Backend Frameworks:**
- Raw database queries outside the data-access layer (e.g., string-concatenated SQL vs. query builders)
- Manual JSON parsing outside typed schemas (e.g., raw `JSON.parse()` vs. validation libraries)

### Inline Styles / Magic Values (error)

```typescript
// BAD — blocks commit (example: web UI)
<div style={{ width: '50%' }}>

// GOOD — use design system utilities
<div className="w-1/2">

// EXCEPTION — dynamic values with justification
{/* eslint-disable-next-line no-restricted-syntax -- dynamic chart width from data */}
<div style={{ width: `${percentage}%` }}>
```

```python
# BAD — magic values (example: backend)
if user.age > 65:
    discount = 0.15

# GOOD — named constants
if user.age > SENIOR_AGE_THRESHOLD:
    discount = SENIOR_DISCOUNT_RATE
```

### Banned Patterns (error)

Projects often ban specific patterns that violate design system standards:

**Examples (adapt to your stack):**
- Inconsistent spacing/sizing values outside allowed scales
- Direct imports of internal modules bypassing public API barrels
- Reserved sentinel values in enums or special fields
- Low-contrast color combinations violating accessibility standards

### Abstraction Suggestions (warn)

Linters can suggest higher-level patterns when they detect repetitive code:

| Pattern Detected | Suggestion |
|-----------------|------------|
| Repetitive UI structure | Use a compound component or layout primitive |
| Repeated validation logic | Extract to a reusable validator |
| Duplicated error handling | Use middleware or a wrapper |

These are nudges, not hard blocks. Fix them when reasonable.

## Framework-Specific Hook Rules (if applicable)

For reactive frameworks (React, Vue, Svelte, SolidJS, etc.), enforce hook/reactivity rules:

- **Rules of Hooks/Reactivity**: hooks/signals only at the top level, only in appropriate scopes
- **Exhaustive dependencies**: all reactive dependencies must be declared

### Suppressing Dependency Rules

Only suppress with a comment explaining why:

```typescript
// Example: React
useEffect(() => {
  loadInitialData();
  // eslint-disable-next-line react-hooks/exhaustive-deps -- mount-only: loadInitialData is stable
}, []);
```

```python
# Example: Python async
async def handler():
    await startup_task()
    # pylint: disable=unused-argument -- event is required by framework signature
```

## Accessibility Rules (error, for web UIs)

Projects with web UIs should enforce accessibility rules via linter plugins (e.g., `jsx-a11y`, `vuejs-accessibility`, `svelte-a11y`):

| Rule Category | What It Checks |
|---------------|---------------|
| Alt text | Images must have meaningful `alt` attributes (or `alt=""` for decorative) |
| Anchor validity | Links must have valid `href` or proper role |
| ARIA validity | ARIA attributes and roles must be valid |
| Keyboard accessibility | Interactive elements must be keyboard-accessible (`onClick` pairs with `onKeyDown`/`onKeyUp`, focusable elements) |
| Label association | Form inputs must have associated labels |
| Interactive semantics | Non-interactive elements shouldn't have click handlers without proper roles |

## Suppressing Rules

When you must suppress a rule, always include a justification:

```typescript
// Single line (TypeScript/JavaScript)
// eslint-disable-next-line <rule-name> -- <justification>

// Block (use sparingly)
/* eslint-disable <rule-name> -- <justification> */
// ... code ...
/* eslint-enable <rule-name> */
```

```python
# Single line (Python)
result = unsafe_operation()  # pylint: disable=<rule-name> -- <justification>

# Block (use sparingly)
# pylint: disable=<rule-name> -- <justification>
# ... code ...
# pylint: enable=<rule-name>
```

**Never use blanket `// eslint-disable` or `# pylint: disable` without specifying a rule name.**

## Running the Linter

```bash
# Generic commands — adapt to your project's scripts
<package-manager> run lint              # Check all files
<linter-cli> path/to/file               # Check single file
<linter-cli> --fix src/                 # Auto-fix what's possible
```

For projects with multiple linters (e.g., backend + frontend, or multiple languages):

```bash
# Backend
cd backend && <run backend linter>

# Frontend
cd frontend && <run frontend linter>

# Or unified at root
<package-manager> run lint:all
```

## Formatting

**Auto-formatters** (e.g., Prettier, Black, Ruff format, gofmt) should run before linting, either:
- As part of `--fix` in the linter
- As a separate pre-commit step

**Formatting is not negotiable.** Configure your editor to format on save, or rely on pre-commit hooks. Never commit unformatted code.

## Ignored Paths

Configure the linter to exclude:
- Build output directories (`dist/`, `build/`, `target/`, `.next/`, etc.)
- Generated code (protobuf outputs, ORM migrations, auto-generated clients)
- Vendor/third-party code
- Tooling artifacts (`.claude/worktrees/`, IDE configs, etc.)
- Legacy/deprecated code not under active development

## Integration with Type Checking

For statically-typed languages, the linter should complement (not replace) the type checker:

| Tool | Focus |
|------|-------|
| Type Checker | Type safety, nullability, interface contracts |
| Linter | Code quality, style, anti-patterns, accessibility, design system compliance |

Run both before committing. See `linting-and-formatting.md` for type-checking rules (if applicable to your stack).

## Enforcement

### Pre-Commit Hook
The project should configure a pre-commit hook (e.g., `husky`, `pre-commit`, `lefthook`) to:
1. Format code
2. Run linter with auto-fix
3. Block commit if errors or warnings remain

### CI/CD
The CI pipeline must run linting as a required check:
1. Format check (fail if code is not formatted)
2. Lint check (fail on errors or warnings)
3. Block merge if linting fails

### Code Review
Reviewers must verify:
- [ ] Zero linting errors or warnings
- [ ] Any suppressed rules have clear justifications
- [ ] Design system and accessibility rules are followed
- [ ] No blanket disables without specific rule names
