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

### Security Lint Layer (error)

Treat a class of security mistakes as **lint errors caught pre-commit**, not only as something the
security review (the `security-and-hardening` skill / `security-reviewer` agent) finds later. Linting
catches the mechanical, always-wrong patterns at the cheapest possible moment — at the keystroke,
before the code is even committed — leaving review to focus on the judgment calls. Enable your stack's
security lint plugin and treat its findings as build-breaking. The patterns are stack-agnostic even
though the rule names differ:

| Pattern (banned) | Why |
|------------------|-----|
| Dynamic code execution from data (`eval`, `Function(...)`, `exec`, deserializing untrusted input) | Arbitrary code execution (OWASP A03/A08). |
| Raw-HTML injection sinks (`innerHTML`, `dangerouslySetInnerHTML`, `v-html`, template `\| safe`) without sanitization | XSS. |
| Insecure randomness for security values (`Math.random()`, non-CSPRNG) for tokens/ids/keys | Predictable secrets. |
| Disabled transport security (`NODE_TLS_REJECT_UNAUTHORIZED=0`, `verify=False`, `rejectUnauthorized:false`) | MITM (mirrors `security-and-hardening` *Outbound TLS*). |
| Shell/command construction from interpolated input | Command injection. |

A suppression here follows the same rule as any other (§"Suppressing Rules"): a specific rule name plus
a written justification — never a blanket disable — and a security suppression is worth a second pair
of eyes in review.

> Stack-agnostic adaptation of the security-linting layer in the MIT
> [`microsoft/eslint-plugin-sdl`](https://github.com/microsoft/eslint-plugin-sdl) (SDL security rules as
> enforced lint errors). Re-derived in prose; not vendored — the patterns generalize beyond any one
> linter.

### Compile-Time Logic-Bug Analysis (error)

A style linter checks formatting and idiom; a *type checker* checks types. Between them sits a third,
higher-value layer: **static analyzers that catch real logic bugs the type checker accepts** — code
that compiles and is type-correct but is almost certainly wrong. Examples (stack-agnostic):

- an equality/`==` check that can never be true because the operands are incompatible types;
- a format string whose placeholders don't match its arguments;
- a returned value or `Future`/`Promise` that is silently dropped (forgotten `await`);
- a collection mutated while iterated; a `@CheckReturnValue`/`#[must_use]` result ignored.

Enable your stack's analyzer for this class and treat its findings as build-breaking, distinct from
both the type checker and the security-lint layer above: Error Prone (Java), `clippy` (Rust),
`staticcheck`/`go vet` (Go), type-aware ESLint rules (TypeScript), Infer / clang-analyzer (C/C++),
Pyright/mypy strict + Ruff's bug-prone (`B`) rules (Python). The point is the *category* — "find bugs,
not style" — not any one tool.

> Stack-agnostic adaptation of compile-time logic-bug analysis as a distinct enforcement layer (beyond
> style + type checking) from the Apache-2.0 [`google/error-prone`](https://github.com/google/error-prone).
> Re-derived in prose; not vendored — every major ecosystem has an equivalent analyzer.

### Interprocedural Taint / Data-Flow Analysis (error, for security)

The security-lint layer above catches *single-line* sink patterns (a literal `eval`, a raw `innerHTML`).
It cannot see the dangerous case where untrusted data enters in one function and reaches a sink **several
calls away** — request param → service method → repository → string-built SQL. **Taint analysis** closes
that gap: it tracks data *flow* across function boundaries and flags any path from an untrusted **source**
to a dangerous **sink** that isn't cleaned by a declared **sanitizer**.

- **Model the three roles, then let the tool find the paths.** Declare **sources** (request bodies/params,
  headers, env, file/network/queue input, deserialized data), **sinks** (SQL/NoSQL, shell/`exec`, `eval`,
  file paths, outbound URLs, HTML/templates, log lines for sensitive data), and **sanitizers** (the
  validator/escaper/parameterizer that makes tainted data safe). The analyzer then reports every
  source→sink path with no sanitizer on it — interprocedurally, which point-in-code lint and the
  type checker cannot do.
- **Where it sits in the layers:** *security-lint* (mechanical single-line bans) → *compile-time
  logic-bug* (correctness) → **taint/data-flow** (does untrusted input reach a sink?) → human security
  review (`security-and-hardening` skill / `security-reviewer`). It is the automated, codebase-wide
  complement to the **secure-by-construction typed wrappers** in `security-and-hardening` (which enforce
  the same source/sink discipline *in the type system* at one boundary; taint analysis *discovers* the
  unguarded flows across the whole tree).
- **Run it in CI on a real engine**, treat a new unsanitized flow as build-breaking, and curate the
  source/sink/sanitizer model over time (the model is the high-value artifact). Every ecosystem has an
  engine: Pysa (Python), Mariana Trench (Java/Android), CodeQL or Semgrep (polyglot), and others.

> Stack-agnostic adaptation of interprocedural taint / data-flow analysis (the source → sanitizer → sink
> model) from the MIT [`facebook/pyre-check`](https://github.com/facebook/pyre-check) (Pysa) and
> [`facebook/mariana-trench`](https://github.com/facebook/mariana-trench). Re-derived in prose; not
> vendored — the model generalizes across taint engines.

### License-Header Enforcement (error)

Where the project (or its org) requires source files to carry a copyright + SPDX license header, make
it a **mechanical, enforced check**, not a manual review item: a CI / pre-commit step verifies every
source file has the expected header and **fails the build** on a missing or malformed one (a `--check`
mode that exits non-zero), with an auto-fix mode that inserts the header locally. This keeps license
hygiene from rotting silently as new files are added.

> Stack-agnostic adaptation of license-header enforcement as a check-mode CI/pre-commit gate from the
> Apache-2.0 [`google/addlicense`](https://github.com/google/addlicense). Re-derived in prose; not
> vendored.

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

### Deterministic Block Sorting

Lists that many contributors append to — dependency arrays, import groups, enum/constant lists, config
allowlists — are a recurring source of **merge conflicts** (two branches both append to the end) and of
"is X already here?" scanning cost. Keep such blocks **deterministically sorted** so additions land in a
predictable place and diffs stay minimal. A language-agnostic, marker-comment formatter does this
without needing the surrounding file to be machine-sortable:

```
# keep-sorted start
  alpha
  bravo
  charlie
# keep-sorted end
```

The tool re-sorts only between the markers (with options for grouping, case, and numeric ordering) and
runs in the same pre-commit / CI auto-fix step as the formatter. Apply it to frequently-edited lists;
don't impose it on sequences whose order is meaningful.

> Stack-agnostic adaptation of marker-comment deterministic block sorting (reduce merge conflicts on
> append-heavy lists) from the Apache-2.0 [`google/keep-sorted`](https://github.com/google/keep-sorted).
> Re-derived in prose; not vendored.

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
