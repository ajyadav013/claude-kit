# UI Design System

**All frontend development MUST follow these rules.**

## Table of Contents

1. [Design Principles](#design-principles)
2. [Color System](#color-system)
3. [Typography](#typography)
4. [Spacing & Layout](#spacing--layout)
5. [Border Radius](#border-radius)
6. [Icons](#icons)
7. [Cards](#cards)
8. [Badges](#badges)
9. [Buttons](#buttons)
10. [Form Controls](#form-controls)
11. [Page Layout](#page-layout)
12. [Motion & Animation](#motion--animation)
13. [Accessibility](#accessibility)
14. [Loading States](#loading-states)
15. [Empty States](#empty-states)
16. [Toast System](#toast-system)
17. [Component Library](#component-library)
18. [Tooltips](#tooltips)
19. [KPI Labels](#kpi-labels)
20. [Number Formatting](#number-formatting)
21. [Data Tables](#data-tables)
22. [Utilities](#utilities)
23. [Theme Tokens Reference](#theme-tokens-reference)
24. [Compound Components](#compound-components)
25. [Page Blueprints](#page-blueprints)

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

## Page Layout

### PageHeader Component (`@/components/ui/PageHeader`)

Use the shared `PageHeader` component for all page headers:

```tsx
import { PageHeader } from "@/components/ui";

<PageHeader
  title="Page Title"
  backTo={{ label: "Dashboard", path: "/dashboard" }}
  actions={
    <Button>
      <Plus className="w-4 h-4" /> New Item
    </Button>
  }
  badges={<Badge variant="success">Live</Badge>}
/>;
```

**Props**:

- `title: string` — the page heading
- `backTo?: { label: string; path: string }` — optional back navigation
- `actions?: ReactNode` — right-aligned action buttons
- `badges?: ReactNode` — inline badges next to title

**Rules**:

- Title + CTA only — no icons in page headers (the sidebar already identifies the page)
- No subtitles/descriptions (redundant)
- Title uses `text-lg font-bold text-gray-900`
- Back link: `text-sm text-gray-500 hover:text-gray-700`

### Standard Page Structure

```tsx
function ExamplePage(): React.JSX.Element {
  return (
    <div className="space-y-4">
      {/* Header */}
      <PageHeader
        title="Page Title"
        actions={
          <Button>
            <Plus className="w-4 h-4" /> Action
          </Button>
        }
      />

      {/* Filter/Tabs Section */}
      <div className="border-b border-gray-200">{/* Tabs or filters */}</div>

      {/* Content */}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3">{/* Cards or content */}</div>
    </div>
  );
}
```

### Status Tabs Pattern

For filtering by status. **Hide zero-count tabs** to reduce visual noise — always show "All" and the currently active tab, but filter out tabs with zero items:

```tsx
<div className="border-b border-gray-200">
  <nav className="flex gap-1 -mb-px overflow-x-auto">
    {tabs
      .filter((tab) => {
        if (tab.value === "all" || activeTab === tab.value) return true;
        return tab.count > 0;
      })
      .map((tab) => (
        <button
          key={tab.value}
          onClick={() => setActiveTab(tab.value)}
          className={cn(
            "flex items-center gap-2 px-3 py-2 text-sm font-medium border-b-2 transition-colors whitespace-nowrap",
            isActive
              ? "border-primary text-primary"
              : "border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300",
          )}
        >
          {tab.label}
          <span
            className={cn(
              "px-2 py-0.5 rounded-full text-xs",
              isActive ? "bg-primary/10 text-primary" : "bg-gray-100 text-gray-600",
            )}
          >
            {tab.count}
          </span>
        </button>
      ))}
  </nav>
</div>
```

### Breadcrumb Pattern

**Desktop only.** Breadcrumbs MUST NOT render on mobile (`< lg:` breakpoint). Use `hidden lg:flex` on breadcrumb containers. On mobile, the bottom tab bar and page title provide sufficient wayfinding.

```tsx
// Breadcrumbs — desktop only
<div className="hidden lg:flex items-center gap-1">
  <button className="text-xs text-gray-500 hover:text-primary transition-colors">
    Parent Page
  </button>
  <ChevronRight className="w-3 h-3 text-gray-400" />
  <h1 className="text-lg font-bold text-gray-900">Current Page</h1>
</div>
```

### Grid Layouts

| Columns    | Classes                                                |
| ---------- | ------------------------------------------------------ |
| 2          | `grid grid-cols-2 gap-3`                               |
| 3          | `grid grid-cols-3 gap-3`                               |
| 4          | `grid grid-cols-4 gap-3`                               |
| Responsive | `grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3` |

---

## Motion & Animation

Animations are defined in your global stylesheet. All animations must respect `prefers-reduced-motion`.

### Available Animations

| Class                  | Duration | Easing                          | Usage                         |
| ---------------------- | -------- | ------------------------------- | ----------------------------- |
| `animate-fadeInUp`     | 500ms    | `cubic-bezier(0.16, 1, 0.3, 1)` | Page entrance, content reveal |
| `animate-tabContentIn` | 150ms    | `ease-out`                      | Tab panel transitions         |
| `animate-slideIn`      | 300ms    | `ease-out`                      | Toast enter                   |
| `animate-slideOut`     | 300ms    | `ease-in`                       | Toast exit                    |

### Staggered Entrances

Use inline `style={{ animationDelay }}` for staggered sequences:

```tsx
<div className="animate-fadeInUp" style={{ animationDelay: '0.2s' }}>
  First element
</div>
<div className="animate-fadeInUp" style={{ animationDelay: '0.5s' }}>
  Second element
</div>
```

### Reduced Motion

All animations are disabled when the user prefers reduced motion. This is handled globally in `index.css`:

```css
@media (prefers-reduced-motion: reduce) {
  .animate-fadeInUp,
  .animate-tabContentIn,
  .animate-slideIn,
  .animate-slideOut {
    animation: none;
  }
}
```

### Guidelines

- **Only animate `transform` and `opacity`** — never animate `width`, `height`, `top`, `left`, `margin`, or `padding`
- **Use `ease-out` variants** for natural deceleration — never `bounce` or `elastic`
- **Keep transitions short** — 150ms for micro-interactions, 300ms for state changes, 500ms max for entrances
- **Tab/panel transitions** should use `animate-tabContentIn` (subtle 4px rise + fade, 150ms)
- **New animations** must be added to the `prefers-reduced-motion` media query

---

## Accessibility

### Focus Ring Standard

All interactive elements must have a visible focus indicator:

```tsx
className = "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2";
```

**Applies to**: buttons, links, nav items, tabs, switches, custom interactive elements.

The `Button`, `Switch`, `Input`, `Select`, and `Tabs` UI primitives include focus rings by default. Add the pattern manually to any custom interactive element.

### Icon-Only Buttons

Every icon-only button must have an explicit `aria-label`:

```tsx
// Correct
<button aria-label="Close dialog" onClick={onClose}>
  <X className="w-4 h-4" />
</button>

// Correct — dynamic label
<button aria-label={isExpanded ? 'Collapse' : 'Expand'}>
  <ChevronDown className="w-4 h-4" />
</button>

// Incorrect — no label
<button onClick={onClose}>
  <X className="w-4 h-4" />
</button>
```

### Touch Target Sizing

Icon-only buttons should have at least a 44x44px touch target. Use padding to expand the hit area:

```tsx
<button className="p-3 -m-3 text-gray-400 hover:text-gray-600" aria-label="Settings">
  <Settings className="w-4 h-4" />
</button>
```

### Color Contrast

- Text on white backgrounds: minimum `text-gray-500` (meets WCAG AA 4.5:1). Never use `text-gray-400` for text that conveys meaning.
- `text-gray-400` is acceptable only for decorative/non-essential metadata (timestamps, footnotes).
- Status indicators must never rely on color alone — always pair with text labels or icons.

### Disabled Interactive Elements

```tsx
<span
  role="link"
  aria-disabled="true"
  tabIndex={0}
  className="opacity-60 cursor-not-allowed"
  onKeyDown={(e) => {
    if (e.key === "Enter" || e.key === " ") e.preventDefault();
  }}
>
  Feature Name
  <span className="text-xs bg-gray-100 px-1.5 py-0.5 rounded ml-2">Soon</span>
</span>
```

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

### Tooltips

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

### KPI Labels

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

### Number Formatting

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

### Data Tables

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

## Page Blueprints

Pages in this app fall into four archetypes: **List**, **Dashboard**, **Detail**, and **Config**. When building a new page or refactoring an existing one, start from the correct blueprint.

### Blueprint A: List Page

For pages with filterable/searchable collections. Uses the full composable hooks chain.

**Characteristics:**

- Filterable/searchable collection
- Selection state
- Pagination
- Status/type segmentation via tabs or pills

**Example pages:** any searchable/filterable collection — an item feed, a work/approval queue, a records list.

**Code template:**

```tsx
export function FeaturePage() {
  const config = usePersonaConfig({
    /* persona-specific config */
  });
  const search = useSearch(mockData, { fields: ["title", "id"] });
  const filters = useFilters(search.results, { status: "all" });
  const sorted = useSort(filters.results, { key: "timestamp", dir: "desc" });
  const page = usePagination(sorted.results, { pageSize: 10 });
  const selection = useSelection();

  useResetOnPersonaChange(() => {
    filters.clearAll();
    search.setQuery("");
    selection.clearSelection();
    // pagination auto-resets via items reference change
  });

  return (
    <div className="space-y-4 animate-fadeInUp">
      <PageHeader title="Feature" actions={/* optional */} />

      <MetricGrid columns={4}>{/* optional KPI row */}</MetricGrid>

      <Tabs defaultValue="all">
        <TabsList variant="underline">{/* segmentation tabs — if needed */}</TabsList>

        <TabsContent value="all">
          <FilterBar>
            <FilterPills /* ... */ />
            <FilterSearch /* ... */ />
          </FilterBar>

          {page.pageItems.length === 0 ? (
            <EmptyState description="No items match your filters" />
          ) : (
            <div className="space-y-2">
              {page.pageItems.map((item) => (
                <ListItemCard key={item.id} /* ... */ />
              ))}
            </div>
          )}

          <Pagination /* ... */ />
        </TabsContent>
      </Tabs>
    </div>
  );
}
```

**Compounds used:** PageHeader, FilterBar, EmptyState, ListItemCard, MetricGrid (optional), Pagination
**Hooks used:** useSearch, useFilters, useSort, usePagination, useSelection, usePersonaConfig, useResetOnPersonaChange

---

### Blueprint B: Dashboard Page

For pages with KPIs, charts, and summary cards. No list state, no pagination.

**Characteristics:**

- KPI metrics in grids
- Charts and visualizations
- Summary cards
- Filtering is optional — some dashboards (e.g., DashboardPage) include a `FilterBar` to scope the data. When present, follow the Filter Tier Model and use the "More Filters" panel pattern for 5+ filters.
- No pagination

**Example pages:** a command-center overview, a domain dashboard, a KPI/health summary.

**Code template:**

```tsx
export function DashboardPage() {
  const config = usePersonaConfig({
    /* persona-specific config */
  });

  return (
    <div className="space-y-4 animate-fadeInUp">
      <PageHeader title="Dashboard" actions={/* optional badges */} />

      <Tabs defaultValue="overview">
        <TabsList variant="underline">{/* domain/category tabs */}</TabsList>

        <TabsContent value="overview">
          <MetricGrid columns={4}>{/* KPI cards */}</MetricGrid>

          <div className="grid grid-cols-2 gap-3">
            <Card>
              <SectionHeader title="Chart Title" actions={/* time filter */} />
              {/* Chart content */}
            </Card>
            <Card>
              <SectionHeader title="Another Section" />
              {/* Content */}
            </Card>
          </div>
        </TabsContent>
      </Tabs>
    </div>
  );
}
```

**Compounds used:** PageHeader, SectionHeader, MetricGrid
**Hooks used:** usePersonaConfig

---

### Blueprint C: Detail Page

For pages showing a single entity. Header with back navigation, tabbed sections of mixed content.

**Characteristics:**

- Single entity view
- Back navigation to parent list
- Tabbed sections
- Entity-level KPIs

**Example pages:** any single-entity detail view reached from a list.

**Code template:**

```tsx
export function DetailPage() {
  const { id } = useParams();

  return (
    <div className="space-y-4 animate-fadeInUp">
      <PageHeader title="Entity Name" backTo="/parent-list" actions={/* status badges, action buttons */} />

      <MetricGrid columns={4}>{/* entity-level KPIs */}</MetricGrid>

      <Tabs defaultValue="overview">
        <TabsList variant="underline">{/* entity sections */}</TabsList>

        <TabsContent value="overview">
          <Card>
            <SectionHeader title="Section One" />
            {/* section content */}
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}
```

**Compounds used:** PageHeader (with `backTo`), SectionHeader, MetricGrid
**Hooks used:** None (detail pages don't have list state)

---

### Blueprint D: Config Page

For admin setup/configuration pages. Form-based, no data visualization.

**Characteristics:**

- Form-based setup/configuration
- Grouped settings cards
- Save/cancel actions
- No KPIs or charts

**Example pages:** admin / settings / configuration pages.

**Code template:**

```tsx
export function AdminFeaturePage() {
  return (
    <div className="space-y-4 animate-fadeInUp">
      <PageHeader title="Feature Configuration" />

      <Card>
        <SectionHeader title="Settings Group" actions={/* save button */} />
        {/* form fields */}
      </Card>

      <Card>
        <SectionHeader title="Another Settings Group" />
        {/* form fields */}
      </Card>
    </div>
  );
}
```

**Compounds used:** PageHeader, SectionHeader
**Hooks used:** None

---

### Compound Applicability by Archetype

| Compound      | List     | Dashboard | Detail                 | Config |
| ------------- | -------- | --------- | ---------------------- | ------ |
| PageHeader    | Always   | Always    | Always (with `backTo`) | Always |
| SectionHeader | Rare     | Always    | Always                 | Always |
| FilterBar     | Always   | Never     | Never                  | Never  |
| EmptyState    | Always   | Rare      | Never                  | Never  |
| MetricGrid    | Optional | Always    | Usually                | Never  |
| ListItemCard  | Always   | Never     | Never                  | Never  |

---

### Hook Applicability by Archetype

| Hook                    | List    | Dashboard | Detail | Config |
| ----------------------- | ------- | --------- | ------ | ------ |
| useSearch               | Always  | Never     | Never  | Never  |
| useFilters              | Always  | Never     | Never  | Never  |
| useSort                 | Usually | Never     | Never  | Never  |
| usePagination           | Always  | Never     | Never  | Never  |
| useSelection            | Usually | Never     | Never  | Never  |
| usePersonaConfig        | Always  | Always    | Never  | Never  |
| useResetOnPersonaChange | Always  | Rare      | Never  | Never  |

---

## Quick Reference

### Don't

- Inline filter bar layout when `FilterBar` exists (use `FilterBar` + `FilterPills`/`FilterSelect`/`FilterSearch`)
- Inline `<div className="flex justify-between mb-3"><h3>` for section titles (use `SectionHeader`)
- Inline `<div className="p-8 text-center">` for empty states (use `EmptyState`)
- Inline `<div className="grid grid-cols-N gap-3">` for metric rows (use `MetricGrid`)
- Inline page title layout (use `PageHeader`)
- Inline selection/hover states on list items (use `ListItemCard`)
- Use `rounded-xl` or larger (use `rounded-lg`)
- Use raw `<select>` elements (use Radix Select)
- Use raw `<input type="checkbox">` for on/off toggles (use `Switch`)
- Use `text-lg` for card titles (use `text-sm font-semibold`)
- Use `p-5` or `p-6` for card padding (use `p-3` or `p-4`)
- Use `w-6 h-6` icons in metadata (use `w-3 h-3`)
- Ship icon-only buttons without `aria-label`
- Use `text-gray-400` for meaningful text (use `text-gray-500` minimum)
- Add icons to page headers (the sidebar already identifies the page)
- Add subtitles/descriptions to page headers (redundant)
- Show all status tabs when most have zero items (hide zero-count tabs)
- Make every button `primary` (one primary CTA per section)
- Use `variant="outline"` for Reject buttons — always use `variant="destructive"` for negative actions (Reject, Delete, Remove, Override, Log Out)
- Use `bounce` or `elastic` easing on animations
- Animate layout properties (`width`, `height`, `margin`, `padding`)

### Do

- Use compound components (`FilterBar`, `SectionHeader`, `EmptyState`, `MetricGrid`, `PageHeader`, `ListItemCard`) instead of inlining their layout
- Check the Compound Components section before building any repeating UI pattern
- Use consistent `rounded-lg` for all cards, buttons, inputs
- Use Radix UI primitives for form controls (`Select`, `Tabs`, `Switch`, `Modal`)
- Use `PageHeader` component for all page headers
- Use `text-sm font-semibold` for card titles
- Use `text-xs` for metadata with `w-3 h-3` icons
- Use `hover:border-primary/30 hover:shadow-md` for card hover
- Use `transition-all duration-200` for smooth transitions
- Add `focus-visible:ring-2 focus-visible:ring-primary` to all custom interactive elements
- Add `aria-label` to every icon-only button
- Hide zero-count status tabs (always show "All" and the active tab)
- Use `animate-fadeInUp` for page entrances
- Add new animations to the `prefers-reduced-motion` media query
- Use `cn()` for conditional class merging
- Use `Button isLoading` for async action feedback
