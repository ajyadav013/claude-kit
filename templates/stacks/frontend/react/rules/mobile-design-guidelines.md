---
paths:
  - "**/*.tsx"
  - "**/*.jsx"
  - "**/*.css"
  - "**/*.scss"
---

# Mobile Design Guidelines

**Consolidated mobile design reference for the application.**
Covers responsive layout, touch interactions, native app (Capacitor), and established mobile UX patterns.

---

## Table of Contents

1. [Breakpoint Strategy](#breakpoint-strategy)
2. [Layout Rules](#layout-rules)
3. [Touch Targets](#touch-targets)
4. [Typography](#typography)
5. [Spacing](#spacing)
6. [Navigation](#navigation)
7. [BottomSheet Pattern](#bottomsheet-pattern)
8. [Filter Pattern](#filter-pattern)
9. [Swipe-to-Dismiss](#swipe-to-dismiss)
10. [Tab Scroll Indicators](#tab-scroll-indicators)
11. [Mobile Card Simplification](#mobile-card-simplification)
12. [Forms](#forms)
13. [Tables](#tables)
14. [Charts](#charts)
15. [Modals & Panels](#modals--panels)
16. [Images & Media](#images--media)
17. [Overflow & Truncation](#overflow--truncation)
18. [Breadcrumbs](#breadcrumbs)
19. [Capacitor Native App](#capacitor-native-app)
20. [Safe Areas (iOS)](#safe-areas-ios)
21. [Testing Responsive Behavior](#testing-responsive-behavior)
22. [Anti-Patterns](#anti-patterns)
23. [Grid Fix Pattern Reference](#grid-fix-pattern-reference)

---

## Breakpoint Strategy

Use Tailwind's mobile-first responsive prefixes. **Write mobile styles first, then layer on desktop overrides.**

| Prefix | Min Width | Target |
|--------|-----------|--------|
| (none) | 0px | Mobile small (single-column layouts) |
| `xs:` | 430px | Larger mobile / two-column threshold (custom — define `--breakpoint-xs` in your global stylesheet) |
| `sm:` | 640px | Large phones / small tablets |
| `md:` | 768px | Tablets |
| `lg:` | 1024px | Desktop |
| `xl:` | 1280px | Large desktop |

```tsx
// GOOD — mobile-first
<div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-3">

// BAD — desktop-first (breaks on mobile)
<div className="grid grid-cols-4 gap-3">
```

### Supported Viewports

| Width | Device | Role |
|-------|--------|------|
| 375px | iPhone SE | Smallest supported width |
| 768px | iPad | Tablet breakpoint |
| 1024px | Laptop | Desktop breakpoint |
| 1440px | Large desktop | Wide layout |

---

## Layout Rules

### Grids

```tsx
// GOOD — generic KPI strips (outside dashboard tabs)
// Encapsulates 1-col mobile -> 2-col xs (430px+) -> N-col desktop (N <= 5)
<MetricGrid columns={4}>
  {kpis.map((k) => <MetricCard key={k.id} label={k.label} value={k.value} />)}
</MetricGrid>

// GOOD — dashboard KPI cards under tabs (cap + View more / View less toggle on mobile)
// See ux-dashboard-patterns.md (Dashboard KPI Grid Pattern) for the full spec
<DashboardKpiGrid>
  {kpis.map((k) => <MetricCard key={k.id} label={k.label} value={k.value} />)}
</DashboardKpiGrid>

// BAD — hand-rolled raw grid for KPI cards (bypasses both primitives)
<div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">

// Content + sidebar: stack on mobile, side-by-side on desktop
<div className="flex flex-col lg:flex-row gap-4">
  <main className="flex-1">{/* content */}</main>
  <aside className="w-full lg:w-80">{/* sidebar */}</aside>
</div>
```

### Dashboard KPI Grid

KPI cards rendered inside `<TabsContent>` on persona-driven dashboards follow a special responsive pattern: max 4 cards per row on desktop (≥1024px) with fill-space behavior when count < 4, 2 per row + cap of 8 on larger mobile (430-1023px), 1 per row + cap of 4 on small mobile (<430px), and a "View more / View less" ghost button toggle on both mobile sizes (never on desktop). Use a dedicated `<DashboardKpiGrid>` component. See the **Dashboard KPI Grid Pattern** in `ux-dashboard-patterns.md` for the full breakpoint table, ASCII wireframes, and anti-patterns.

### Sidebar & Navigation

- Desktop sidebar (76px dark) is `hidden lg:flex` — invisible on mobile
- L2 panel (200px white) is `hidden lg:flex` — invisible on mobile
- Mobile uses a hamburger menu + a split nav drawer (~280px)
- Content margin: `lg:ml-[76px]` (no L2) or `lg:ml-[276px]` (with L2), no margin on mobile

### List + Detail Splits

Desktop split layouts (`w-[60%]` / `w-[40%]`) must become full-screen overlays on mobile:

```tsx
// Desktop: side-by-side
<div className="hidden lg:block lg:w-[60%]">{/* list */}</div>
<div className="hidden lg:block lg:w-[40%]">{/* detail */}</div>

// Mobile: detail as full-screen overlay
<div className="fixed inset-0 z-50 bg-white lg:hidden">{/* detail */}</div>
```

---

## Touch Targets

All interactive elements MUST meet the **44x44px minimum** touch target (WCAG 2.5.8).

```tsx
// Buttons: minimum height on mobile
<Button className="min-h-[44px] md:min-h-0">

// Icon buttons: padding ensures touch area
<button className="p-3 md:p-2" aria-label="Close">
  <X className="w-4 h-4" />
</button>

// List items / clickable rows
<div className="py-3 md:py-2 cursor-pointer">
```

### Size Reference

| Element | Mobile | Desktop | Class |
|---------|--------|---------|-------|
| Buttons | `min-h-[44px]` | `min-h-0` | `min-h-[44px] md:min-h-0` |
| Icon-only buttons | `p-3` | `p-2` | `p-3 md:p-2` |
| Clickable list rows | `py-3` | `py-2` | `py-3 md:py-2` |
| Breadcrumb segments | `min-h-11` (44px) | auto | `min-h-11 px-1` |
| Filter buttons | `min-h-10` (40px) | auto | `min-h-10` |
| BottomSheet list items | `min-h-12` (48px) | N/A | `min-h-12` |
| Links in body text | sufficient `leading-6` | same | `leading-6` |

---

## Typography

- Body text minimum `text-sm` (14px) — never smaller on mobile
- Touch labels minimum `text-xs` (12px)
- `text-[10px]` and below: only for non-interactive labels/metadata
- Headings scale down on mobile:

```tsx
<h1 className="text-lg md:text-xl font-bold text-gray-900">
<h2 className="text-base md:text-lg font-semibold text-gray-900">
```

### iOS Zoom Prevention

Inputs and selects must use `text-base` (16px) on mobile to prevent iOS auto-zoom:

```tsx
<Input className="text-base lg:text-sm" />
<Select className="text-base lg:text-sm" />
```

---

## Spacing

- Card padding: `p-3` or `p-4` (already responsive-safe)
- Page padding: `px-4 md:px-6 lg:px-8`
- Section spacing: `space-y-4 md:space-y-6`
- FAB content overlap: add `pb-20 lg:pb-4` to main content area so the FAB never overlaps the last card
- Reduce `gap-*` values on mobile only if content overflows

---

## Navigation

### Mobile Navigation Components

These are the standard mobile-nav patterns; name the components to your project's convention.

| Pattern | Purpose | Trigger |
|---------|---------|---------|
| Split nav drawer | L1 + L2 split navigation | Hamburger menu (top bar) |
| Horizontal L2 chips | Horizontal sub-section feature chips | Fixed below the top bar when inside a section |
| Full-screen search overlay | Full-screen search with scope chips | Search icon (top bar) |
| Bottom tab bar | 5-item contextual tab bar | Always visible on mobile |
| Floating action button (FAB) | A persistent quick-action button (e.g. an AI assistant or quick-create action) | Mobile only (`md:hidden`) |
| Profile bottom sheet | Profile menu | Avatar tap (top bar) |

### TopBar Mobile Adaptations

- Hamburger button: `lg:hidden`, toggles to X icon when drawer open
- Search bar: `hidden md:flex` (replaced by search icon on mobile)
- Persona switcher: `hidden md:flex`
- Product title: `hidden sm:block`
- Right icons: `ml-auto` for correct spacing

---

## BottomSheet Pattern

**On mobile (`< lg:` breakpoint), ALL overlay menus, dropdown menus, filter pickers, sort menus, and select options MUST open in a `BottomSheet` instead of a dropdown/popover.**

| Desktop Component | Mobile Replacement |
|---|---|
| `DropdownMenu` (Radix) | `BottomSheet` with tappable rows (48px touch targets) |
| `Select` dropdown | `BottomSheet` with option list + check icon |
| Filter popover | `BottomSheet` |
| Sort dropdown | `BottomSheet` with sort options + check icon |
| Overflow menu (kebab) | `BottomSheet` with action list |

### Why

- Touch targets: BottomSheet rows are `min-h-12` (48px) — dropdown items are often too small
- Thumb reachability: BottomSheet slides up from bottom — in the thumb zone
- No accidental dismissal: explicit close (X, swipe-down, backdrop tap)
- Consistent with iOS/Android native patterns

### Z-Index Stacking

- Default BottomSheet: `z-index: 40`
- Child/nested filter sheets: `z-index: 50` (via `zIndex` prop)
- Ref-counted scroll lock prevents nested sheets from prematurely re-enabling body scroll

### Portal Requirement

BottomSheet is portaled to `document.body` via `createPortal`. This is required because CSS `transform` on ANY ancestor (including identity `matrix(1,0,0,1,0,0)` from animations like `animate-fadeInUp`) creates a new containing block, breaking `fixed` positioning.

---

## Filter Pattern

Filters are shown **inline/upfront** on mobile (same layout as desktop). The key difference is that individual filter controls open **BottomSheets instead of dropdowns** on mobile.

### How It Works

- `FilterSelect`, `FilterMultiSelect`, and `FilterDateRange` each detect `useIsMobile()` internally
- On mobile: tapping the trigger opens a BottomSheet
- On desktop: standard dropdown/popover
- `FilterBar` is identical on mobile and desktop — no "Filters" CTA, no collapsing
- `activeFilterCount` prop is deprecated (no-op)

### FilterBar Scroll

On mobile, FilterBar uses horizontal scroll to prevent orphan filter wrapping:

```tsx
<div className="overflow-x-auto scrollbar-hide lg:flex-wrap lg:overflow-visible">
```

---

## Swipe-to-Dismiss

Both `BottomSheet` and `Modal` (mobile bottom-sheet variant) support drag-to-dismiss via the handle pill.

### Implementation Details

- Uses refs (`dragStartY`, `isDragging`) for performance — no state re-renders during drag
- `translateY` transform for visual feedback
- 80px threshold for dismissal
- Backdrop opacity reduction during drag
- Always null-check `e.touches[0]` / `e.changedTouches[0]` for TypeScript safety

```tsx
// Pattern (simplified)
const handleTouchStart = (e: React.TouchEvent) => {
  const touch = e.touches[0];
  if (!touch) return;
  dragStartY.current = touch.clientY;
  isDragging.current = true;
};

const handleTouchEnd = (e: React.TouchEvent) => {
  const touch = e.changedTouches[0];
  if (!touch || !isDragging.current) return;
  const delta = touch.clientY - dragStartY.current;
  if (delta > 80) onClose();
  isDragging.current = false;
};
```

---

## Tab Scroll Indicators

Fade gradient overlays on `TabsList` edges when content is scrollable. Mobile only (`lg:hidden`).

- Pattern: `from-white to-transparent`, 32px wide
- Track scroll position via `onScroll` + `MutationObserver` for async children
- Left gradient shows when scrolled past start
- Right gradient shows when not scrolled to end

---

## Mobile Card Simplification

Use `useIsMobile()` conditional rendering within the same component (no separate `MobileXCard`). Show only essential triage info on mobile, full detail on desktop.

### Pattern

```
Mobile: severity + time -> title -> impact + status (3 rows)
Desktop: full detail with all metadata
```

### Example (status / list cards)

**Mobile shows**: status badge, time, title, key metric, category
**Mobile hides**: secondary IDs, type badge, timers, related-entity chains, nested lists, secondary impact fields

---

## Forms

```tsx
// Inputs: full width on mobile
<Input className="w-full md:w-80" />

// Form layout: stack on mobile, inline on desktop
<div className="flex flex-col md:flex-row gap-3">
  <Input className="flex-1" />
  <Button>Submit</Button>
</div>

// Filter bars: wrap on mobile
<div className="flex flex-wrap gap-2">
  <Select className="w-full sm:w-auto" />
  <Select className="w-full sm:w-auto" />
</div>
```

---

## Tables

Tables must be scrollable on small screens — never let them overflow the viewport.

```tsx
// Wrap all tables in a horizontal scroll container
<div className="overflow-x-auto -mx-3 px-3">
  <table className="min-w-[600px] w-full">
    {/* ... */}
  </table>
</div>
```

For data-heavy tables, consider switching to a card layout on mobile:

```tsx
// Table on desktop, cards on mobile
<div className="hidden md:block">
  <table>{/* desktop table */}</table>
</div>
<div className="md:hidden space-y-3">
  {items.map(item => <MobileCard key={item.id} {...item} />)}
</div>
```

---

## Charts

```tsx
// Responsive container with min height
<ResponsiveContainer width="100%" height={200} minWidth={300}>
  <LineChart data={data}>
    <XAxis tick={{ fontSize: 10 }} interval="preserveStartEnd" />
    <YAxis hide={isMobile} />
  </LineChart>
</ResponsiveContainer>
```

- Use `ResponsiveContainer` for all charts
- Reduce legend items on mobile or move legend below chart
- Use `interval="preserveStartEnd"` on X-axis to avoid label overlap
- Hide Y-axis on mobile if space is tight

---

## Modals & Panels

```tsx
// Modal: bottom sheet on mobile, centered dialog on desktop
// The Modal component handles this automatically via useIsMobile()

// Detail panels: full width on mobile, slide-over on desktop
<DetailPanel className="w-full lg:w-[480px]">
```

- Modal renders as bottom sheet on mobile with handle pill and swipe-to-dismiss
- Full-screen overlay on mobile (`inset-0`), centered on `sm+`
- Detail panels become full-screen overlays on mobile

---

## Images & Media

```tsx
// Always constrain images
<img className="w-full h-auto max-w-full" />

// Prevent layout shift with aspect ratio
<div className="aspect-video w-full">
  <img className="w-full h-full object-cover rounded-lg" />
</div>
```

---

## Overflow & Truncation

```tsx
// Truncate long text on mobile
<span className="truncate max-w-[200px] md:max-w-none">
  {longText}
</span>

// Multi-line clamp
<p className="line-clamp-2 md:line-clamp-none">
  {description}
</p>
```

**Never let content overflow horizontally.** Use `overflow-hidden`, `truncate`, or `overflow-x-auto` to prevent horizontal scroll on the page body.

---

## Breadcrumbs

**Breadcrumbs MUST NOT render on mobile** (`< lg:` breakpoint). Use `hidden lg:flex` on breadcrumb containers.

On mobile, the bottom tab bar and page titles provide sufficient wayfinding. A lightweight mobile breadcrumb (if present) can provide context via the horizontal L2 chips.

`PageHeader` breadcrumbs are automatically `hidden lg:flex`.

---

## Capacitor Native App

The project uses **Capacitor** to wrap the web app as native iOS/Android apps.

### Platform Detection

```typescript
import { Capacitor } from '@capacitor/core';

if (Capacitor.isNativePlatform()) { /* iOS or Android */ }
if (Capacitor.getPlatform() === 'ios') { /* iOS only */ }
if (Capacitor.getPlatform() === 'android') { /* Android only */ }
if (Capacitor.getPlatform() === 'web') { /* Browser */ }
```

### Plugin Usage

Always guard plugin calls — they throw on web:

```typescript
import { StatusBar, Style } from '@capacitor/status-bar';

if (Capacitor.isNativePlatform()) {
  await StatusBar.setStyle({ style: Style.Dark });
}
```

### Common Plugins

| Plugin | Package | Purpose |
|--------|---------|---------|
| App | `@capacitor/app` | App lifecycle, back button handling |
| Status Bar | `@capacitor/status-bar` | Status bar style and color |
| Splash Screen | `@capacitor/splash-screen` | Launch screen control |

### Android Back Button

```typescript
import { App as CapApp } from '@capacitor/app';

if (Capacitor.getPlatform() === 'android') {
  CapApp.addListener('backButton', ({ canGoBack }) => {
    if (canGoBack) window.history.back();
    else CapApp.exitApp();
  });
}
```

### Build Commands

```bash
npm run cap:sync          # Build web + copy to native projects
npm run cap:open:ios      # Open Xcode project
npm run cap:open:android  # Open Android Studio project
```

---

## Safe Areas (iOS)

iOS devices with notches/Dynamic Island require safe area handling. Already configured:

- `index.html` has `viewport-fit=cover` in viewport meta tag
- Your global stylesheet defines safe-area utilities: `pt-safe`, `pb-safe`, `mb-safe`
- App shell components already use these

For new full-screen or edge-to-edge UI:

```css
padding-top: env(safe-area-inset-top, 0px);
padding-bottom: env(safe-area-inset-bottom, 0px);
```

Or use utility classes: `pt-safe`, `pb-safe`, `mb-safe`.

---

## Testing Responsive Behavior

When building or modifying UI:

1. Verify at **375px** (iPhone SE) — smallest supported width
2. Verify at **768px** (iPad) — tablet breakpoint
3. Verify at **1024px** (laptop) — desktop breakpoint
4. Check for **horizontal overflow** at each breakpoint
5. Verify **touch targets** meet 44px minimum on mobile
6. Test **BottomSheet** opens instead of dropdowns on mobile
7. Test **swipe-to-dismiss** on BottomSheet and Modal
8. Verify **breadcrumbs** are hidden on mobile

---

## Anti-Patterns

| Don't | Do Instead |
|-------|------------|
| Fixed pixel widths (`w-[800px]`) | Responsive widths (`w-full lg:w-[800px]`) |
| Desktop-only grid (`grid-cols-4`) | Mobile-first grid (`grid-cols-1 lg:grid-cols-4`) |
| Unscrollable wide tables | `overflow-x-auto` wrapper |
| Tiny touch targets (`p-1` on buttons) | `min-h-[44px]` or `p-3` on mobile |
| `hidden` without responsive prefix | `hidden md:block` (intentional hiding) |
| Hover-only interactions | Hover + tap/click alternatives |
| Fixed-position elements covering content | Sticky or relative positioning, `pb-20` for FAB |
| `text-xs` for body text | `text-sm` minimum for readable content |
| Dropdown menus on mobile | BottomSheet with 48px touch targets |
| Separate `MobileXCard` components | `useIsMobile()` conditional rendering in same component |
| Inline breadcrumbs on mobile | `hidden lg:flex` — use horizontal L2 chips for context |
| `style={{ fontSize: 10 }}` on interactive elements | `text-xs` minimum for tappable text |

---

## Grid Fix Pattern Reference

When making non-responsive grids mobile-friendly:

| Original | Responsive Fix |
|----------|---------------|
| `grid-cols-2` | `grid-cols-1 sm:grid-cols-2` |
| `grid-cols-3` | `grid-cols-1 sm:grid-cols-2 lg:grid-cols-3` |
| `grid-cols-4` | `grid-cols-2 sm:grid-cols-4` |
| `grid-cols-5` | `grid-cols-2 sm:grid-cols-3 lg:grid-cols-5` |
| `grid-cols-7` | `grid-cols-3 sm:grid-cols-4 lg:grid-cols-7` |
| `w-[N%]` split | `hidden lg:block lg:w-[N%]` + `fixed inset-0 z-50 bg-white lg:relative...` |
| `w-[Npx]` fixed | `w-full max-w-[Npx]` |

---

## Key Files

Keep a small index of the components/hooks that own these mobile patterns in your codebase, e.g.:

| File | Purpose |
|------|---------|
| `@/hooks/useMediaQuery` | `useMediaQuery`, `breakpoints`, `useBreakpoint`, `useIsMobile` hooks |
| `@/components/ui/BottomSheet` | Reusable bottom sheet primitive |
| `@/components/ui/Modal` | Dialog — bottom sheet on mobile, centered on desktop |
| `@/components/ui/FilterBar` | FilterBar + FilterSelect/MultiSelect/DateRange (auto BottomSheet on mobile) |
| `@/components/ui/Tabs` | TabsList with scroll fade indicators |
| `capacitor.config.ts` | Capacitor native app config (if using Capacitor) |
