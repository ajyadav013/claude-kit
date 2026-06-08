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
