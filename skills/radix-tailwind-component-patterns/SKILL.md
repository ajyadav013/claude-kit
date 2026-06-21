---
name: radix-tailwind-component-patterns
description: Design-system components built from Radix UI headless primitives with custom Tailwind styling (manual integration, not shadcn CLI). Covers variant-driven component APIs, the cn() helper (twMerge + clsx), Tailwind v4 @theme design tokens, asChild/Slot polymorphism, data-state animations, and prefers-reduced-motion. Use when building a custom design system from Radix primitives, implementing variant-based components without shadcn, or migrating to Tailwind v4 @theme tokens.
---

Standardize design-system component patterns using Radix UI headless primitives with custom Tailwind styling, variant-driven APIs, and Tailwind v4 @theme design tokens.

## When to use

- Building a custom design system from Radix UI primitives without shadcn CLI
- Implementing variant-based component APIs (primary/secondary/outline/ghost patterns)
- Migrating to or using Tailwind v4 @theme {} for design tokens
- Creating polymorphic components with asChild/Slot pattern
- Wrapping Radix primitives (Dialog, Select, Dropdown, Switch, Tabs, Toast, Tooltip) with project-specific styling
- Setting up the cn() utility for conditional class merging
- Adding data-state-driven animations and respecting prefers-reduced-motion
- Building mobile-responsive components (BottomSheet on mobile, Popover on desktop)
- Cross-linking with frontend-repo-architecture for where ui/ components live

## Core conventions

1. **cn() utility in lib/utils.ts**: combine `clsx` for conditional classes with `tailwind-merge` to deduplicate conflicting Tailwind utilities. Signature: `cn(...inputs: ClassValue[]): string => twMerge(clsx(inputs))`. Import via `import { cn } from '@/lib/utils'` and use in every component's className prop to merge user-provided classes with base styles.

2. **Tailwind v4 @theme {} design tokens**: define brand colors, radii, fonts, and breakpoints in index.css (or global CSS entry) via `@theme { --color-primary-500: #6366f1; --radius-lg: 0.5rem; --font-sans: Inter, sans-serif; }`. Reference in components as `bg-primary`, `text-primary-600`, `rounded-lg`, etc. Tailwind v4 reads these tokens directly; no tailwind.config.js theme extension needed.

3. **Variant-driven component API**: define a `variantStyles: Record<VariantName, string>` map for each variant type (e.g., `primary`, `secondary`, `outline`, `ghost`, `destructive`) and a `sizeStyles: Record<SizeName, string>` map for size variants. Accept `variant` and `size` props, merge the corresponding class strings via `cn(baseStyles, variantStyles[variant], sizeStyles[size], className)`. Example: Button with `variant="primary" size="md"`.

4. **Radix primitive wrapping pattern**: import the Radix primitive (e.g., `@radix-ui/react-dialog`), re-export the Root as-is or with a thin wrapper, and wrap sub-components (Trigger, Content, Overlay, Title, Description) with forwardRef to add custom styles. Always preserve `ref` and `...props` spread. For Dialog: `Dialog = DialogPrimitive.Root`, `DialogTrigger = DialogPrimitive.Trigger`, `DialogOverlay = forwardRef<...>((props, ref) => <DialogPrimitive.Overlay ref={ref} className={cn(...)} {...props} />)`.

5. **asChild / Slot polymorphism**: use `@radix-ui/react-slot` to enable polymorphic rendering. Accept an `asChild?: boolean` prop (default `false`). If `asChild` is true, render `<Slot>` which merges the component's props into the single child element instead of wrapping it. Example: `const Comp = asChild ? Slot : 'button'; return <Comp className={cn(...)} ref={ref} {...props}>{children}</Comp>`. This lets consumers pass `asChild` to render the component as a custom element (e.g., `<Button asChild><a href="...">Link</a></Button>`).

6. **data-[state=...] Radix state classes**: Radix primitives expose state via `data-state="open|closed|active|inactive"` attributes. Style these with Tailwind's data attribute variants: `data-[state=open]:opacity-100 data-[state=closed]:opacity-0`, `data-[state=active]:bg-primary data-[state=inactive]:bg-gray-100`. Pair with animate-in/out classes for transitions.

7. **Custom Tailwind variants**: define custom variants in index.css via `@custom-variant pointer-fine (@media (pointer: fine))` for fine pointer (mouse) vs coarse (touch). Use in components as `pointer-fine:opacity-100` to show hover states only on mouse devices. Define `@media (prefers-reduced-motion: reduce)` rules to disable animations when the user prefers reduced motion.

8. **Keyframe animations + animate-* utilities**: define keyframes in index.css (`@keyframes fadeIn { from { opacity: 0; } to { opacity: 1; } }`), then create utility classes (`@layer utilities { .animate-fadeIn { animation: fadeIn 0.2s ease-out; } }`). Use in components: `className="animate-fadeIn data-[state=open]:animate-in data-[state=closed]:animate-out"`. Always wrap animations in `@media (prefers-reduced-motion: reduce) { .animate-* { animation: none; } }` to respect accessibility.

9. **Mobile/desktop conditional rendering**: detect viewport via custom hooks (e.g., `useIsMobile()` from `@/hooks/useMediaQuery`). Render Radix Select as a BottomSheet on mobile, standard Popover on desktop. Wrap mobile-specific UI in conditional blocks (`if (isMobile) return <BottomSheet>...</BottomSheet>`). Extract SelectItem children recursively on mobile to populate the sheet's option list.

10. **DialogPortal / SelectPortal pattern**: Radix Content components render into a Portal by default to escape z-index stacking. Explicitly wrap Content with `<DialogPrimitive.Portal><DialogPrimitive.Content /></DialogPrimitive.Portal>` for clarity. This ensures overlays appear above everything else in the DOM.

11. **Focus-visible ring**: add `focus:outline-none focus:ring-2 focus:ring-primary/20 focus:ring-offset-2` to all interactive components. Use `focus-visible:` variant for keyboard-only focus rings (no ring on mouse click). Define a global base style in index.css: `:focus-visible { @apply outline-none ring-2 ring-primary-500/20 ring-offset-2; }`.

12. **Component file structure**: one file per Radix primitive wrapper (e.g., `Dialog.tsx`, `Select.tsx`, `Switch.tsx`, `Tabs.tsx`). Each file exports all sub-components (`Dialog`, `DialogTrigger`, `DialogContent`, `DialogTitle`, etc.). Place in `src/components/ui/` directory. Export via barrel `index.ts` for clean imports: `import { Dialog, DialogContent } from '@/components/ui'`.

13. **TypeScript forwardRef pattern**: wrap every Radix sub-component with `React.forwardRef<React.ElementRef<typeof Primitive>, React.ComponentPropsWithoutRef<typeof Primitive>>((props, ref) => ...)` to preserve type safety and ref forwarding. Use `ComponentPropsWithoutRef` to extract props minus ref, then spread `{...props}` after className.

14. **Safe area insets for mobile**: define utilities in index.css: `.pb-safe { padding-bottom: env(safe-area-inset-bottom, 0px); }`. Use on mobile BottomSheets and fixed footers to avoid notch overlap on iOS devices. Example: `<div className="pb-safe">...</div>`.

15. **Scroll behavior patterns**: for horizontally scrollable tabs, wrap the TabsList in a scroll container with `overflow-x-auto scrollbar-hide min-w-0`. Add fade indicators at edges via `mask-image: linear-gradient(to right, transparent 0, black 32px, black calc(100% - 32px), transparent 100%)`. Check scroll bounds with `useEffect` and `scrollLeft` to show/hide fade dynamically.

## Skeleton / example

```tsx
// lib/utils.ts
import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';

export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}
```

```css
/* src/index.css */
@import "tailwindcss";

@theme {
  /* Primary colors */
  --color-primary-500: #6366f1;
  --color-primary-600: #4f46e5;
  --color-primary: #6366f1;

  /* Semantic colors */
  --color-success: #10B981;
  --color-warning: #F59E0B;
  --color-error: #EF4444;

  /* Border radius */
  --radius-lg: 0.5rem;
  --radius-full: 9999px;

  /* Font families */
  --font-sans: Inter, system-ui, sans-serif;
}

@custom-variant pointer-fine (@media (pointer: fine));

@layer utilities {
  .scrollbar-hide {
    -ms-overflow-style: none;
    scrollbar-width: none;
  }
  .scrollbar-hide::-webkit-scrollbar {
    display: none;
  }
}

@keyframes fadeIn {
  from { opacity: 0; }
  to { opacity: 1; }
}

.animate-fadeIn {
  animation: fadeIn 0.2s ease-out;
}

@media (prefers-reduced-motion: reduce) {
  .animate-fadeIn {
    animation: none;
  }
}
```

```tsx
// components/ui/Button.tsx
import React, { forwardRef, type ButtonHTMLAttributes } from 'react';
import { Slot } from '@radix-ui/react-slot';
import { cn } from '@/lib/utils';

type ButtonVariant = 'primary' | 'secondary' | 'outline' | 'ghost' | 'destructive';
type ButtonSize = 'sm' | 'md' | 'lg' | 'icon';

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  asChild?: boolean;
}

const variantStyles: Record<ButtonVariant, string> = {
  primary: 'bg-primary text-white hover:bg-primary-600 focus:ring-primary/20',
  secondary: 'bg-gray-700 text-white hover:bg-gray-800 focus:ring-gray-200',
  outline: 'border border-gray-300 bg-transparent text-gray-700 hover:bg-gray-50',
  ghost: 'bg-transparent text-gray-700 hover:bg-gray-100',
  destructive: 'bg-error text-white hover:bg-error-600 focus:ring-error/20',
};

const sizeStyles: Record<ButtonSize, string> = {
  sm: 'h-8 px-3 text-sm',
  md: 'h-10 px-4 text-sm',
  lg: 'h-12 px-6 text-base',
  icon: 'h-10 w-10',
};

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant = 'primary', size = 'md', asChild = false, ...props }, ref) => {
    const Comp = asChild ? Slot : 'button';

    return (
      <Comp
        className={cn(
          'inline-flex items-center justify-center rounded-lg font-medium transition-colors',
          'focus:outline-none focus:ring-4 disabled:opacity-50 disabled:cursor-not-allowed',
          variantStyles[variant],
          sizeStyles[size],
          className
        )}
        ref={ref}
        {...props}
      />
    );
  }
);

Button.displayName = 'Button';
```

```tsx
// components/ui/Dialog.tsx
import * as React from 'react';
import * as DialogPrimitive from '@radix-ui/react-dialog';
import { X } from 'lucide-react';
import { cn } from '@/lib/utils';

const Dialog = DialogPrimitive.Root;
const DialogTrigger = DialogPrimitive.Trigger;
const DialogPortal = DialogPrimitive.Portal;
const DialogClose = DialogPrimitive.Close;

const DialogOverlay = React.forwardRef<
  React.ElementRef<typeof DialogPrimitive.Overlay>,
  React.ComponentPropsWithoutRef<typeof DialogPrimitive.Overlay>
>(({ className, ...props }, ref) => (
  <DialogPrimitive.Overlay
    ref={ref}
    className={cn(
      'fixed inset-0 z-50 bg-black/20',
      'data-[state=open]:animate-in data-[state=closed]:animate-out',
      'data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0',
      className
    )}
    {...props}
  />
));
DialogOverlay.displayName = DialogPrimitive.Overlay.displayName;

const DialogContent = React.forwardRef<
  React.ElementRef<typeof DialogPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof DialogPrimitive.Content>
>(({ className, children, ...props }, ref) => (
  <DialogPortal>
    <DialogOverlay />
    <DialogPrimitive.Content
      ref={ref}
      className={cn(
        'fixed left-[50%] top-[50%] z-50 w-full max-w-lg translate-x-[-50%] translate-y-[-50%]',
        'border bg-white p-6 shadow-lg rounded-lg',
        'data-[state=open]:animate-in data-[state=closed]:animate-out',
        'data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0',
        'data-[state=closed]:zoom-out-95 data-[state=open]:zoom-in-95',
        className
      )}
      {...props}
    >
      {children}
      <DialogPrimitive.Close className="absolute right-4 top-4 rounded-sm opacity-70 hover:opacity-100">
        <X className="h-4 w-4" />
        <span className="sr-only">Close</span>
      </DialogPrimitive.Close>
    </DialogPrimitive.Content>
  </DialogPortal>
));
DialogContent.displayName = DialogPrimitive.Content.displayName;

const DialogTitle = React.forwardRef<
  React.ElementRef<typeof DialogPrimitive.Title>,
  React.ComponentPropsWithoutRef<typeof DialogPrimitive.Title>
>(({ className, ...props }, ref) => (
  <DialogPrimitive.Title
    ref={ref}
    className={cn('text-lg font-semibold leading-none', className)}
    {...props}
  />
));
DialogTitle.displayName = DialogPrimitive.Title.displayName;

export { Dialog, DialogPortal, DialogOverlay, DialogClose, DialogTrigger, DialogContent, DialogTitle };
```

```tsx
// components/ui/Switch.tsx
import React, { forwardRef } from 'react';
import * as SwitchPrimitive from '@radix-ui/react-switch';
import { cn } from '@/lib/utils';

const Switch = forwardRef<
  React.ElementRef<typeof SwitchPrimitive.Root>,
  React.ComponentPropsWithoutRef<typeof SwitchPrimitive.Root>
>(({ className, ...props }, ref) => (
  <SwitchPrimitive.Root
    ref={ref}
    className={cn(
      'peer inline-flex h-5 w-9 shrink-0 cursor-pointer items-center rounded-full',
      'border-2 border-transparent transition-colors duration-200',
      'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2',
      'disabled:cursor-not-allowed disabled:opacity-50',
      'data-[state=checked]:bg-primary data-[state=unchecked]:bg-gray-200',
      className
    )}
    {...props}
  >
    <SwitchPrimitive.Thumb
      className={cn(
        'block h-4 w-4 rounded-full bg-white shadow-sm',
        'transition-transform duration-200',
        'data-[state=checked]:translate-x-4 data-[state=unchecked]:translate-x-0'
      )}
    />
  </SwitchPrimitive.Root>
));
Switch.displayName = 'Switch';

export { Switch };
```

## Anti-patterns to avoid

1. **Hardcoding colors instead of using @theme tokens**: avoid `bg-[#6366f1]` or hardcoded hex values. Always define colors in @theme {} and reference via `bg-primary`. This ensures consistency and makes theming easier.
2. **Not using cn() for className merging**: always use `cn(baseClasses, className)` to merge user-provided className with base styles. Direct string concatenation (`className + ' ' + baseClasses`) breaks when classes conflict.
3. **Forgetting to forward ref**: Radix primitives require ref forwarding for proper DOM manipulation. Always wrap with `forwardRef` and pass `ref={ref}` to the primitive.
4. **Missing data-state animations**: Radix components expose open/closed/active state via data attributes. Use `data-[state=open]:animate-in` to animate state changes. Without this, components appear/disappear instantly.
5. **Ignoring prefers-reduced-motion**: animations must respect `@media (prefers-reduced-motion: reduce)`. Wrap all animation classes in this media query to disable animations for users who prefer reduced motion.
6. **Not using Portal for overlays**: Dialog/Dropdown/Tooltip Content must render in a Portal to escape z-index stacking issues. Always wrap Content with `<Primitive.Portal>`.
7. **Variant styles as inline ternaries**: avoid `className={variant === 'primary' ? '...' : '...'}`. Use a `variantStyles` Record for readability and maintainability.
8. **Missing focus-visible rings**: all interactive components need keyboard focus indicators. Use `focus-visible:ring-2` to show rings only on keyboard focus, not mouse clicks.
9. **Not handling mobile-specific UI**: components like Select/Dropdown should render as BottomSheet on mobile for better UX. Detect with `useIsMobile()` and conditionally render.
10. **Forgetting safe area insets on mobile**: fixed footers and BottomSheets on iOS need `pb-safe` to avoid notch overlap. Use `padding-bottom: env(safe-area-inset-bottom)`.

## References

- [radix-primitives-and-variants.md](references/radix-primitives-and-variants.md) — Radix primitive wrapping, variant API patterns, asChild/Slot polymorphism, data-state styling
- [tailwind-theme-and-cn.md](references/tailwind-theme-and-cn.md) — Tailwind v4 @theme tokens, cn() utility, custom variants, keyframe animations, prefers-reduced-motion
- [repo-evidence.md](references/repo-evidence.md) — source file paths and genericized snippets from production services
- [frontend-repo-architecture](../frontend-repo-architecture) — where ui/ components live in the project structure
