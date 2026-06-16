# React frontend patterns

Stack-specific conventions for the frontend. This overlay is installed into `.claude/rules/` only
when the **React** frontend is selected. Read the generic
`.claude/rules/frontend-best-practices.md`, `.claude/rules/code-organization.md`, and
`.claude/rules/responsive-and-accessibility.md` first; this file makes them concrete for React.

## Stack

- **React** + **TypeScript** (strict), a modern build/dev server (Vite or your project's choice).
- Data: a shared HTTP client instance (e.g. `src/api/client.ts`); typed API modules under `src/api/`.
- Tests: a component testing stack (Vitest/Jest + React Testing Library + `@testing-library/jest-dom`).
- Tooling: ESLint (flat config) and `tsc --noEmit` for type checking.

Run the project's own scripts for these tasks (see the **Commands** section of `CLAUDE.md`):
install, run/dev, test, lint, type-check, build.

## Architecture

```
src/
  api/client.ts          one configured HTTP client instance (base URL, headers, interceptors)
  api/<resource>.ts      typed request functions (one module per resource)
  types/<resource>.ts    shared types — mirror the backend response/request schemas
  features/<feature>/    a folder per feature:
    use<Feature>.ts        data hook: state + fetching + actions
    <Feature>Page.tsx      presentational component (renders the hook's data)
    <Feature>Page.test.tsx component tests with the API module mocked
  test/setup.ts          test matcher registration + cleanup
```

Rules of thumb:
- **Container/presentational split.** Data fetching and state live in a hook (`use<Feature>`);
  components render props/hook output and own only local UI state (form fields, toggles).
- **Never call the HTTP library directly.** Import the shared client so base URL and headers are
  configured once. Put request functions in `src/api/<resource>.ts`, fully typed.
- **Types mirror the backend.** Keep `src/types/<resource>.ts` in sync with the backend schemas.
  A field added on the backend is added here — and in any test fixtures/mocks that build that type
  (`tsc --noEmit` flags the ones you miss).
- **Config via env.** Read backend URLs from build-time env (e.g. `import.meta.env.VITE_*`), declared
  in the env typings. Never hard-code hosts in components.
- **Accessibility.** Label inputs (`aria-label` or `<label>`), use `role="alert"` for errors, and
  give actionable controls accessible names — tests select by role/label, which enforces this.

## Adding a feature (the recipe)

1. **Types** — `src/types/<feature>.ts`, matching the backend schema.
2. **API** — `src/api/<feature>.ts`: typed functions using the shared client.
3. **Hook** — `src/features/<feature>/use<Feature>.ts`: state + fetching + actions.
4. **Component** — `src/features/<feature>/<Feature>Page.tsx`: presentational; consumes the hook.
5. **Wire it in** — render the page from `App.tsx` (or the router).
6. **Tests** — `<Feature>Page.test.tsx`: mock the API module, then assert rendering, the empty
   state, and the create/update flow. Select by role/label, not test ids.

## Conventions

- **Type everything.** No `any`; exported functions and hooks have explicit return types and doc
  comments per `.claude/rules/documentation.md`. Type-check and lint must pass.
- **Keep tests behavioral.** Mock the API module, drive the UI like a user, and assert what the user
  sees — not implementation details. When testing-library cleanup is not automatic, register an
  explicit `afterEach(cleanup)` in `test/setup.ts`.
- **Small components.** If a component grows past one responsibility, split it; move shared logic
  into a hook.

## Accessibility specifics (Tailwind + Radix)

The generic WCAG technique lives in `.claude/rules/responsive-and-accessibility.md` and the
`accessibility-review` skill. These are the React/Tailwind/Radix specifics that overlay carries
(assuming this overlay's Tailwind + Radix styling stack — see `design-system-compliance.md`):

- **Text contrast.** WCAG AA needs **4.5:1** for normal text (3:1 for large/bold ≥18.66px). On a
  white background, the muted Tailwind grays fall out roughly as:

  | Class | ≈ ratio on white | Verdict for body text |
  |---|---|---|
  | `text-gray-400` | ~3.0:1 | **FAIL** — never for body copy |
  | `text-gray-500` | ~4.6:1 | borderline pass — ok for secondary, not ideal |
  | `text-gray-600`+ | ≥7:1 | safe |

  Use `text-gray-600`/`700` for body, reserve `text-gray-500` for genuinely secondary text, and don't
  use `text-gray-400` (or lighter) for anything a user must read.
- **Touch targets without shrinking the visual.** A control's hit area should be ≥44px even when the
  icon is small — expand the padding and pull it back with a negative margin so layout is unchanged:
  `className="p-3 -m-3"` on the clickable element. Pad the hit area; never shrink it. (See the
  touch-target guidance in `.claude/rules/responsive-and-accessibility.md`.)
- **Clickable non-buttons.** Prefer a real `<button>`. If you must make a `<div>`/`<span>` clickable,
  it needs all three: `role="button"`, `tabIndex={0}`, and an `onKeyDown` that fires on `Enter` and
  `Space` — an `onClick` alone is unreachable by keyboard. Give it a dynamic `aria-label` when the
  visible text isn't descriptive.
- **Don't re-flag accessible primitives.** Components from `@/components/ui` (shadcn) and Radix
  primitives already manage focus, keyboard, and ARIA — don't add redundant handlers or report them
  as findings. *Do* flag raw `<div onClick>` and unlabeled icon-only buttons.

## Which tests to run for a change

Route by what changed (run the project's test command scoped to the area; see `CLAUDE.md` Commands):

| Changed | Run |
|---|---|
| a hook (`use<Feature>`) | that feature's hook/unit tests |
| a component | that component's tests |
| a shared type / API module | the components consuming it **and** the contract checks (`tsc --noEmit` + fixtures) |
| cross-cutting (client, providers) | the full frontend suite |

## Contract fixtures (keeping types in sync with the backend)

The backend speaks **snake_case** (see `fastapi-patterns.md`); mirror that exactly in
`src/types/<resource>.ts` — don't remap to camelCase. If the project validates API responses at the
boundary with a schema library (e.g. Zod), make the schema **strict** so an unexpected, missing, or
retyped field is rejected rather than silently passed:

- Use the recursive/strict form (e.g. Zod `.strict()`), not a top-level shape that ignores extra keys.
- Match optionality precisely — `.nullable()` vs `.optional()`, and `z.literal(...)`/`z.enum([...])`
  for closed sets — so a server-side enum or nullability change fails the parse.
- Parse representative fixtures in your component tests so a backend contract change surfaces as a
  failing frontend test (the drift the `test-plan-review` skill warns about).
