---
paths:
  - "**/*.tsx"
  - "**/*.jsx"
  - "**/*.css"
  - "**/*.scss"
---

# UX Dashboard Patterns

**Companion to [`ux-patterns.md`](./ux-patterns.md)** and [`ui-design-system.md`](./ui-design-system.md).
This doc covers the **dashboard-specific usage rules**: chart standards, tab-bar limits, KPI-grid
layouts, and the global filter strip. General status, empty-state, content, and page-structure rules
live in [`ux-patterns.md`](./ux-patterns.md). Section numbers below match the original source ordering.

---

## 17. Chart Standards

### Library

**Recharts only.** No other chart library (d3, chart.js, nivo, visx) is permitted. All charts use `<ResponsiveContainer>` as the outermost wrapper.

### Data Colors — `@/config/chartColors`

All data-encoding colors (series fills, strokes, status) MUST come from the centralized palette. Never hardcode hex values for data colors.

| Token | Value | When to use |
|-------|-------|------------|
| `CHART_PRIMARY` | `#______` | Single-series bars, lines, areas (your primary token) |
| `CHART_BASELINE` | `#9ca3af` | Target / reference lines |
| `CHART_SEQUENTIAL` | 6 indigo shades | Parts-of-whole (subcategories, tiers) |
| `CHART_CATEGORICAL` | 8 distinct hues | Comparing independent entities (regions, scenarios) |
| `CHART_STATUS` | green/amber/red/gray | RAG health encoding |
| `CHART_DIVERGING` | indigo + orange | Positive vs negative values (variance, margin flow) |

### Chrome Colors — `@/config/chartColors`

Grid lines, axis text, and tooltip borders MUST use the centralized chrome constants. Never hardcode `#f3f4f6`, `#9ca3af`, `#6b7280`, or `#e5e7eb` inline.

| Token | Value | Usage |
|-------|-------|-------|
| `CHART_GRID` | `#f3f4f6` | `<CartesianGrid stroke={CHART_GRID} />` |
| `CHART_AXIS_TICK` | `#9ca3af` | `tick={{ fill: CHART_AXIS_TICK }}` (numeric labels) |
| `CHART_AXIS_LABEL` | `#6b7280` | `tick={{ fill: CHART_AXIS_LABEL }}` (category labels) |
| `CHART_BORDER` | `#e5e7eb` | Tooltip border, axis line stroke |

### Mobile Responsiveness (Mandatory)

Every chart MUST handle mobile via `useIsMobile()`:

```tsx
const isMobile = useIsMobile();

<XAxis
  tick={{ fontSize: isMobile ? 10 : 12, fill: CHART_AXIS_TICK }}
  interval={isMobile ? "preserveStartEnd" : 0}
/>
<YAxis hide={isMobile} />
```

**Rules:**
- Hide Y-axis on mobile (`hide={isMobile}`)
- Reduce tick font size to 10px on mobile
- Use `interval="preserveStartEnd"` on X-axis to avoid label overlap
- Bar charts: reduce `barSize` on mobile (e.g., `barSize={isMobile ? 32 : 48}`)

### Anti-Patterns

| Don't | Do Instead |
|-------|------------|
| Hardcode `stroke="#f3f4f6"` | Use `stroke={CHART_GRID}` from `chartColors.ts` |
| Hardcode `fill: '#9ca3af'` | Use `fill: CHART_AXIS_TICK` from `chartColors.ts` |
| Hardcode `border: '1px solid #e5e7eb'` | Use `` `1px solid ${CHART_BORDER}` `` |
| Use API-provided colors for pie charts | Use `CHART_CATEGORICAL` or `CHART_SEQUENTIAL` |
| Same chart at all breakpoints | Add `useIsMobile()` + hide Y-axis + reduce fonts |
| Use `#f0f0f0` for grids | Use `CHART_GRID` (`#f3f4f6` = gray-100) |

---

## 18. Tab Bar Rules

### The Rule

**Maximum 5 tabs per row.** A page-level `<TabsList>` MUST never render more than 5 sibling `<TabsTrigger>` elements in a single row.

If a feature needs more than 5 logical sections, choose one of:

| Pattern | When |
|---------|------|
| **Consolidate** — merge related tabs into a parent tab with sub-sections | Two tabs share a domain or audience (e.g. "Stores" + "Distribution" → "Store & Distribution") |
| **Promote to L2 navigation** — split into separate L2 panel routes | Sections are independently navigable and bookmarkable (different URLs) |
| **Demote to filter or pills** inside one tab | Sections are facets of the same data, not different views (use `FilterPills` instead) |

### Why

- **Cognitive load** — humans struggle to scan more than ~5 sibling choices at once. Beyond that, a tab bar reads as a navigation menu, not a view selector.
- **Mobile horizontal scroll** — `<TabsList>` is `overflow-x-auto`. Six or more tabs guarantees scrolling on every viewport ≤768px and most laptops at 1024px, hiding tabs behind the right edge.
- **Information architecture signal** — needing >5 tabs usually means the sections aren't peers; they belong in nested navigation.

### Information Hierarchy Rule (KPI Strips)

Hero / health-strip KPIs MUST live **inside the most-relevant tab**, never in a global strip above the `<TabsList>`. Reasons:

1. KPIs above the tabs imply they apply to every tab, but they almost always reflect one tab's domain (e.g. revenue metrics belong in the Revenue tab).
2. Anchoring KPIs to a tab keeps the page top-frame compact — only the briefing/insights banner sits above tabs, not metric cards.
3. Switching tabs makes the relevant KPIs swap into view, which reinforces the tab's domain.

If a metric truly applies to every tab, it belongs in the briefing/insights banner above the tabs, not in a 6-card strip.

### Examples

```tsx
// GOOD — exactly 5 tabs, KPI strip lives inside the relevant tab
<Tabs>
  <TabsList variant="underline">
    <TabsTrigger value="performance">Performance</TabsTrigger>
    <TabsTrigger value="activity">Activity & Options</TabsTrigger>
    <TabsTrigger value="inventory">Inventory & Lifecycle</TabsTrigger>
    <TabsTrigger value="stores">Stores & Distribution</TabsTrigger>
    <TabsTrigger value="supply">Supply</TabsTrigger>
  </TabsList>
  <TabsContent value="activity">
    <HealthStrip />     {/* KPIs scoped to this tab */}
    <ActivityCharts />
  </TabsContent>
</Tabs>

// BAD — 6 tabs, KPIs floating above the tabs as a global strip
<>
  <HealthStrip />        {/* implies these apply to every tab below */}
  <Tabs>
    <TabsList>
      <TabsTrigger>Performance</TabsTrigger>
      <TabsTrigger>Activity</TabsTrigger>
      <TabsTrigger>Inventory</TabsTrigger>
      <TabsTrigger>Stores</TabsTrigger>
      <TabsTrigger>Distribution</TabsTrigger>
      <TabsTrigger>Supply</TabsTrigger>     {/* 6th tab — split or consolidate */}
    </TabsList>
  </Tabs>
</>
```

### Anti-Patterns

| Don't | Do Instead |
|-------|------------|
| 6+ sibling `<TabsTrigger>` elements in one `<TabsList>` | Consolidate, promote to L2, or demote to filter pills |
| Global hero/health KPI strip above the tabs | Move the strip into the tab whose domain it describes |
| Hide overflow tabs behind a "More" dropdown | If you need a "More" overflow, the IA is wrong — re-architect |
| Wrap the tab row to a second line (`flex-wrap`) on narrow viewports | Stick to single-row + horizontal scroll; if it scrolls, you have too many tabs |

---

## 19. KPI Grid Layout Rules

> **Scope:** This rule applies to all KPI / metric strips **outside the persona-driven dashboard tabs**. For KPI cards rendered inside `<TabsContent>` on persona-driven dashboards, use the dashboard-specific pattern in **Section 20** instead.

### The Rule

**Maximum 5 KPI cards per row.** Any KPI / metric strip with 6+ cards MUST wrap to a second row, never extend the first row beyond 5 columns.

This is enforced by `<MetricGrid>` (`@/components/ui/MetricGrid`), which only accepts `columns: 2 | 3 | 4 | 5`. Always use `<MetricGrid>`. Never bypass it with a raw `grid grid-cols-6` (or higher) container, even with an `eslint-disable` comment.

### Row Distribution

| KPI count | Use | Result |
|-----------|-----|--------|
| 2 | `<MetricGrid columns={2}>` | 2 in a row |
| 3 | `<MetricGrid columns={3}>` | 3 in a row |
| 4 | `<MetricGrid columns={4}>` | 4 in a row |
| 5 | `<MetricGrid columns={5}>` | 5 in a row |
| 6 | `<MetricGrid columns={5}>` | 5 + 1 (last card spans one column on row 2) |
| 7 | `<MetricGrid columns={4}>` | 4 + 3 (more balanced than 5 + 2) |
| 8 | `<MetricGrid columns={4}>` | 4 + 4 |
| 9 | `<MetricGrid columns={5}>` | 5 + 4 |
| 10 | `<MetricGrid columns={5}>` | 5 + 5 |
| 10+ | Re-think the strip — split across tabs or move to a detail panel | — |

When a count splits awkwardly (e.g. 6 = 5 + 1, 7 = 5 + 2), pick the column count that produces the most balanced distribution from the table above. A leftover single card in row 2 is acceptable; a leftover *gap* (empty grid cells) is not — `<MetricGrid>` handles this automatically by collapsing rather than padding.

### Why

- **Scannability** — beyond 5 columns, individual labels and values blur into a wall of text, especially with long currency-prefixed values.
- **Card width threshold** — at 1280px viewport, 6 columns drops each card to ~190px wide, which truncates labels like "Net Revenue vs Plan" or "Customer Retention". 5 columns keeps cards ≥230px.
- **Mobile collapses to 2 columns anyway** — `<MetricGrid>` always renders `grid-cols-1 xs:grid-cols-2` on mobile/tablet, so the desktop column count only matters at `lg:` and above. A single source of truth (`<MetricGrid>`) handles the responsive behavior.

### Examples

```tsx
// GOOD — 6 KPIs wrap as 5 + 1
<MetricGrid columns={5}>
  {sixKpis.map((kpi) => <MetricCard key={kpi.id} {...kpi} />)}
</MetricGrid>

// GOOD — 4 KPIs in a tight row
<MetricGrid columns={4}>
  {fourKpis.map((kpi) => <MetricCard key={kpi.id} {...kpi} />)}
</MetricGrid>

// BAD — bypasses MetricGrid to force 6 cards in one row
<div className="grid grid-cols-2 lg:grid-cols-3 xl:grid-cols-6 gap-3">
  {sixKpis.map((kpi) => <MetricCard key={kpi.id} {...kpi} />)}
</div>
```

### Anti-Patterns

| Don't | Do Instead |
|-------|------------|
| Raw `grid grid-cols-6` (or 7, 8…) for KPI cards | `<MetricGrid columns={5}>` and let row 2 take the overflow |
| Use an `eslint-disable` comment to escape the cap | Reduce cards or accept the 2-row layout |
| Mixed sized cards in one row to fit more in | Keep all cards uniform; if you need different sizes, they're not peers — split into separate sections |
| Different column counts for the same KPI strip across pages | Pick one column count per logical strip and use it consistently |

---

## 20. Dashboard KPI Grid Pattern

> **Scope:** This rule applies to KPI cards rendered inside `<TabsContent>` on persona-driven dashboards. A relocated hero KPI strip (a per-tab `<HealthStrip>`) is included — it lives inside its most-relevant tab. For all other KPI strips, use **Section 19** (`<MetricGrid>`).

### The Rule

Dashboard KPI cards use a viewport-aware layout with a mobile-only "View more / View less" toggle. **Always use a dedicated `<DashboardKpiGrid>` component.** Never hand-roll the responsive grid.

| Viewport | Cols per row | Cap (collapsed) | Toggle? |
|----------|--------------|-----------------|---------|
| `<430px` (mobile small) | 1 | 4 | Yes — `View more (+N)` / `View less` ghost button below the grid |
| `430-1023px` (mobile larger / tablet) | 2 max | 8 (= 4 rows × 2 cols) | Yes — same toggle |
| `≥1024px` (desktop) | up to 4 (fill space when count < 4) | None | No toggle, all cards always render |

### Desktop Fill-Space Behavior

When the KPI count is **less than 4** on desktop, the grid uses exactly that many columns (each card 1/N width). When the count is **more than 4**, the grid uses 4 columns and rows wrap with **consistent 1/4 column width** on every row — the last row is left-aligned with empty space on the right (rather than stretching the trailing cards to fill).

| Count | Desktop layout |
|-------|----------------|
| 1 | 1 col × full width |
| 2 | 2 cols × 1/2 each |
| 3 | 3 cols × 1/3 each (fill) |
| 4 | 4 cols × 1/4 each |
| 5 | row 1: 4 × 1/4, row 2: 1 × 1/4 (left-aligned) |
| 6 | 4 + 2 |
| 7 | 4 + 3 |
| 8 | 4 + 4 |
| 9 | 4 + 4 + 1 |
| 10 | 4 + 4 + 2 |

### Toggle Behavior

- Default state on mobile: **collapsed** (only `cap` cards visible).
- Tap "View more (+N)" → expands to show all cards at the same column count.
- Button label flips to "View less" → tap to collapse back to `cap` cards.
- Toggle is mobile-only (`lg:hidden`); on desktop the button never renders and all children always show.
- State is local to the component and resets on tab switch / route change.

### Wireframes

**3 cards (under all caps, no toggle on any viewport):**

```
Desktop                                      Mobile larger              Mobile small
┌──────┬──────┬──────┐                       ┌──────┬──────┐            ┌──────────┐
│ KPI1 │ KPI2 │ KPI3 │                       │ KPI1 │ KPI2 │            │   KPI1   │
└──────┴──────┴──────┘                       ├──────┼──────┘            ├──────────┤
                                             │ KPI3 │                   │   KPI2   │
                                             └──────┘                   ├──────────┤
                                                                        │   KPI3   │
                                                                        └──────────┘
```

**6 cards (4 + 2 on desktop, 3 × 2 on mobile larger, 4 + toggle on mobile small):**

```
Desktop (4 + 2)                              Mobile larger (3 × 2)       Mobile small collapsed
┌──────┬──────┬──────┬──────┐                ┌──────┬──────┐             ┌──────────┐
│ KPI1 │ KPI2 │ KPI3 │ KPI4 │                │ KPI1 │ KPI2 │             │   KPI1   │
├──────┼──────┴──────┴──────┘                ├──────┼──────┤             ├──────────┤
│ KPI5 │ KPI6 │                              │ KPI3 │ KPI4 │             │   KPI2   │
└──────┴──────┘                              ├──────┼──────┤             ├──────────┤
                                             │ KPI5 │ KPI6 │             │   KPI3   │
                                             └──────┴──────┘             ├──────────┤
                                                                         │   KPI4   │
                                                                         └──────────┘
                                                                         [View more (+2)]
```

**10 cards (4 + 4 + 2 on desktop, cap-8 on mobile larger, cap-4 on mobile small — both with toggle):**

```
Desktop (4 + 4 + 2)                          Mobile larger collapsed     Mobile small collapsed
┌──────┬──────┬──────┬──────┐                ┌──────┬──────┐             ┌──────────┐
│ KPI1 │ KPI2 │ KPI3 │ KPI4 │                │ KPI1 │ KPI2 │             │   KPI1   │
├──────┼──────┼──────┼──────┤                ├──────┼──────┤             ├──────────┤
│ KPI5 │ KPI6 │ KPI7 │ KPI8 │                │ KPI3 │ KPI4 │             │   KPI2   │
├──────┼──────┴──────┴──────┘                ├──────┼──────┤             ├──────────┤
│ KPI9 │ KPI10│                              │ KPI5 │ KPI6 │             │   KPI3   │
└──────┴──────┘                              ├──────┼──────┤             ├──────────┤
                                             │ KPI7 │ KPI8 │             │   KPI4   │
                                             └──────┴──────┘             └──────────┘
                                             [View more (+2)]            [View more (+6)]
```

### Implementation

```tsx
import { DashboardKpiGrid } from '@/components/ui';

<DashboardKpiGrid>
  {kpis.map((kpi) => (
    <MetricCard key={kpi.id} label={kpi.label} value={kpi.value} />
  ))}
</DashboardKpiGrid>
```

The component owns the responsive grid math and the toggle state. Consumers pass children only.

### Anti-Patterns

| Don't | Do Instead |
|-------|------------|
| Use `<MetricGrid>` for KPI cards inside persona-driven dashboard tabs | Use `<DashboardKpiGrid>` — Section 20 supersedes Section 19 within these tabs |
| Hand-roll the responsive grid (`grid-cols-1 xs:grid-cols-2 lg:grid-cols-4`) | Use `<DashboardKpiGrid>`; the responsive math is encapsulated |
| Render a "View more" button on desktop | The toggle is mobile-only by design — desktop never collapses |
| Persist the expanded state across tab switches | Default behavior is correct: state resets on tab switch (component remounts). Adding persistence requires a separate store and is out of scope for this pattern |
| Bypass the cap with `smallMobileCap={999}` to disable the toggle | If your tab has too many KPIs to fit the cap, reduce the KPI count — don't escape the pattern |

---

## Global Filter Strip

The standard chrome that sits above tabs on any dashboard-style page. Filter chips drive a single, batched BE refetch — never one call per chip click.

### Why batched

The dashboard endpoints behind these pages can be expensive analytical queries that take several seconds per call. If every chip change triggered a fresh refetch, picking 3 filters would trigger 3 cold-cache queries. We hold all draft selections locally and only fire the BE call when the user is done picking — one request per intentional change.

### The pattern (draft → applied)

There are two layers of state for filters on every page:

| Layer | Owner | What it holds | Who reads it |
|---|---|---|---|
| **Draft** | Zustand store (`useXFilterStore.filters`) | The chip values the user is currently editing | The chip components themselves, the cascading `/filters` options call |
| **Applied** | Page-level `useState<XFilters>` | The snapshot the BE last saw | Every tab component — passed in as a `filters` prop |

The dirty check is a single line:
```ts
const filtersChanged = filterKey(filters) !== filterKey(appliedFilters);
```

Where `filterKey(f)` is `Object.values(f).join('|')` — a stable string serializer exported alongside each page's filter store.

### The two Apply buttons

There are **two distinct Apply actions** in the flow. Don't conflate them.

1. **Per-chip Apply** — inside each `FilterMultiSelect` dropdown (and `MobileFilterSheet` on mobile). Built into the primitive in `@/components/ui/FilterBar`. Clicking it commits the chip's local draft to `filters` (the store) and closes the dropdown. The chip pill updates to show a count like `Format (1)`. **No BE call fires yet.**
2. **Global Apply Filters** — a `<Button variant="primary">` rendered in the FilterBar after "More filters" and before "Clear filters". Renders **only when `filtersChanged === true`**. Clicking it sets `appliedFilters = filters`, which propagates as the `filters` prop to all tab components, triggering exactly **one** React Query refetch chain (KPIs, charts, tables — one BE call per endpoint).

### The Clear button

`<FilterClear>` is rendered to the right of the Apply Filters button and is visible when `hasActiveFilters()` is true. Clicking it must reset **both layers** in one shot:
```ts
const handleClearAllFilters = () => {
  clearFilters();                            // resets draft (store)
  setAppliedFilters(getDefaultXFilters());   // resets applied (useState)
};
```

### Filter chip order

Every dashboard's primary filter row follows the **same column ordering**:

1. **Date range** (or the primary time filter)
2. **Primary dimension** (your top-level facet)
3. **Secondary dimension**
4. **Hierarchy parent** (a drill-down facet)
5. **Hierarchy child** *(must be adjacent to its parent — they're read together as a hierarchy)*
6. *Page-specific chips* — in order of operational importance for that view
7. **More filters** toggle — hides the rarely-used chips
8. **Apply Filters** (conditional — appears when dirty)
9. **Clear filters** (conditional — appears when any filter is non-default)

**Hard rule**: a hierarchy parent and its child are ALWAYS adjacent in the visible primary row. Never collapse the child into "More filters" while leaving the parent outside. If your taxonomy adds a third level later, append it to the same hierarchy block.

### Mobile

`MobileFilterSheet` (`@/components/ui/MobileFilterSheet`) already implements the draft → applied gate internally:
- All chip changes update an in-sheet `draft` object
- A single "Apply" button at the bottom commits draft → calls `onApply(draftValues)`
- The page's `handleMobileFilterApply` writes the draft values BOTH to the store (via `setFilter` per key) AND to `appliedFilters` in one shot — so mobile gets one BE call per Apply tap, with no separate global Apply step needed.

### Cascading filter options (`/filters`)

The cascading-options call (subcategory list narrows when category changes) stays keyed on the **draft** (live store filters), not applied. The options endpoint is cheap and cached; the user should see option lists narrow as they pick. This is the only legitimate exception to "draft doesn't trigger BE."

### Building a new dashboard or filter strip

**Required**:
- Store exports a `xFilterKey(f)` helper (same `Object.values().join('|')` shape).
- Page holds `const [appliedFilters, setAppliedFilters] = useState(filters)`.
- Page renders the Apply Filters button conditionally via `filtersChanged`.
- All tabs / sections receive `filters` as a prop — they DO NOT subscribe to the store for filter values. (Subscribing to non-filter store state like UI toggles is fine.)
- `handleClearAllFilters` resets both layers.
- Mobile `handleMobileFilterApply` commits to both layers.

**Forbidden**:
- Letting any tab component call `useXFilterStore((s) => s.filters)` for API-driving filter values. This breaks the gate — selections leak past the Apply button.
- Hiding a hierarchy child behind "More filters" while its parent is visible. Always adjacent.
- Adding a third Apply variant (e.g. per-tab apply). One global Apply per page.

### Canonical reference implementation

Keep one canonical reference implementation — a dashboard page with the `appliedFilters` useState, the `filtersChanged` dirty check, and the conditional Apply button — and mirror it across the other dashboard pages.

---
