---
paths:
  - "**/*.tsx"
  - "**/*.jsx"
  - "**/*.css"
  - "**/*.scss"
---

# UI Components

**All frontend development MUST follow these rules.** Companion to
[`ui-design-system.md`](./ui-design-system.md) (foundations: color, typography, spacing, tokens) and
[`ui-layout-and-motion.md`](./ui-layout-and-motion.md) (page layout, motion, accessibility, blueprints).

This file covers the **component layer** — the primitives and compound components every page composes.

## Table of Contents

1. [Cards](#cards)
2. [Badges](#badges)
3. [Buttons](#buttons)
4. [Form Controls](#form-controls)
5. [Loading States](#loading-states)
6. [Empty States](#empty-states)
7. [Toast System](#toast-system)
8. [Component Library](#component-library)
9. [Tooltips](#tooltips)
10. [KPI Labels](#kpi-labels)
11. [Data Tables](#data-tables)
12. [Compound Components](#compound-components)

---

## Cards

### Standard Card

```tsx
<div
  className={cn(
    "bg-white rounded-lg border border-gray-200 p-3 h-full flex flex-col",
    "hover:border-primary/30 hover:shadow-md transition-all duration-200",
    className,
  )}
>
  {/* Content */}
</div>
```

### Card Structure

```tsx
<div className="bg-white rounded-lg border border-gray-200 p-3 hover:border-primary/30 hover:shadow-md transition-all duration-200">
  {/* Header: Title and Status */}
  <div className="flex items-start justify-between gap-2 mb-2">
    <h3 className="text-sm font-semibold text-gray-900 line-clamp-2 flex-1">Card Title</h3>
    <Badge variant="success">Active</Badge>
  </div>

  {/* Badges row */}
  <div className="flex items-center gap-2 mb-2">
    <span className="px-2 py-0.5 rounded text-xs font-medium bg-blue-100 text-blue-700">Category</span>
  </div>

  {/* Optional: Description */}
  <p className="text-xs text-gray-600 mb-2 line-clamp-1">Description text</p>

  {/* Footer: Timestamp — pushed to bottom */}
  <div className="flex items-center gap-1 text-xs text-gray-400 mt-auto pt-2">
    <Clock className="w-3 h-3" />
    <span>2 hours ago</span>
  </div>
</div>
```

### Metric Card (Stat Card)

For displaying KPIs with icons:

```tsx
<div className="bg-white rounded-lg border border-gray-200 p-4">
  <div className="flex items-center justify-between mb-2">
    <div className="flex items-center gap-1.5">
      <Icon className="w-4 h-4 text-gray-400" />
      <span className="text-sm font-semibold text-gray-900">Metric Label</span>
    </div>
    <Badge variant="success">On Track</Badge>
  </div>
  <p className="text-2xl font-bold text-gray-900">1,234</p>
  <p className="text-xs text-gray-500 mt-1">vs target: 1,200</p>
</div>
```

### Status Card with Colored Border

```tsx
<div className="bg-white rounded-lg border-2 border-success/30 p-4">{/* Content */}</div>
```

### Card Title

```
text-sm font-semibold text-gray-900
```

Never use `text-lg` for card titles.

---

## Badges

### Badge Component (`@/components/ui/Badge`)

```tsx
import { Badge } from '@/components/ui';

<Badge variant="success">Approved</Badge>
<Badge variant="error">Rejected</Badge>
<Badge variant="warning">Pending</Badge>
<Badge variant="info">Info</Badge>
<Badge variant="default">Default</Badge>
```

**Variants**: `default`, `primary`, `secondary`, `success`, `warning`, `error`, `destructive`, `info`, `outline`

**Sizes**: `sm`, `md`, `lg`

| Size | Classes                         |
| ---- | ------------------------------- |
| `sm` | `px-1.5 py-0.5 text-xs`         |
| `md` | `px-2 py-0.5 text-xs` (default) |
| `lg` | `px-2.5 py-1 text-sm`           |

**Base styles**: `inline-flex items-center gap-1.5 font-medium rounded-full`

**Dot indicator**: Use `dot` prop for status dots.

```tsx
<Badge variant="success" dot>
  Active
</Badge>
```

### Inline Badges (No Component)

For simple inline badges in cards, use raw Tailwind:

```tsx
// Standard inline badge
<span className="px-2 py-0.5 rounded text-xs font-medium bg-blue-100 text-blue-700">
  Label
</span>

// Pill badge (rounded-full)
<span className="px-2 py-0.5 rounded-full text-xs font-medium bg-green-100 text-green-700">
  Label
</span>
```

### Status Color Patterns

| Status  | Background     | Text             |
| ------- | -------------- | ---------------- |
| Success | `bg-green-100` | `text-green-700` |
| Warning | `bg-amber-100` | `text-amber-700` |
| Error   | `bg-red-100`   | `text-red-700`   |
| Info    | `bg-blue-100`  | `text-blue-700`  |
| Neutral | `bg-gray-100`  | `text-gray-700`  |

### Badge: Non-Interactive Only

**Rule: Badges are strictly non-interactive visual indicators.** A badge communicates a status, category, count, or notification — it is never an action trigger. No `onClick`, no `cursor-pointer`, no `role="button"`, no `role="link"`, no wrapping in clickable elements.

#### Permitted Use Cases

| Use case | Example |
|----------|---------|
| Status label | `<Badge variant="success">On Track</Badge>` |
| Category tag | `<Badge variant="primary">Fashion</Badge>` |
| Notification count | `<Badge variant="error">3</Badge>` |
| Severity indicator | `<Badge variant="warning" dot>At Risk</Badge>` |

#### Only Permitted Interaction: Tooltip on Hover

If additional context is needed, wrap a Badge in a `<Tooltip>`:

```tsx
<Tooltip>
  <TooltipTrigger asChild>
    <span><Badge variant="warning" dot>At Risk</Badge></span>
  </TooltipTrigger>
  <TooltipContent>Revenue 12% below target for 3 consecutive weeks</TooltipContent>
</Tooltip>
```

No cursor change, no focus ring, no hover ring. The tooltip is a passive information layer.

#### What Was Previously a Badge — Use Instead

| Old pattern | Replace with | Why |
|-------------|-------------|-----|
| Clickable badge (navigation) | `<Button variant="ghost" size="sm">` or `<Button variant="link">` | Buttons are for actions; use `asChild` with `<Link>` for navigation |
| Clickable badge (toggle on/off) | `<Switch>` component | Switches are the standard toggle pattern; paired with a label |
| Badge as filter chip | `FilterPills` component | Filter selection has its own compound component |

#### Anti-Patterns

| Don't | Do Instead |
|-------|------------|
| `<Badge onClick={...}>` | Use `<Button>` for actions |
| `<button><Badge>...</Badge></button>` | Use `<Button>` directly — don't nest a Badge inside a Button |
| `<span role="button"><Badge>...</Badge></span>` | Use `<Button>` with appropriate variant |
| Badge with `cursor-pointer` | Remove — badges are not clickable |
| Badge toggling between variants on click | Use `<Switch>` with a text label |

---

## Buttons

### Button Component (`@/components/ui/Button`)

```tsx
import { Button } from '@/components/ui';

// Primary (default)
<Button>Submit</Button>

// Secondary
<Button variant="secondary">Secondary</Button>

// Outline
<Button variant="outline">Cancel</Button>

// Ghost
<Button variant="ghost">Edit</Button>

// Destructive
<Button variant="destructive">Delete</Button>

// Sizes
<Button size="sm">Small</Button>
<Button size="md">Medium</Button>
<Button size="lg">Large</Button>

// With icon
<Button>
  <Plus className="w-4 h-4" />
  New Item
</Button>

// Loading
<Button isLoading>Submitting...</Button>
```

### Button Variant Usage

Use the right variant for the right context — visual hierarchy matters:

| Variant       | Color              | When to Use                                                       |
| ------------- | ------------------ | ----------------------------------------------------------------- |
| `primary`     | Primary token      | **Main CTA** — one per section. Submit, Create, Approve.          |
| `secondary`   | Secondary token    | **Accent actions** — highlights, promotional CTAs. Use sparingly. |
| `outline`     | Gray border        | **Secondary actions** — Cancel, Back, alternative paths.          |
| `ghost`       | Transparent        | **Tertiary actions** — Edit, settings, inline actions.            |
| `destructive` | Red                | **Destructive actions** — Delete, Remove. Require confirmation.   |
| `link`        | Primary underline  | **Inline navigation** — embedded in text, no button chrome.       |

**Important**: Don't make every button `primary`. One primary CTA per form/section. Use `outline` or `ghost` for secondary actions to maintain clear visual hierarchy.

### Button Sizes

| Size   | Height      | Padding | Font Size   |
| ------ | ----------- | ------- | ----------- |
| `sm`   | `h-8`       | `px-3`  | `text-sm`   |
| `md`   | `h-10`      | `px-4`  | `text-sm`   |
| `lg`   | `h-12`      | `px-6`  | `text-base` |
| `icon` | `h-10 w-10` | -       | -           |

### Button Base Styles

```
inline-flex items-center justify-center rounded-lg font-medium transition-colors
focus:outline-none focus:ring-4
disabled:opacity-50 disabled:cursor-not-allowed
```

### Polymorphic Rendering

Use `asChild` prop with Radix Slot when the button should render as a different element (e.g., a link):

```tsx
<Button asChild>
  <Link to="/page">Navigate</Link>
</Button>
```

---

## Form Controls

### Input Component (`@/components/ui/Input`)

```tsx
import { Input } from '@/components/ui';

<Input
  label="Email"
  type="email"
  placeholder="you@example.com"
/>

// With error
<Input
  label="Email"
  error="Please enter a valid email"
/>

// With icons
<Input
  leftIcon={<Search className="w-4 h-4" />}
  placeholder="Search..."
/>

// With hint
<Input
  label="Username"
  hint="Must be 3-20 characters"
/>
```

**Styles**:

- Container: `space-y-1.5`
- Label: `block text-sm font-medium text-gray-700`
- Input: `w-full rounded-lg border bg-white py-3 text-gray-900 placeholder:text-gray-500`
- Normal border: `border-gray-200`
- Focus: `focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary`
- Error: `border-error focus:ring-error/20 focus:border-error`
- Disabled: `disabled:bg-gray-50 disabled:cursor-not-allowed`

**Accessibility**: Auto-links `aria-describedby` to hint/error, sets `aria-invalid` on error, error has `role="alert"`.

### Select Component (`@/components/ui/Select`)

Uses Radix UI primitives. Always use this instead of raw `<select>`:

```tsx
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui";

<Select value={value} onValueChange={setValue}>
  <SelectTrigger>
    <SelectValue placeholder="Select option..." />
  </SelectTrigger>
  <SelectContent>
    <SelectItem value="option1">Option 1</SelectItem>
    <SelectItem value="option2">Option 2</SelectItem>
  </SelectContent>
</Select>;
```

**Trigger sizes**: `sm` (`h-8 px-2 text-xs`), `md` (`h-10 px-3 text-sm`), `lg` (`h-12 px-4 text-base`)

**SelectContent**: Animated entrance/exit via Radix `animate-in`/`animate-out`.

### Tabs Component (`@/components/ui/Tabs`)

Uses Radix UI primitives with three visual variants:

```tsx
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui";

<Tabs defaultValue="tab1">
  <TabsList variant="default">
    <TabsTrigger value="tab1">Tab 1</TabsTrigger>
    <TabsTrigger value="tab2">Tab 2</TabsTrigger>
  </TabsList>
  <TabsContent value="tab1">Content 1</TabsContent>
  <TabsContent value="tab2">Content 2</TabsContent>
</Tabs>;
```

**Variants**:

| Variant     | TabsList                         | TabsTrigger Active State                   |
| ----------- | -------------------------------- | ------------------------------------------ |
| `default`   | `bg-gray-100 p-1 rounded-lg`     | `bg-white text-gray-900 shadow-sm`         |
| `pills`     | `gap-2`                          | `bg-primary text-white`                    |
| `underline` | `border-b border-gray-200 gap-4` | `text-primary border-primary` (border-b-2) |

### Switch Component (`@/components/ui/Switch`)

Radix-based toggle for boolean settings. Always use instead of `<input type="checkbox">` for on/off controls.

```tsx
import { Switch } from "@/components/ui";

<label className="flex items-center gap-2 cursor-pointer">
  <Switch checked={value} onCheckedChange={(checked) => setValue(checked)} />
  <span className="text-sm text-gray-700">Enable feature</span>
</label>;
```

**Specs**: `w-9 h-5`, checked: `bg-primary`, unchecked: `bg-gray-200`, thumb: `w-4 h-4 rounded-full bg-white` with translate animation.

---

## Loading States

### Spinner Component

```tsx
import { Spinner } from '@/components/ui';

<Spinner size="sm" />  // w-4 h-4
<Spinner size="md" />  // w-6 h-6
<Spinner size="lg" />  // w-8 h-8
<Spinner size="xl" />  // w-12 h-12
```

### Centered Loading

```tsx
<div className="flex items-center justify-center py-12">
  <div className="flex flex-col items-center gap-3">
    <Spinner size="lg" />
    <p className="text-sm text-gray-500">Loading...</p>
  </div>
</div>
```

### Button Loading

Built into the Button component with `isLoading` prop:

```tsx
<Button isLoading>Submitting...</Button>
```

### Image Loading

The `OptimizedImage` component shows a pulse placeholder while loading:

```tsx
<div className="absolute inset-0 animate-pulse bg-gray-200" />
```

### Progress Bars

```tsx
import { Progress, CircularProgress } from '@/components/ui';

// Linear progress
<Progress value={75} size="md" showLabel />

// Circular progress
<CircularProgress value={75} size={48} showLabel />
```

**Progress sizes**: `sm` (`h-1`), `md` (`h-2`), `lg` (`h-3`)

---

## Empty States

### Standard Empty State

```tsx
<div className="flex flex-col items-center justify-center py-12 bg-gray-50 rounded-lg">
  <FileText className="w-12 h-12 text-gray-300 mb-4" />
  <h3 className="text-lg font-medium text-gray-900 mb-1">No items found</h3>
  <p className="text-sm text-gray-500 mb-4">Start by creating a new item</p>
  <Button>
    <Plus className="w-4 h-4" />
    Create Item
  </Button>
</div>
```

### Minimal Empty State

For inline content areas:

```tsx
<div className="flex items-center justify-center h-64">
  <p className="text-sm text-gray-500">No data available.</p>
</div>
```

---

## Toast System

### Usage

```tsx
const { success, error, warning, info } = useToast();
success("Item saved");
error("Failed to save");
warning("Unsaved changes");
info("New update available");
```

Add `<ToastContainer />` to the app root to render toasts.

### Variants

| Variant   | Border              | Background     | Icon                                |
| --------- | ------------------- | -------------- | ----------------------------------- |
| `success` | `border-green-200`  | `bg-green-50`  | `CheckCircle` (`text-green-500`)    |
| `error`   | `border-red-200`    | `bg-red-50`    | `XCircle` (`text-red-500`)          |
| `warning` | `border-yellow-200` | `bg-yellow-50` | `AlertTriangle` (`text-yellow-500`) |
| `info`    | `border-blue-200`   | `bg-blue-50`   | `Info` (`text-blue-500`)            |

### Toast Structure

- Container: `relative flex items-start gap-3 rounded-lg border p-4 shadow-lg`
- Title: `text-sm font-semibold text-gray-900`
- Description: `text-sm text-gray-600 mt-0.5`
- Viewport: `fixed bottom-0 right-0 flex flex-col gap-2 p-4 w-full max-w-md z-50`
- Supports swipe-to-dismiss

---

## Component Library

### UI Primitives (`@/components/ui`)

All components use Radix UI primitives with Tailwind styling. Import via barrel export:

```tsx
import { Button, Badge, Modal, Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui";
```

| Component                                                          | Description                                                      |
| ------------------------------------------------------------------ | ---------------------------------------------------------------- |
| `Button`                                                           | Primary action component with 6 variants, 4 sizes, loading state |
| `Input`                                                            | Text input with label, error, hint, icon support                 |
| `Badge`                                                            | Status and category badges with 9 variants, dot indicator        |
| `Switch`                                                           | Boolean toggle (Radix-based)                                     |
| `Select` (full suite)                                              | Dropdown select with trigger sizes (Radix-based)                 |
| `Tabs` / `TabsList` / `TabsTrigger` / `TabsContent`                | Tab navigation with 3 variants                                   |
| `Modal` / `ModalFooter`                                            | Dialog overlays with 5 sizes                                     |
| `Toast` / `ToastContainer`                                         | Notification system with 4 variants                              |
| `Progress` / `CircularProgress`                                    | Linear and circular progress bars                                |
| `Spinner`                                                          | Loading spinner with 4 sizes                                     |
| `PageHeader`                                                       | Standardized page header with back nav, actions, badges          |
| `Card` / `CardHeader` / `CardTitle` / `CardContent` / `CardFooter` | Composable card primitives                                       |
| `DetailPanel` / `DetailPanelSection` / `DetailPanelRow`            | Slide-in detail panel for master-detail layouts                  |
| `OptimizedImage`                                                   | Image with lazy loading and pulse placeholder                    |
| `InlineExpandableForm`                                             | Inline editing that expands in-place (replaces modals)           |
| `InlinePicker`                                                     | Inline dropdown picker with search and filter tabs               |
| `Slider`                                                           | Range input with custom thumb styling                            |

### Modal Sizes

| Size   | Width                |
| ------ | -------------------- |
| `sm`   | `max-w-sm`           |
| `md`   | `max-w-md` (default) |
| `lg`   | `max-w-lg`           |
| `xl`   | `max-w-xl`           |
| `full` | `max-w-4xl`          |

### DetailPanel Widths

| Size  | Width            |
| ----- | ---------------- |
| `sm`  | `w-72`           |
| `md`  | `w-80` (default) |
| `lg`  | `w-96`           |
| `xl`  | `w-[28rem]`      |
| `2xl` | `w-[32rem]`      |

### Rules

- **Always** use existing UI primitives from `@/components/ui/` — never raw HTML `<select>`, `<input>`, etc.
- **Always** use Radix-based components (Select, Tabs, Switch) instead of custom implementations
- **Always** import via the barrel export `@/components/ui`

---

## Tooltips

Use the `Tooltip` component (wrapping `@radix-ui/react-tooltip`) for contextual information.

**When to use:**

- KPI abbreviation labels (via `KpiLabel`)
- Truncated text that needs full display on hover
- Icon-only buttons that need a text label

**Component API:**

```tsx
import { Tooltip, TooltipTrigger, TooltipContent } from "@/components/ui";

<Tooltip delayDuration={300}>
  <TooltipTrigger asChild>
    <button>Hover me</button>
  </TooltipTrigger>
  <TooltipContent side="top">Tooltip text here</TooltipContent>
</Tooltip>;
```

**Styling:** `bg-gray-900 text-white text-xs rounded-lg px-3 py-1.5 shadow-lg max-w-xs`. Default delay: 300ms. The `TooltipProvider` wraps the app root in `App.tsx`.

---

## KPI Labels

Use `KpiLabel` to make KPI abbreviations self-documenting for business users.

**Usage:**

```tsx
import { KpiLabel } from "@/components/ui";

<KpiLabel abbr="MRR" />; // Renders: MRR + info icon, tooltip on hover
```

**Glossary:** All abbreviation definitions live in `@/config/kpiGlossary`. Each entry has: `name`, `definition`, optional `formula`, optional `uom`.

**Adding new abbreviations:** Add an entry to the `kpiGlossary` record in `@/config/kpiGlossary`.

**Guidelines:**

- Use on first occurrence of an abbreviation in section headers or table headers
- Do not use inside data cells or inline values
- If the abbreviation is not in the glossary, KpiLabel renders plain text without an icon (graceful fallback)

---

## Data Tables

Use the `DataTable` component family for consistent table styling. These are lightweight wrappers providing standard Tailwind classes — no data management, sorting, or pagination logic included.

**Components:**

```tsx
import { DataTable, DataTableHeader, DataTableBody, DataTableRow, DataTableHead, DataTableCell } from "@/components/ui";

<DataTable>
  <DataTableHeader>
    <DataTableHead>Name</DataTableHead>
    <DataTableHead align="right">Value</DataTableHead>
  </DataTableHeader>
  <DataTableBody>
    <DataTableRow>
      <DataTableCell>Revenue</DataTableCell>
      <DataTableCell align="right">$1,234</DataTableCell>
    </DataTableRow>
  </DataTableBody>
</DataTable>;
```

**Standard styling:** `bg-gray-50` header, `text-xs`, `px-3 py-2` cell padding, `divide-y divide-gray-100` row borders.

**Props:** All components accept `className` for overrides. `DataTableHead` and `DataTableCell` accept `align` (`left` | `right` | `center`).

**With Pagination:** Pair with `<Pagination>` component below the table for paginated views.

---

## Compound Components

Compounds sit between primitives and pages. They encode spatial contracts — the layout relationships between primitives — so page authors wire up data, not layout.

**Rule: If a compound component exists for a pattern, you MUST use it. Never inline the layout that a compound owns.**

### Available Compounds

| Component       | What it owns                                                                | Import            |
| --------------- | --------------------------------------------------------------------------- | ----------------- |
| `FilterBar`     | Filter row layout: pills/dropdowns left, spacer, clear button, search right | `@/components/ui` |
| `FilterPills`   | Single-select pill group with consistent sizing, active/inactive styles     | `@/components/ui` |
| `FilterSelect`  | Thin Select wrapper with `size="sm"`, min-width, "All X" placeholder        | `@/components/ui` |
| `FilterSearch`  | Search input with fixed width, search icon, debounced onChange              | `@/components/ui` |
| `SectionHeader` | Title + optional subtitle + right-aligned actions, consistent `mb-3`        | `@/components/ui` |
| `EmptyState`    | Centered icon + title + description for empty/filtered states               | `@/components/ui` |
| `MetricGrid`    | Grid wrapper for MetricCard rows with consistent columns and gap            | `@/components/ui` |
| `PageHeader`    | Page title + breadcrumbs + right-aligned actions, consistent `mb-4`         | `@/components/ui` |
| `ListItemCard`  | Selectable card/row with standardized selection, hover, content slots       | `@/components/ui` |

### Decision Tree: When to Use What

```
Building a page with a list or table?
  -> Use FilterBar for any filtering UI

Adding a section title inside a card or content area?
  -> Use SectionHeader (never inline flex justify-between + h3)

Showing a row of KPI/metric cards?
  -> Use MetricGrid + MetricCard (never inline the grid)

Handling an empty or filtered-to-zero state?
  -> Use EmptyState (never inline centered text)

Adding a page title at the top?
  -> Use PageHeader (never inline h1 + flex justify-between)

Building a selectable item in a list or feed?
  -> Use ListItemCard (never inline selection/hover states)
```

### Filter Tier Model

Filtering has three tiers — **never mix them**:

| Tier             | Purpose                                               | UI                                                                              |
| ---------------- | ----------------------------------------------------- | ------------------------------------------------------------------------------- |
| **Segmentation** | Top-level content partitioning (changes what you see) | `Tabs` (underline variant) — sits **above** FilterBar                           |
| **Refinement**   | Narrows within a segment (reduces the list)           | `FilterPills` (2-5 options) or `FilterSelect` (6+ options) — inside `FilterBar` |
| **Search**       | Free-text lookup within the refined set               | `FilterSearch` — always rightmost in `FilterBar`                                |

### Filter Overflow — "More Filters" Panel

When a page has more refinement filters than fit comfortably in one horizontal row (typically **5+**), split them into **primary** (always visible as inline pills/dropdowns in the `FilterBar`) and **secondary** (behind a "More" trigger that opens a vertical popover panel).

**Layout:**

```
Primary filters inline in FilterBar:
[Date Range ▾] [Facet A ▾] [Facet B ▾] [Facet C ▾]  [+ More]  🔍
                                                     ↓ click
                                              ┌──────────────┐
                                              │ Facet D    ▾ │
                                              │ Facet E    ▾ │
                                              │ Facet F    ▾ │
                                              │ Facet G    ▾ │
                                              │              │
                                              │[Clear][Apply]│
                                              └──────────────┘
```

**"More" trigger spec:**

- Appears as the **last item** in the `FilterBar` row, before `FilterSearch`
- Ghost `Button` variant with `Plus` icon + "More" label
- No chevron — the `+` icon signals expandability
- When secondary filters have active values, append a count badge: **More (3)**

**More panel spec:**

- Opens via Radix `Popover`, anchored to the "More" trigger
- Fixed width (~280px), `rounded-lg`, `shadow-lg`, `border border-gray-200`, white background
- Interior: vertical stack of labeled filter controls, one per row, `space-y-3` gap
- Each filter inside the panel uses `FilterSelect` or `FilterMultiSelect` — identical behavior to primary filters
- Footer row: "Clear" (ghost `Button`) + "Apply" (primary `Button`)
- Closes on: Apply click, Escape key, outside click (standard Radix Popover behavior)

**Primary vs secondary split guidance:**

- **Primary** = the 3–4 most commonly used filters for the page's domain (always visible)
- **Secondary** = remaining filters that are less frequently used or more granular
- The split is page-specific, decided by the page author — not the component

**Anti-patterns:**

| Don't | Do Instead |
|-------|------------|
| Toggle "More/Less" that adds more horizontal dropdowns to the row | Use "More" popover panel with vertical layout |
| Let 5+ filters wrap across multiple horizontal lines | Move overflow filters into the "More" panel |
| Show/hide filters with a boolean state toggle (`showMoreFilters`) | Use a Radix Popover for secondary filters |

**When to reach for it:** any page with ~5+ refinement filters. Split the most-used 3–4 into the always-visible primary row and move the rest into the "More" panel.

### Extracting New Compounds

When a developer is about to write `<div className="flex items-center justify-between mb-3">`, they should ask:

```
Is this spatial pattern already encoded in a compound?
  YES -> Use the compound.
  NO  -> Does this same layout appear on 2+ other pages?
    YES -> Build the compound first, then use it.
    NO  -> Inline is fine. If it later appears on a 3rd page, extract.
```

Keep the full specification for each compound (its owned layout, props, and slots) alongside the component in your codebase.

---
