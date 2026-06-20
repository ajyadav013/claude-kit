# Radix + Tailwind Component Patterns

Design-system components built from Radix UI headless primitives with custom Tailwind styling (manual integration, not shadcn CLI).

## Coverage

This skill documents production patterns for:

- **Variant-driven component APIs**: Button, Badge, Alert with primary/secondary/outline/ghost/destructive variants and sm/md/lg sizes
- **Radix primitive wrappers**: Dialog, Select, Dropdown Menu, Switch, Tabs, Toast, Tooltip with custom styling
- **Tailwind v4 @theme tokens**: --color-*, --radius-*, --font-* design tokens in index.css
- **cn() utility**: twMerge + clsx for conditional class merging
- **asChild / Slot polymorphism**: polymorphic rendering pattern from @radix-ui/react-slot
- **data-state animations**: data-[state=open]/data-[state=closed] styling with animate-in/out classes
- **Mobile-responsive patterns**: BottomSheet on mobile, Popover on desktop for Select/Dropdown
- **Accessibility**: focus-visible rings, prefers-reduced-motion, safe area insets
- **Custom Tailwind variants**: pointer-fine/pointer-coarse for touch vs mouse detection

## Origin

Derived from real production frontend services using:
- Radix UI primitives v1.x (Dialog, Select, Dropdown Menu, Switch, Tabs, Toast, Tooltip)
- Tailwind CSS v4 with @theme {} design tokens
- React 18+ with TypeScript
- clsx + tailwind-merge for className composition

All examples are genericized — no internal service names, repos, or company-specific branding.

## Use cases

- Building a custom design system from Radix primitives without shadcn CLI scaffolding
- Migrating to Tailwind v4 @theme tokens from tailwind.config.js theme extension
- Implementing variant-based component APIs with TypeScript safety
- Creating mobile-responsive components (BottomSheet on touch, Popover on desktop)
- Setting up accessibility-first components (focus-visible, reduced motion, safe areas)

## Cross-references

- **frontend-repo-architecture**: where `src/components/ui/` lives in the project structure
- **frontend-ui-engineering**: broader UI patterns (this skill focuses on the Radix+Tailwind integration layer)
