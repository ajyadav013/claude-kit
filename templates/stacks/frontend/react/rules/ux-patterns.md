# UX Patterns Reference

**Companion to [`ui-design-system.md`](./ui-design-system.md)** (and its `ui-components.md` /
`ui-layout-and-motion.md` companions).
The design system covers visual primitives (colors, spacing, components). This doc covers **usage rules** — when to use which pattern, content guidelines, and page structure.

Dashboard-specific usage rules — chart standards, tab-bar limits, KPI-grid layouts, and the global
filter strip — live in the companion **[`ux-dashboard-patterns.md`](./ux-dashboard-patterns.md)**.

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
