# react-hook-form-zod-patterns

Production-grounded skill for building type-safe React forms using react-hook-form with Zod schema validation.

## What this covers

- **useForm setup** with zodResolver for schema-driven validation
- **Zod schemas** with `.strict()`, `.refine()`, and cross-field validation
- **Reusable validation rules** (password strength, email/phone patterns)
- **Field registration** via `{...register('field')}` and error display
- **Multi-step forms** with separate useForm instances per step
- **Mode switching** (password vs OTP login, create vs edit) with field syncing
- **Conditional validation** by form mode (create vs update schemas)
- **formState.errors** and **formState.isDirty** for UI state
- **reset()**, **getValues()**, **setValue()** for form lifecycle
- **TypeScript types** derived from Zod schemas via `z.infer<typeof schema>`

## Origin

Derived from real production React frontends implementing authentication flows, profile management, and multi-step onboarding.

## Key trade-offs

- **Schema-driven validation**: Zod is the single source of truth for validation rules and TypeScript types—no separate interfaces or manual validation logic.
- **Separate useForm per step**: Multi-step forms maintain separate form instances per step (e.g., signup details → OTP verification) rather than a single shared instance.
- **Mode switching**: Forms with multiple modes (password vs OTP login, view vs edit) use separate useForm instances and sync shared fields via `setValue` when switching.
- **Error display**: Field-level errors are displayed inline via an `error` prop on Input components, not generic top-level messages.

## Anti-patterns

See [SKILL.md](SKILL.md) for the full list, including:
- Defining form types separately from schemas (use `z.infer`)
- Sharing a single useForm across unrelated steps
- Not using `.refine()` for cross-field validation
- Not resetting form after successful submit
- Duplicating validation regex across components

## References

- `references/form-setup-and-zod.md` — useForm setup, zodResolver, and schema definition
- `references/multi-step-and-modes.md` — multi-step forms and mode switching patterns
- `references/repo-evidence.md` — genericized snippets from production services
