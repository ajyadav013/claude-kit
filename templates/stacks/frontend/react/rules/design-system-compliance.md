# Design-system compliance (React + Tailwind + Radix)

Stack-specific design-system enforcement for the frontend. Installed into `.claude/rules/` only when
the **React** frontend is selected; it complements `react-patterns.md`,
`.claude/rules/responsive-and-accessibility.md`, and the `ui-ux-design` skill (the agnostic
design-review technique). This file is about **consistency**: make every screen look like it came from
one system, by going through tokens and shared primitives instead of one-off styling.

> The full token / component / pattern catalog is **`ui-design-system.md`** (with `ux-patterns.md` for
> usage rules and `mobile-design-guidelines.md` for responsive/native) — all installed alongside this
> file in `.claude/rules/`. Those are the source of truth; this file is the short, always-on
> **enforcement** hook. If anything here ever conflicts with `ui-design-system.md`, that file wins.

## Use tokens, never arbitrary values

- Reference the configured theme/palette names (`bg-primary`, `text-muted-foreground`, …) — **do not**
  ship Tailwind arbitrary values like `bg-[#5347CD]`, `rounded-[7px]`, `p-[13px]`. An arbitrary value
  in a component is a design-system bypass and a review finding.
- Pin the palette once in the Tailwind theme config (`@theme`); components consume the names. The
  actual token values and the full color / spacing / typography / radius scales are defined in
  **`ui-design-system.md`** — set them there, then reference the names everywhere.

## One set of component variants

- Buttons, inputs, badges, etc. come from the shared UI primitive layer (`@/components/ui`, Radix/
  shadcn) — don't hand-roll a one-off styled `<button>`. Use the variant prop, not bespoke classes:

  | Variant | Use for |
  |---|---|
  | primary / default | the main action on a view (one per view) |
  | secondary | supporting actions |
  | ghost / outline | low-emphasis / toolbar actions |
  | destructive | irreversible/danger actions |

  If a needed variant doesn't exist, add it to the primitive — don't fork its styling inline.

## Radius, spacing, and icons are scales

- Use the spacing/radius **scale** (`rounded-md`, `p-4`), never arbitrary one-offs — consistency comes
  from reusing the steps.
- One icon library (e.g. Lucide), at a small fixed set of sizes (e.g. `size-4` / `size-5`); don't mix
  icon sets or scatter custom pixel sizes.

## Conditional classes go through `cn()`

Merge/condition classes with the project's `cn()` helper (clsx + tailwind-merge) so later utilities
win predictably and duplicates collapse:

```tsx
<button className={cn("rounded-md px-3 py-2", isActive && "bg-primary text-white", className)} />
```

Don't build class strings with template literals and manual `&&` — that's how conflicting utilities
(`px-2 px-4`) silently ship.

## Decide light/dark scope explicitly

State whether the app is light-only, dark-only, or themed, and hold to it. If light-only, don't leave
stray `dark:` variants; if themed, every surface/foreground pair must be defined for both. Half-themed
UIs are a common source of unreadable contrast — which also trips the accessibility rules in
`react-patterns.md`.

## Review hook

When reviewing UI against this system, flag: arbitrary Tailwind values, hand-rolled components that
duplicate a primitive, off-scale radius/spacing, mixed icon sizes/sets, manual class concatenation,
and theme-scope leaks. Severity per `.claude/rules/quality-gates.md`; the broader UX/visual review
stays in the `ui-ux-design` skill.
