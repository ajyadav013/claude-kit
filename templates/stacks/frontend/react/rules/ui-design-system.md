# UI Design System — Foundations

**All frontend development MUST follow these rules.**

This is the **foundations & index** file for the design system. It carries the core visual language
(principles, color, typography, spacing, radius, icons, number formatting, utilities, theme tokens) and
indexes the component and layout rules, which live in two companion files so every rule file stays under
the editor/memory size limit:

- **[`ui-components.md`](./ui-components.md)** — cards, badges, buttons, form controls, states, the component library, tooltips, KPI labels, data tables, and compound components.
- **[`ui-layout-and-motion.md`](./ui-layout-and-motion.md)** — page layout, motion & animation, accessibility, page blueprints, and the quick reference.

## Table of Contents

### Foundations (this file)

1. [Design Principles](#design-principles)
2. [Color System](#color-system)
3. [Typography](#typography)
4. [Spacing & Layout](#spacing--layout)
5. [Border Radius](#border-radius)
6. [Icons](#icons)
7. [Number Formatting](#number-formatting)
8. [Utilities](#utilities)
9. [Theme Tokens Reference](#theme-tokens-reference)

### Components — [`ui-components.md`](./ui-components.md)

10. [Cards](./ui-components.md#cards)
11. [Badges](./ui-components.md#badges)
12. [Buttons](./ui-components.md#buttons)
13. [Form Controls](./ui-components.md#form-controls)
14. [Loading States](./ui-components.md#loading-states)
15. [Empty States](./ui-components.md#empty-states)
16. [Toast System](./ui-components.md#toast-system)
17. [Component Library](./ui-components.md#component-library)
18. [Tooltips](./ui-components.md#tooltips)
19. [KPI Labels](./ui-components.md#kpi-labels)
20. [Data Tables](./ui-components.md#data-tables)
21. [Compound Components](./ui-components.md#compound-components)

### Layout & Motion — [`ui-layout-and-motion.md`](./ui-layout-and-motion.md)

22. [Page Layout](./ui-layout-and-motion.md#page-layout)
23. [Motion & Animation](./ui-layout-and-motion.md#motion--animation)
24. [Accessibility](./ui-layout-and-motion.md#accessibility)
25. [Page Blueprints](./ui-layout-and-motion.md#page-blueprints)
26. [Quick Reference](./ui-layout-and-motion.md#quick-reference)

---

## Design Principles

1. **Content over chrome.** UI elements support, not compete. Minimize decorative elements.
2. **Confidence through clarity.** Every screen should make the next action obvious.
3. **Density without clutter.** Progressive disclosure — summary first, details on demand.
4. **Consistency is kindness.** Same patterns everywhere: `rounded-lg`, Radix primitives, `gap-3` for grids.

---

## Color System

Colors are defined as CSS custom properties in your global stylesheet using the `@theme` directive.

### Brand Colors

| Color         | Token       | Hex       | Usage                                   |
| ------------- | ----------- | --------- | --------------------------------------- |
| **Primary**   | `primary`   | `#______` | CTAs, active states, links, focus rings |
| **Secondary** | `secondary` | `#______` | Highlights, secondary CTAs, accents     |
| **Success**   | `success`   | `#______` | Approvals, positive metrics             |
| **Warning**   | `warning`   | `#______` | Cautions, pending states                |
| **Error**     | `error`     | `#______` | Errors, rejections                      |

> Pin the actual hex values once in your theme config (`@theme` block below). Components consume the **token names** (`bg-primary`, `text-success`, …), never raw hex.

### Color Scales

Full 50–900 scales are defined as `@theme` tokens in your global stylesheet:

| Token       | Scale                                           |
| ----------- | ----------------------------------------------- |
| `primary`   | 50, 100, 200, 300, 400, 500, 600, 700, 800, 900 |
| `secondary` | 50, 100, 200, 300, 400, 500, 600, 700, 800, 900 |
| `success`   | 50, 500, 600                                    |
| `warning`   | 50, 500, 600                                    |
| `error`     | 50, 500, 600                                    |

### Semantic Color Patterns

For state-based coloring (badges, cards, status indicators):

```tsx
// Success state
bg-green-100 text-green-700

// Warning state
bg-amber-100 text-amber-700

// Error state
bg-red-100 text-red-700

// Info state
bg-blue-100 text-blue-700

// Neutral state
bg-gray-100 text-gray-700
```

### Gray Palette

| Class             | Usage                                               |
| ----------------- | --------------------------------------------------- |
| `text-gray-900`   | Headings, important text                            |
| `text-gray-700`   | Body text                                           |
| `text-gray-500`   | Muted / secondary text, placeholders                |
| `text-gray-400`   | Non-essential metadata only (timestamps, footnotes) |
| `bg-gray-50`      | Page background                                     |
| `bg-gray-100`     | Subtle background, hover states                     |
| `border-gray-200` | Card/section borders                                |
| `border-gray-100` | Subtle dividers (modal headers/footers)             |
| `border-gray-300` | Input borders                                       |

---

## Typography

### Font Family

The app uses **Inter** as the primary font (fallback: `system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif`).

### Text Sizes

| Size        | Tailwind Class     | Usage                                        |
| ----------- | ------------------ | -------------------------------------------- |
| Extra Small | `text-xs` (12px)   | Metadata, hints, badges, timestamps          |
| Small       | `text-sm` (14px)   | Body text, labels, card content, button text |
| Base        | `text-base` (16px) | Large button text (`size="lg"`)              |
| Large       | `text-lg` (18px)   | Page titles, modal titles                    |
| 2XL         | `text-2xl` (24px)  | Large metrics, KPI values                    |

### Font Weights

| Weight   | Tailwind Class  | Usage                                      |
| -------- | --------------- | ------------------------------------------ |
| Regular  | `font-normal`   | Body text                                  |
| Medium   | `font-medium`   | Labels, badge text, input labels           |
| Semibold | `font-semibold` | Card titles, section headers, modal titles |
| Bold     | `font-bold`     | Page titles, KPI values                    |

### Text Colors

| Color     | Tailwind Class  | Usage                                         |
| --------- | --------------- | --------------------------------------------- |
| Primary   | `text-gray-900` | Headings, important text                      |
| Secondary | `text-gray-700` | Body text                                     |
| Muted     | `text-gray-500` | Subtitles, descriptions, placeholders         |
| Hint      | `text-gray-400` | Timestamps, footnotes, non-essential metadata |

**Note**: Placeholders (`placeholder:text-gray-500`) use `text-gray-500` (Muted), not `text-gray-400`, to meet WCAG AA contrast requirements (4.5:1 on white).

### Standard Text Patterns

```tsx
// Page title (standalone — no subtitle, no icon)
<h1 className="text-lg font-bold text-gray-900">Page Title</h1>

// Section header (inside cards or content areas)
<h2 className="text-sm font-semibold text-gray-900">Section Title</h2>

// Card title
<h3 className="text-sm font-semibold text-gray-900">Card Title</h3>

// Metadata
<span className="text-xs text-gray-500">Updated 2 hours ago</span>

// Footer/timestamp text
<span className="text-xs text-gray-400">Additional info</span>

// KPI value
<p className="text-2xl font-bold text-gray-900">1,234</p>
```

---

## Spacing & Layout

### Spacing Scale

| Value | Pixels | Usage                                  |
| ----- | ------ | -------------------------------------- |
| `1`   | 4px    | Tight spacing, icon-text gap           |
| `2`   | 8px    | Standard gap between inline elements   |
| `3`   | 12px   | Card padding, grid gaps                |
| `4`   | 16px   | Section spacing, standard card padding |
| `6`   | 24px   | Modal padding                          |

### Container Patterns

```tsx
// Page container
<div className="space-y-4">

// Card grid
<div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3">

// Flex row with gap
<div className="flex items-center gap-2">
```

### Rules

| Element      | Rule                                                |
| ------------ | --------------------------------------------------- |
| Card padding | `p-3` or `p-4`. **NEVER** `p-5` or `p-6` for cards. |
| Grid gaps    | `gap-3` as the standard spacing unit                |
| Page spacing | `space-y-4` between major sections                  |

---

## Border Radius

**Standard radius**: `rounded-lg` (8px)

| Pattern        | Usage                                 |
| -------------- | ------------------------------------- |
| `rounded-lg`   | Cards, buttons, inputs, modals        |
| `rounded-md`   | Tabs, smaller containers              |
| `rounded-full` | Badges, pills, avatars, switch thumbs |

**Important**: Do NOT use `rounded-xl` or larger for standard components. Use `rounded-lg` consistently.

```tsx
// Correct
<div className="rounded-lg">

// Incorrect — avoid for standard components
<div className="rounded-xl">
```

---

## Icons

We use **Lucide React** for all icons. No custom SVG icons — if Lucide has it, use it.

```tsx
import { Home, Search, Settings } from 'lucide-react';
```

### Icon Sizes

| Size        | Tailwind Class | Usage                                       |
| ----------- | -------------- | ------------------------------------------- |
| Extra Small | `w-3 h-3`      | Inline with `text-xs`, metadata, timestamps |
| Small       | `w-4 h-4`      | Inline with `text-sm`, buttons, back arrows |
| Medium      | `w-5 h-5`      | Stat cards, standalone icons                |
| Large       | `w-8 h-8`      | Empty states, modal headers                 |
| Extra Large | `w-12 h-12`    | Empty state illustrations                   |

### Icon Patterns

```tsx
// Button icon (inside button)
<Plus className="w-4 h-4" />

// Metadata icon
<Clock className="w-3 h-3" />
<span className="text-xs">2 hours ago</span>

// Stat card icon with background
<div className="p-2 rounded-lg bg-blue-100">
  <Eye className="w-5 h-5 text-blue-600" />
</div>

// Empty state icon
<FileText className="w-12 h-12 text-gray-300" />
```

### Icon Colors

| Context        | Color Class                           |
| -------------- | ------------------------------------- |
| Default        | `text-gray-400` or `text-gray-500`    |
| Active/Primary | `text-primary`                        |
| Success        | `text-green-500` or `text-green-600`  |
| Warning        | `text-yellow-500` or `text-amber-500` |
| Error          | `text-red-500` or `text-red-600`      |
| Info           | `text-blue-500` or `text-blue-600`    |
| Empty state    | `text-gray-300`                       |

---

## Number Formatting

All number and currency formatting uses centralized functions from `@/lib/utils`. Never create page-local formatters.

| Function                   | Input  | Output            | Example                              |
| -------------------------- | ------ | ----------------- | ------------------------------------ |
| `formatCurrency(value)`    | Number | Localized money   | `formatCurrency(50000)` → `$50,000`  |
| `formatNumber(num)`        | Number | Grouped digits    | `formatNumber(1234567)` → `1,234,567` |
| `formatCompactNumber(num)` | Number | Compact notation  | `formatCompactNumber(1234567)` → `1.2M` |

**Rules:**

- Pick **one** currency symbol, abbreviation style, and locale/grouping convention for the project and apply it everywhere — never mix formats on the same screen.
- Route every rendered number/currency through these helpers; do not inline `toLocaleString`/`Intl.NumberFormat` in components.
- Add a new helper to `@/lib/utils` rather than a page-local formatter when a new format is needed.

---

## Utilities

### `@/lib/utils`

| Function                | Purpose                                              |
| ----------------------- | ---------------------------------------------------- |
| `cn()`                  | Tailwind-aware class merging (clsx + tailwind-merge) |
| `formatDate()`          | Date formatting                                      |
| `formatDateTime()`      | Date + time formatting                               |
| `formatRelativeTime()`  | Relative time (e.g. "2 hours ago")                   |
| `truncate()`            | Truncate text with ellipsis                          |
| `capitalize()`          | Capitalize first letter                              |
| `getInitials()`         | Extract initials from name                           |
| `formatNumber()`        | Number formatting with locale                        |
| `formatCompactNumber()` | Compact notation (e.g. "1.2K")                       |
| `formatFileSize()`      | File size formatting                                 |
| `formatDuration()`      | Duration formatting                                  |
| `debounce()`            | Debounce function calls                              |
| `sleep()`               | Async delay                                          |
| `isDefined()`           | Type guard for non-null values                       |

---

## Theme Tokens Reference

All theme tokens are defined in your global stylesheet using the Tailwind v4 `@theme` directive:

```css
@theme {
  --color-primary: #______;
  --color-secondary: #______;
  --color-success: #______;
  --color-warning: #______;
  --color-error: #______;

  --radius-sm: 0.25rem;
  --radius-md: 0.375rem;
  --radius-lg: 0.5rem;

  --font-sans: Inter, system-ui, ...;
  --font-mono: ui-monospace, SFMono-Regular, ...;
}
```

---
