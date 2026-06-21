# Tailwind v4 @theme and cn() Utility

## Tailwind v4 @theme design tokens

Tailwind v4 reads design tokens directly from CSS via `@theme {}` blocks. No tailwind.config.js theme extension needed.

Define in `src/index.css` (or global CSS entry):

```css
@import "tailwindcss";

@theme {
  /* Breakpoints */
  --breakpoint-xs: 430px;

  /* Primary colors */
  --color-primary-50: #eef2ff;
  --color-primary-500: #6366f1;
  --color-primary-600: #4f46e5;
  --color-primary: #6366f1;  /* default primary */

  /* Semantic colors */
  --color-success-500: #10B981;
  --color-success: #10B981;
  --color-warning: #F59E0B;
  --color-error: #EF4444;

  /* Border radius */
  --radius-sm: 0.25rem;
  --radius-md: 0.375rem;
  --radius-lg: 0.5rem;
  --radius-full: 9999px;

  /* Font families */
  --font-sans: Inter, system-ui, -apple-system, sans-serif;
  --font-mono: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
}
```

Reference in components:
- Colors: `bg-primary`, `text-primary-600`, `border-error`
- Radius: `rounded-lg`, `rounded-full`
- Fonts: `font-sans`, `font-mono`

Tailwind automatically generates utilities from `--color-*`, `--radius-*`, `--font-*` tokens.

## cn() utility

Combine `clsx` for conditional classes with `tailwind-merge` to deduplicate conflicting Tailwind utilities:

```ts
// lib/utils.ts
import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';

export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}
```

Usage in components:

```tsx
const Button = ({ variant, className, ...props }) => (
  <button
    className={cn(
      'px-4 py-2 rounded-lg',
      variant === 'primary' && 'bg-primary text-white',
      variant === 'outline' && 'border border-gray-300',
      className  // user-provided classes override defaults
    )}
    {...props}
  />
);

// User can override:
<Button variant="primary" className="bg-error">Delete</Button>
// Result: bg-error (user override) instead of bg-primary
```

`twMerge` deduplicates conflicting utilities (e.g., `bg-primary bg-error` → `bg-error`). `clsx` handles conditional classes (`variant === 'primary' && '...'`).

## Custom Tailwind variants

Define custom variants in index.css via `@custom-variant`:

```css
/* Pointer variants for touch vs mouse detection */
@custom-variant pointer-fine (@media (pointer: fine));
@custom-variant pointer-coarse (@media (pointer: coarse));
```

Use in components:

```tsx
// Show keyboard hints only on devices with fine pointers (mouse)
<kbd className="opacity-0 pointer-fine:opacity-100">⌘K</kbd>

// Increase tap target size on touch devices
<button className="h-10 pointer-coarse:h-12">Tap me</button>
```

Standard variants:
- `pointer-fine`: mouse/trackpad devices
- `pointer-coarse`: touch-primary devices
- `focus-visible`: keyboard focus only (no mouse click)
- `data-[state=...]`: Radix state attributes

## Keyframe animations

Define keyframes in index.css, then create utility classes:

```css
@keyframes fadeIn {
  from { opacity: 0; }
  to { opacity: 1; }
}

@keyframes slideInRight {
  from { transform: translateX(100%); }
  to { transform: translateX(0); }
}

@layer utilities {
  .animate-fadeIn {
    animation: fadeIn 0.2s ease-out;
  }

  .animate-slideInRight {
    animation: slideInRight 0.3s ease-out;
  }
}
```

Use in components:

```tsx
<div className="animate-fadeIn data-[state=open]:animate-slideInRight">
  Content
</div>
```

Pair with Radix data-state attributes for state-driven animations.

## prefers-reduced-motion

All animations must respect user preference for reduced motion:

```css
@media (prefers-reduced-motion: reduce) {
  .animate-fadeIn,
  .animate-slideInRight,
  .animate-* {
    animation: none;
  }

  /* Disable all transitions */
  *,
  *::before,
  *::after {
    transition-duration: 0.01ms !important;
  }
}
```

This ensures users who prefer reduced motion see instant state changes instead of animated transitions.

## Custom utility classes

Define project-specific utilities in index.css:

```css
@layer utilities {
  /* Hide scrollbar */
  .scrollbar-hide {
    -ms-overflow-style: none;
    scrollbar-width: none;
  }
  .scrollbar-hide::-webkit-scrollbar {
    display: none;
  }

  /* Safe area insets for iOS notch */
  .pb-safe {
    padding-bottom: env(safe-area-inset-bottom, 0px);
  }
  .pt-safe {
    padding-top: env(safe-area-inset-top, 0px);
  }

  /* Horizontal scroll chips */
  .chip-scroll {
    @apply flex overflow-x-auto gap-2 pb-2;
    -ms-overflow-style: none;
    scrollbar-width: none;
    scroll-snap-type: x mandatory;
  }
  .chip-scroll > * {
    @apply snap-start flex-shrink-0;
  }

  /* Right-edge fade for tables */
  .scroll-fade-r {
    mask-image: linear-gradient(to right, black calc(100% - 32px), transparent 100%);
    -webkit-mask-image: linear-gradient(to right, black calc(100% - 32px), transparent 100%);
  }
}
```

## Base styles layer

Global element styles in index.css:

```css
@layer base {
  html {
    font-family: var(--font-sans);
    -webkit-font-smoothing: antialiased;
    -moz-osx-font-smoothing: grayscale;
  }

  body {
    @apply bg-gray-50 text-gray-900 m-0;
  }

  /* Default border color */
  * {
    @apply border-gray-200;
  }

  /* Interactive elements default to pointer cursor */
  button:not(:disabled),
  [role="button"]:not([aria-disabled="true"]),
  [role="tab"],
  summary {
    cursor: pointer;
  }

  /* Focus ring styles */
  :focus-visible {
    @apply outline-none ring-2 ring-primary-500/20 ring-offset-2;
  }
}
```

## Radix animate-in/out pattern

Tailwind + Radix data-state animations:

```tsx
<DialogPrimitive.Overlay
  className={cn(
    'fixed inset-0 bg-black/20',
    'data-[state=open]:animate-in data-[state=closed]:animate-out',
    'data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0',
    'data-[state=closed]:zoom-out-95 data-[state=open]:zoom-in-95'
  )}
/>
```

Tailwind's `animate-in`/`animate-out` utilities pair with `fade-in-0`, `zoom-in-95`, `slide-in-from-top-2`, etc., to create state-driven enter/exit animations.

## Scroll behavior utilities

For horizontally scrollable tabs with fade indicators:

```tsx
const [canScrollLeft, setCanScrollLeft] = useState(false);
const [canScrollRight, setCanScrollRight] = useState(false);

const maskImage = canScrollLeft || canScrollRight
  ? `linear-gradient(to right, ${
      canScrollLeft ? 'transparent 0, black 32px' : 'black 0'
    }, ${
      canScrollRight ? 'black calc(100% - 32px), transparent 100%' : 'black 100%'
    })`
  : undefined;

<div
  className="overflow-x-auto scrollbar-hide"
  style={{ maskImage, WebkitMaskImage: maskImage }}
  onScroll={checkScroll}
>
  <TabsList />
</div>
```

Check scroll bounds with `scrollLeft`, `clientWidth`, `scrollWidth` in `useEffect`.
