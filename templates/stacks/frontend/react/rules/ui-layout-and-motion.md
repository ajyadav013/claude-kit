---
paths:
  - "**/*.tsx"
  - "**/*.jsx"
  - "**/*.css"
  - "**/*.scss"
---

# UI Layout & Motion

**All frontend development MUST follow these rules.** Companion to
[`ui-design-system.md`](./ui-design-system.md) (foundations) and
[`ui-components.md`](./ui-components.md) (components).

This file covers **page-level structure and behavior** — layout, motion, accessibility, the four page
blueprints, and the quick do/don't reference.

## Table of Contents

1. [Page Layout](#page-layout)
2. [Motion & Animation](#motion--animation)
3. [Accessibility](#accessibility)
4. [Page Blueprints](#page-blueprints)
5. [Quick Reference](#quick-reference)

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
