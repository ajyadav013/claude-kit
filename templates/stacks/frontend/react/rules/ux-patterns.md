# UX Patterns Reference

**Companion to [`ui-design-system.md`](./ui-design-system.md).**
The design system covers visual primitives (colors, spacing, components). This doc covers **usage rules** — when to use which pattern, content guidelines, and page structure.

---

## 1. Status Expression Rules

### The Standard — Badge Only

Status is expressed through **one pattern**: `<Badge>`. No others are permitted.

| Pattern   | When to use                                                                                         | Example                                              |
| --------- | --------------------------------------------------------------------------------------------------- | ---------------------------------------------------- |
| **Badge** | Anywhere status needs to be shown — KPI tiles, cards, rows, tables, lists. Use `<Badge variant="success\|warning\|error">`. | `<Badge variant="warning">At Risk</Badge>`           |

> **Badges are never interactive.** They display status only. If a status needs to trigger navigation, place a `<Button variant="ghost">` or `<Button variant="link">` alongside the badge — never make the badge itself clickable. See the Badge section in the design system for full rules.

### What is NOT allowed

- **Colored left borders** (`border-l-3 border-l-red-500`, `border-l-4 border-l-amber-500`, any `border-l-<color>` driven by status) — use `<Badge>` instead. Reason: stacks of cards with mixed RAG colors create a "barber-pole" gutter that pulls the eye away from the value the card is meant to communicate.
- **Standalone colored dots** (`w-2 h-2 rounded-full bg-green-500`) — use `<Badge dot>` instead
- **Bold colored text for status labels** (`text-green-700 font-medium` on "Completed") — use `<Badge variant="success">` instead
- **Colored background containers** (`bg-red-50` on a row, `bg-amber-50` shading the whole card) — use `<Badge>` instead

### Migrating existing left-border cards

When touching a file that uses the old `border-l-3 border-l-<color>` pattern, drop the border classes entirely. Keep the status `<Badge>` already in the card — that's the post-rule expression. Remove any status-driven border/background helper calls at the call site (e.g. a `getStatusBorder()` / `STATUS_BORDER` map that colors the card edge by state). The corresponding `<Badge>` already exists in every card that used these — just remove the className wiring.

### The Moderate Rubric for Colored Text

Not all colored text is a status expression. Apply this rule:

> **If a human would read the text aloud as a category/state, it's a label — use Badge.**
> **If they'd read it as a quantity/measurement, it's a value — keep color.**

| Text                               | Type         | Treatment                                              |
| ---------------------------------- | ------------ | ------------------------------------------------------ |
| "On Track", "At Risk", "Completed" | Status label | `<Badge>`                                              |
| "+5.2%", "42 items", "$1.2M"       | Data value   | Keep semantic color (`text-green-700`, `text-red-700`) |
| "Green", "Amber", "Red"            | Status label | `<Badge variant="success\|warning\|error">`            |

### Chart Legend Exemption

Colored dots used as **chart legends** (e.g., in a map view or a detail panel) are data visualization elements, not status indicators. These are **exempt** from the 2-pattern standard.

Progress bars and heatmap cells are also exempt — they are data visualization, not status expression.

---

## 2. Empty State Content Guidelines

### When to Use

Every `.map()` call on a data array must have an empty guard:

```tsx
{items.length === 0 ? (
  <EmptyState description="No items match your filters" />
) : (
  items.map(item => ...)
)}
```

### Content Formula

Each empty state needs:

1. **What's missing** — a clear statement of what would normally appear
2. **Why** (optional) — if the emptiness is likely caused by filters, say so
3. **Recovery CTA** (optional) — an action to resolve the empty state

```tsx
<EmptyState
  description="No exceptions match your current filters"
  action={
    <Button variant="outline" size="sm" onClick={clearFilters}>
      Clear Filters
    </Button>
  }
/>
```

### Tone

- Factual and calm. No apologies ("Sorry, nothing here").
- No emoji, illustrations, or playful language.
- Use present tense: "No agents are idle" not "There are no idle agents."

### Common Descriptions by Context

| Context                    | Description                             |
| -------------------------- | --------------------------------------- |
| Filtered list (no results) | "No {items} match your current filters" |
| Empty table section        | "No {items} to display"                 |
| Empty config list          | "No {items} configured"                 |
| Empty activity feed        | "No recent activity"                    |

---

## 3. Breadcrumb Conventions

### Mobile Rule

**Breadcrumbs MUST NOT render on mobile** (`< lg:` breakpoint). On mobile, the 5-tab bottom navigation bar and page titles provide sufficient wayfinding. Breadcrumb containers must use `hidden lg:flex` to hide on mobile. This applies to `PageHeader` breadcrumbs, inline breadcrumbs, and any custom breadcrumb patterns.

### When to Use (Desktop Only)

All **sub-pages** (pages accessed from a parent page) must use breadcrumbs via `PageHeader`'s `breadcrumbs` prop on desktop. The `backTo` prop is deprecated — always use `breadcrumbs` instead.

### Format

```tsx
<PageHeader title="Detail Name" breadcrumbs={[{ label: "Section", to: "/section" }, { label: "Detail Name" }]} />
```

### Depth Rules

| Depth        | Example                                                                      |
| ------------ | ---------------------------------------------------------------------------- |
| 2-level      | `Section > Detail` — most sub-pages                                          |
| 3-level      | `Section > List > Detail` — when there's an intermediate list page           |
| Max depth: 3 | Never go deeper. If you need 4+ levels, flatten the hierarchy.               |

### TopBar Coordination

When a sub-page shows breadcrumbs, the TopBar title **simplifies to the module name**:

| Route                    | TopBar title |
| ------------------------ | ------------ |
| `/section/item/:id`      | "Section"    |
| `/area/entity/:entityId` | "Area"       |
| `/group/scenarios/:id`   | "Group"      |

The breadcrumbs in `PageHeader` provide the full navigation context. Avoid duplicating the sub-page name in both TopBar and breadcrumbs.

---

## 4. Page Blueprint Selection

Every page follows one of four blueprints. Choose based on the page's primary purpose.

### Decision Tree

```
Is the page showing aggregate metrics & charts?
  → Dashboard

Is the page a filterable collection of items?
  → List

Is the page focused on a single entity?
  → Detail

Is the page for configuration/settings?
  → Config
```

### Blueprint Opening Patterns

| Blueprint     | Opens with                                                     | Notes                                                  |
| ------------- | -------------------------------------------------------------- | ------------------------------------------------------ |
| **Dashboard** | `MetricGrid` → Charts → Summary cards                          | KPIs are the hero. 3-4 MetricCards at top.             |
| **List**      | `FilterBar` → Inline summary strip → List/Table → `EmptyState` | No MetricGrid. Summary counts as a text line.          |
| **Detail**    | `PageHeader` with breadcrumbs → Entity info → Tabbed sections  | Entity name in title. Back navigation via breadcrumbs. |
| **Config**    | `PageHeader` → Tabbed config sections → Forms                  | Admin-oriented. Tabs organize settings.                |

### List Page Summary Strip

List pages replace MetricGrid with an inline text summary:

```tsx
<p className="text-xs text-gray-500 px-1">
  {total} agents · {active} active · {idle} idle · {error} error
</p>
```

This clearly differentiates List pages from Dashboard pages at a glance.

---

## 5. Data Value Color Rules

### When Semantic Color is Appropriate

Semantic color on data values (numbers, percentages, currency) is appropriate when the value communicates **direction** (up/down, good/bad):

| Value                    | Color            | Rationale                   |
| ------------------------ | ---------------- | --------------------------- |
| `+5.2%` (positive delta) | `text-green-700` | Direction: favorable        |
| `-3.1%` (negative delta) | `text-red-700`   | Direction: unfavorable      |
| `42 items on track`      | `text-green-700` | Count categorized by status |
| `3 violations`           | `text-red-600`   | Count requiring attention   |

### When Color is NOT Appropriate

- Neutral values with no directional meaning (total counts, absolute values)
- Values where the direction is ambiguous without context

### Formatting

- Always pair semantic color with `font-medium` or `font-semibold` for emphasis
- Never use `font-bold` with color — it's too loud for the "calm confidence" aesthetic
- Use `text-{color}-700` for text (not 500 or 600 which have insufficient contrast on white)

---

## 6. KPI Label Rules

### When to Use KpiLabel

Wrap any **user-visible abbreviation** in `<KpiLabel abbr="...">` if:

1. The abbreviation is industry-specific (e.g. MRR, ARR, LTV, CAC)
2. A new user might not immediately know what it stands for
3. It appears in a heading, label, table header, or descriptive text

### When NOT to Use

- Inside TypeScript type names, variable names, or import paths
- Inside mock data property keys (only wrap the rendered output)
- When the abbreviation is part of a longer descriptive phrase that already explains it (e.g., "Monthly Recurring Revenue (MRR)")

### Glossary Maintenance

All abbreviations must have entries in a central glossary module (e.g. `@/config/kpiGlossary`). Each entry needs:

- `name` — full expansion
- `definition` — one-sentence explanation
- `formula` (optional) — how it's calculated
- `uom` (optional) — unit of measurement

When adding a new abbreviation to the UI, add its glossary entry first.

---

## 7. Inline Summary Strip Pattern

### Purpose

List pages use an inline text summary instead of MetricGrid to differentiate from Dashboard pages.

### Format

```tsx
<p className="text-xs text-gray-500 px-1">
  {total} {itemType} · {countA} {labelA} · {countB} {labelB}
</p>
```

### Rules

- Place immediately after `FilterBar` (or after page header if no FilterBar)
- Use `text-xs text-gray-500` — subtle, not competing with content
- Separate segments with `·` (middle dot with spaces)
- Show 3-5 segments maximum
- Compute counts from the **filtered** data, not the total dataset
- No icons, badges, or colored text in the strip — plain text only

---

## 14. Destructive Action Styling

### The Rule

**All negative or irreversible actions MUST use `variant="destructive"` (red) styling.** This includes:

| Action | Treatment | Rationale |
|--------|-----------|-----------|
| **Reject** (exception, approval, recommendation) | `variant="destructive"` | Discards agent work, logs a negative outcome |
| **Delete** (record, item, configuration) | `variant="destructive"` | Irreversible data loss |
| **Remove** (team member, permission, access) | `variant="destructive"` | Revokes access |
| **Cancel** (order, PO, scheduled action) | `variant="destructive"` | Stops an in-progress operation |
| **Log Out** | `variant="destructive"` | Ends session, loses unsaved state |
| **Override** (agent recommendation) | `variant="destructive"` | Overrides AI-recommended action |

### What is NOT destructive

| Action | Treatment | Rationale |
|--------|-----------|-----------|
| **Approve** | `variant="primary"` | Positive action, confirms work |
| **Delegate** | `variant="outline"` | Non-destructive, reversible |
| **Snooze** | `variant="outline"` | Temporary, reversible |
| **Close / Dismiss** | `variant="ghost"` | UI navigation, not a data action |
| **Cancel** (in a modal, meaning "go back") | `variant="ghost"` | Not a data action — just closing the dialog |

### Styling: Outline-Destructive (Preferred for Reject)

Use `variant="outline"` with destructive color overrides for a softer, less alarming treatment. This is the preferred style for Reject buttons — the solid red `variant="destructive"` is reserved for truly irreversible actions like Delete.

```tsx
// Reject button — outline with red text + border
<Button
  variant="outline"
  className="border-error/40 text-error hover:bg-error-50 hover:border-error/60"
>
  Reject
</Button>

// Delete button — solid destructive (stronger signal)
<Button variant="destructive">Delete</Button>
```

### In Confirmation Dialogs

When a destructive action requires confirmation (via `ConfirmDialog`), use `variant="destructive"` on the confirm button:

```tsx
<ConfirmDialog
  title="Reject this recommendation?"
  description="Rejecting removes this item from the queue."
  confirmLabel="Reject and log reason"
  variant="destructive"
  onConfirm={handleReject}
/>
```

---

## 15. Mobile BottomSheet Rule

### The Rule

**On mobile (`< lg:` breakpoint), ALL overlay menus, dropdown menus, filter pickers, sort menus, and select options MUST open in a `BottomSheet` instead of a dropdown/popover/overlay menu.** This is an app-wide rule.

| Desktop Component | Mobile Replacement |
|---|---|
| `DropdownMenu` (Radix) | `BottomSheet` with tappable rows (48px touch targets) |
| `Select` dropdown | `BottomSheet` with option list + check icon |
| Filter popover | `MobileFilterSheet` (existing) or `BottomSheet` |
| Sort dropdown | `BottomSheet` with sort options + check icon |
| Overflow menu (kebab `⋮`) | `BottomSheet` with action list |

### Why

- Touch targets: BottomSheet rows are `min-h-12` (48px) — dropdown items are often too small
- Thumb reachability: BottomSheet slides up from bottom — the interaction zone is in the thumb zone
- No accidental dismissal: BottomSheet has explicit close (X, swipe-down, backdrop tap)
- Consistent with iOS/Android native patterns

### Implementation

Components that already handle this internally via `useIsMobile()`:
- `FilterSelect` → opens BottomSheet on mobile
- `FilterMultiSelect` → opens BottomSheet on mobile
- `FilterDateRange` → opens BottomSheet on mobile

Components that need explicit mobile handling:
- `DropdownMenu` → wrap with `useIsMobile()` check, render `BottomSheet` on mobile
- Custom sort menus → use `BottomSheet` on mobile (already done in Dashboard Zone 2)
- Tab switchers → use `BottomSheet` on mobile (already done in Dashboard Zone 5)

---

## Touch Target Extension (Invisible Tap Area)

Interactive elements may be visually smaller than 44px (e.g., 32px icon buttons in the TopBar). Rather than enlarging the visible element, extend the **tappable area** using an invisible overlay.

### Pattern

```tsx
<button className="relative w-8 h-8 ...">
  <span className="absolute -inset-1.5" aria-hidden="true" />
  <Icon className="w-4 h-4" />
</button>
```

The `<span>` with `absolute -inset-*` extends the hit zone beyond the button's visual bounds. `aria-hidden="true"` keeps it invisible to screen readers.

### Inset Values by Base Size

| Visible Size | Class | Tap Area |
|-------------|-------|----------|
| 20px (`w-5 h-5`) | `-inset-3` | 44px |
| 24px (`w-6 h-6`) | `-inset-2.5` | 44px |
| 32px (`w-8 h-8`) | `-inset-1.5` | 44px |
| 36px (`w-9 h-9`) | `-inset-1` | 44px |
| 40px (`w-10 h-10`) | `-inset-0.5` | 44px |

### Rules

- The button **must** have `relative` positioning
- The span **must** have `aria-hidden="true"`
- Apply to **all** interactive elements smaller than 44px
- Do NOT resize the visible element — only extend the invisible tap zone
- This pattern applies on all devices (not just touch) since the invisible span doesn't affect visual layout

---

## 16. Drilldown Table Text Color Rule

### The Rule

**All text in drilldown/data table cells and table action controls (Expand All, Collapse) MUST use neutral gray colors.** No `text-primary`, `text-indigo-*`, or `text-blue-*` is permitted in table cells or table-level controls.

### Permitted Colors

| Element | Color | Class |
|---------|-------|-------|
| Parent row name | Dark, bold | `text-gray-900 font-semibold` |
| Child row name | Medium, medium-weight | `text-gray-700 font-medium` |
| Grandchild row name | Muted | `text-gray-600` |
| Data values | Standard | `text-gray-700` |
| Table actions (Expand/Collapse) | Muted interactive | `text-gray-500 hover:text-gray-700` |

### Exemptions

- **Directional data values** (deltas like `+5.2%`, `-3.1%`) may use semantic color per [Data Value Color Rules](#5-data-value-color-rules)
- **RAG status badges** inside table cells follow the [Status Expression Rules](#1-status-expression-rules)
- **Filter pills and tabs** above/outside the table may use `text-primary` for active states — they are interactive controls, not table content

### Why

Primary/indigo text in data tables creates visual noise and falsely implies clickability. Data tables should feel calm and scannable. Color should only carry semantic meaning (directional values, status), never decoration.

### ESLint Enforcement

`text-indigo-*` classes are banned in application code via a lint rule (error severity), enforced in CI / pre-commit.

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

## 21. Button Ordering Rule (Mandatory)

### The Rule

When two or more buttons are placed side-by-side (horizontally), they MUST be ordered **right-to-left by visual weight**: primary → destructive → outline → ghost.

The **primary action is always rightmost**. Secondary actions cascade to its left in descending visual weight.

### Visual Weight Hierarchy (right → left)

| Position | Variant | Use for |
|----------|---------|---------|
| Rightmost | `primary` (filled) | The main action — Approve, Save, Confirm, Submit |
| Next left | `outline-destructive` | Destructive secondary — Reject, Delete, Remove |
| Next left | `outline` | Neutral secondary — Modify, Cancel, Create Task |
| Leftmost | `ghost` | Tertiary — Close, Dismiss, Back |

### Examples

```tsx
// ✅ Correct — primary rightmost
<div className="flex items-center gap-2">
  <Button variant="outline">Cancel</Button>
  <Button variant="outline-destructive">Reject</Button>
  <Button>Approve</Button>
</div>

// ✅ Correct — two buttons
<div className="flex items-center gap-2">
  <Button variant="outline">Cancel</Button>
  <Button>Save</Button>
</div>

// ❌ Wrong — primary on the left
<div className="flex items-center gap-2">
  <Button>Approve</Button>
  <Button variant="outline-destructive">Reject</Button>
</div>
```

### Applies to

- Modal footers (`ModalFooter`)
- Detail panel action rows
- Batch action toolbars
- Form submit rows
- Confirmation dialogs
- Any horizontal button group with 2+ buttons

### Exceptions

- **Inline toggle pairs** (e.g., view mode switches) follow their own pattern
- **Icon-only button groups** in toolbars are ordered by frequency, not weight
- **Mobile stacked buttons** (vertical layout) follow top-to-bottom = primary → secondary

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

## 22. Date Format Rules

> **Scope:** Every user-facing date rendered in the app — picker buttons, table cells, headers, body copy, tooltips. Internal/wire formats (API payloads, localStorage, URL params) are unaffected and continue to use ISO `YYYY-MM-DD`.

### The Rule

| Context | Format | Example | Rationale |
|---------|--------|---------|-----------|
| **Actionable** (date pickers, date inputs, range filter button) | `DD/MM/YYYY` | `02/06/2026` | Compact, easy to scan as a pair (`01/04/2026 – 30/04/2026`); pick one regional order and keep it. |
| **Display** (text labels, tooltips, table cells, headers, captions) | `MMM DD, YYYY` | `Jun 02, 2026` | Eliminates day/month ambiguity (`02/06` vs `06/02`), reads as prose, locale-stable. |
| **Wire** (API params, ISO storage, sort keys) | `YYYY-MM-DD` | `2026-06-02` | Machine-parseable, sortable, never shown to users. |
| **Relative time** (< 7 days, real-time feel) | `"X ago"` | `2 hours ago` | Use `formatRelativeTime()`; falls back to display format after 7 days. |

### Canonical helpers

Always go through your shared date helpers (e.g. `@/lib/utils`) — do **not** inline `toLocaleDateString` in components:

| Helper | When to use | Output |
|--------|-------------|--------|
| `formatDate(d)` | Any display-only date | `Jun 2, 2026` (matches the display rule above) |
| `formatDateTime(d)` | Display date + time together | `Jun 2, 2026, 4:32 PM` |
| `formatRelativeTime(d)` | Recent timestamps (< 7 days), comments, activity feeds | `2 hours ago` → falls back to `formatDate` |
| `formatWeekRange(iso)` | 7-day bucket labels (calendar, week-over-week) | `Mar 29 – Apr 4, 2026` |
| `getDataAvailableThroughDateIso()` | Default date range in filter stores | `2026-06-02` (T-2 ISO) |

The date-range picker (`FilterDateRange` in `@/components/ui/FilterBar`) already renders its button as `DD/MM/YYYY` via the local `fmtDisplay()` helper — that one is bespoke (and correct) because it round-trips with `dd/mm/yyyy` text input parsing.

### Don'ts

| Don't | Why |
|-------|-----|
| Inline `date.toLocaleDateString('en-US', { ... })` in a component | Drifts from the convention silently; use `formatDate()` instead. |
| Mix `en-US` (`Jun 2`) and `en-GB` (`2 Jun`) on the same screen | Inconsistent visual rhythm, confuses users. |
| Show display dates without the year (e.g. `Jun 02`) | Ambiguous for old/archived rows; always include the year on full display dates. |
| Use `DD/MM/YYYY` in body text | It's the actionable format; in prose it reads as a form value, not a date. |
| Use `MMM DD, YYYY` inside a date picker pill | Wastes horizontal space; pickers are scanned, not read. |
