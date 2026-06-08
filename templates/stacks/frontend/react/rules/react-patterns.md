# React frontend patterns

Stack-specific conventions for the frontend. This overlay is installed into `.claude/rules/` only
when the **React · TypeScript · Vite** stack is selected. Read the generic
`.claude/rules/frontend-best-practices.md`, `.claude/rules/code-organization.md`, and
`.claude/rules/responsive-and-accessibility.md` first; this file makes them concrete for React.

## Stack

- **React 19** + **TypeScript** (strict), **Vite** build/dev server.
- Data: a shared **Axios** instance (`src/api/client.ts`); typed API modules under `src/api/`.
- Tests: **Vitest** + **React Testing Library** + **@testing-library/jest-dom**, jsdom environment.
- Tooling: **ESLint 9** (flat config), `tsc --noEmit` for type checking.

All commands run from the `frontend/` directory:

| Task | Command |
|------|---------|
| Install | `npm install` |
| Run | `npm run dev` |
| Test | `npm run test` |
| Lint | `npm run lint` |
| Type-check | `npm run typecheck` |
| Build | `npm run build` |

## Architecture

```
src/
  api/client.ts          one configured Axios instance (base URL, headers, interceptors)
  api/<resource>.ts      typed request functions (one module per resource)
  types/<resource>.ts    shared types — mirror the backend response/request schemas
  features/<feature>/    a folder per feature:
    use<Feature>.ts        data hook: state + fetching + actions
    <Feature>Page.tsx      presentational component (renders the hook's data)
    <Feature>Page.test.tsx component tests with the API module mocked
  test/setup.ts          jest-dom matcher registration
```

Rules of thumb:
- **Container/presentational split.** Data fetching and state live in a hook (`use<Feature>`);
  components render props/hook output and own only local UI state (form fields, toggles).
- **Never call `axios` directly.** Import `apiClient` from `src/api/client.ts` so base URL and
  headers are configured once. Put request functions in `src/api/<resource>.ts`, fully typed.
- **Types mirror the backend.** Keep `src/types/<resource>.ts` in sync with the backend schemas
  (`ItemRead` -> `Item`, `ItemCreate` -> `ItemCreate`). A field added on the backend is added here —
  and in any test fixtures/mocks that build that type (`tsc --noEmit` flags the ones you miss).
- **Config via env.** Read backend URLs from `import.meta.env.VITE_*` (declared in
  `src/vite-env.d.ts`). Never hard-code hosts in components.
- **Accessibility.** Label inputs (`aria-label` or `<label>`), use `role="alert"` for errors, and
  give actionable controls accessible names — tests select by role/label, which enforces this.

## Adding a feature (the recipe)

The `items` feature is the worked example. To add `<feature>`:

1. **Types** — `src/types/<feature>.ts`, matching the backend schema.
2. **API** — `src/api/<feature>.ts`: typed functions using `apiClient`.
3. **Hook** — `src/features/<feature>/use<Feature>.ts`: state + fetching + actions.
4. **Component** — `src/features/<feature>/<Feature>Page.tsx`: presentational; consumes the hook.
5. **Wire it in** — render the page from `App.tsx` (or the router, once one is added).
6. **Tests** — `<Feature>Page.test.tsx`: `vi.mock('../../api/<feature>')`, then assert rendering,
   the empty state, and the create/update flow. Select by role/label, not test ids.

## Conventions

- **Type everything.** No `any`; exported functions and hooks have explicit return types and
  doc comments per `.claude/rules/documentation.md`. `npm run typecheck` and `npm run lint` pass.
- **Keep tests behavioral.** Mock the API module, drive the UI with `@testing-library/user-event`,
  and assert what the user sees. Don't assert implementation details.
- **Small components.** If a component grows past one responsibility, split it; move shared logic
  into a hook.
