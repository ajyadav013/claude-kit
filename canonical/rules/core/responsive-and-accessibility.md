# Responsive & Accessibility

All new and modified UI components MUST be responsive and usable on mobile devices (375px+), tablets (768px+), and desktop (1024px+), and MUST meet accessibility standards.

## Breakpoint Strategy

Use mobile-first responsive design:

| Breakpoint | Min Width | Target |
|------------|-----------|--------|
| Base | 0px | Mobile (default) |
| Small | 640px | Large phones / small tablets |
| Medium | 768px | Tablets |
| Large | 1024px | Desktop |
| XLarge | 1280px | Large desktop |

**Write mobile styles first, then layer on desktop overrides.**

```
// GOOD — mobile-first
<element> base: single-column, medium: 2-column, large: 4-column

// BAD — desktop-first (breaks on mobile)
<element> base: 4-column (will overflow on mobile)
```

## Layout Rules

### Grids & Flex Layouts

- Start with single-column layouts on mobile
- Add columns at larger breakpoints
- Stack content vertically on mobile, side-by-side on desktop
- Ensure proper gap/spacing between elements at all sizes

```
// Metric cards example: 1 col mobile → 2 col tablet → 4 col desktop
<grid> base: 1-column, small: 2-column, large: 4-column

// Content + sidebar: stack on mobile, side-by-side on desktop
<container> base: vertical-stack, large: horizontal-layout
  <main-content> flex: 1
  <sidebar> base: full-width, large: fixed-width
```

### Tables

Tables must be scrollable on small screens — never let them overflow the viewport.

```
// Wrap all tables in a horizontal scroll container
<scroll-container> horizontal-overflow: auto
  <table> minimum-width: reasonable-for-content
```

For data-heavy tables, consider switching to a card layout on mobile:

```
// Table on desktop, cards on mobile
<table-view> display: hidden on mobile, visible on medium+
<card-list> display: visible on mobile, hidden on medium+
  {items.map(item => <mobile-card>)}
```

### Sidebar & Navigation

- Sidebar collapses to a hamburger menu on mobile (large breakpoint)
- Navigation items stack vertically on mobile
- Avoid horizontal nav bars with more than 4 items on mobile — use a dropdown or drawer
- Bottom navigation bars are an acceptable mobile pattern for primary navigation

### Modals & Panels

- Full-screen on mobile, centered dialog on desktop
- Detail panels: full width on mobile, slide-over on desktop
- Ensure close buttons are accessible on all screen sizes

```
// Modal: full-screen mobile, centered desktop
<modal> base: fixed-inset, medium: centered-with-max-width

// Detail panel: full width mobile, fixed width desktop
<panel> base: full-width, large: fixed-width-sidebar
```

## Typography

- Body text minimum 14px — never smaller on mobile
- Touch labels minimum 12px
- Headings scale down on mobile for better readability
- Ensure adequate line-height for readability (1.5 or more for body text)

```
// Heading sizes scale down on mobile
<h1> base: 18px, medium: 24px
<h2> base: 16px, medium: 20px
```

## Touch Targets

All interactive elements MUST meet the 44x44px minimum touch target (WCAG 2.5.5 Level AAA; 24x24px is Level A minimum).

**Rules:**
- Buttons: minimum 44px height/width on mobile
- Icon-only buttons: ensure 44px tap area with padding
- Clickable list rows: minimum 44px height
- Links in body text: sufficient line-height and padding

```
// Button with minimum touch target
<button> base: min-height-44px, medium: min-height-auto

// Icon button with padding for touch area
<icon-button> base: padding-12px, medium: padding-8px
  <icon> size: 16px

// Clickable list item
<list-item> base: padding-y-12px, medium: padding-y-8px
```

### Invisible Tap Area Extension

For small visual elements that need larger tap zones, use invisible overlays:

```
// Small visual element with extended tap area
<clickable-container> position: relative
  <visual-element> size: small
  <tap-area-overlay> position: absolute, inset: -12px
```

## Spacing

- Use consistent spacing units (e.g., 12px, 16px multiples)
- Page padding: increase on larger screens (16px mobile → 24px tablet → 32px desktop)
- Section spacing: adequate vertical rhythm
- Reduce spacing on mobile only if content overflows
- Maintain consistent card/component padding across breakpoints

## Images & Media

```
// Always constrain images to container
<img> width: 100%, height: auto, max-width: 100%

// Prevent layout shift with aspect ratio
<image-container> aspect-ratio: desired-ratio
  <img> width: 100%, height: 100%, object-fit: cover
```

- Use responsive image techniques (srcset, picture element)
- Ensure alt text is meaningful for screen readers
- Constrain video and iframe embeds to container width

## Overflow & Truncation

```
// Truncate long text on mobile
<text> base: truncate-with-max-width, medium: no-truncation

// Multi-line clamp
<paragraph> base: line-clamp-2, medium: no-clamp
```

**Never let content overflow horizontally.** Use overflow controls, truncation, or scrolling to prevent horizontal page scroll.

## Forms

- Inputs: full width on mobile, constrained on desktop
- Form layout: stack on mobile, inline on desktop
- Filter bars: wrap on mobile, maintain single row on desktop
- Ensure form labels are associated with inputs for screen readers
- Use appropriate input types (email, tel, number) for mobile keyboards

```
// Input sizing
<input> base: full-width, medium: fixed-width

// Form layout: stack mobile, inline desktop
<form-row> base: vertical-stack, medium: horizontal-layout
  <input> flex: 1
  <button> Submit

// Filter bar with wrapping
<filter-bar> display: flex, wrap: wrap
  <filter-item> base: full-width, small: auto-width
```

## Charts & Data Visualizations

- Use responsive containers with minimum dimensions
- Reduce legend items on mobile or reposition legend
- Simplify axes on small screens
- Consider alternative representations for complex charts on mobile
- Ensure color is not the only differentiator (use patterns, labels)

```
// Responsive chart container
<chart-container> width: 100%, height: responsive, min-width: reasonable
  <chart>
    // Simplify on mobile
    <y-axis> display: hidden on mobile, visible on medium+
    <x-axis> font-size: small, interval: preserve-start-end
```

## Testing Responsive Behavior

When building or modifying UI:

1. **Verify at 375px** (iPhone SE) — smallest supported width
2. **Verify at 768px** (iPad) — tablet breakpoint
3. **Verify at 1024px** (laptop) — desktop breakpoint
4. **Check for horizontal overflow** at each breakpoint
5. **Verify touch targets** meet 44px minimum on mobile
6. **Test with actual touch devices** when possible
7. **Test with screen readers** for accessibility
8. **Check keyboard navigation** for all interactive elements

## Touch-Aware Interactions

Consider using a **two-layer detection system** for optimal UX:

| Layer | Detects | Drives |
|-------|---------|--------|
| **Layout** | Screen width | Cards vs tables, sidebar visibility, stacking |
| **Interaction** | Touch capability | Tooltips, touch targets, hover reveals |

Large tablets (e.g., iPad Pro 13" at 1024px+) may get the **desktop layout** but need **touch interactions** — tooltips tap-to-show, hover-reveal content always visible, 44px tap zones.

### Touch Detection

Detect touch capability using CSS media queries or JavaScript:
- CSS: `@media (pointer: coarse)` targets touch devices
- CSS: `@media (hover: none)` targets devices without hover capability
- JS: `navigator.maxTouchPoints > 0` or touch event support

Use touch detection for:
- Tooltip behavior (hover vs tap-to-show)
- Hover-reveal content visibility
- Touch target sizing
- Interaction feedback patterns

### Tooltip Behavior

- **Mouse devices**: hover to show
- **Touch devices**: tap to show, tap outside to dismiss
- Never use hover-only tooltips without touch alternatives
- Consider always-visible labels on touch devices

### Hover-Reveal Content

Never rely on hover alone. Provide touch alternatives:

```
// Hover-reveal with touch alternative
<content> base-opacity: 0, parent-hover: opacity-100, touch-device: opacity-100
```

Strategies:
- Make content always visible on touch devices
- Provide tap-to-toggle behavior
- Use explicit "show more" buttons on touch

## Accessibility Requirements (WCAG 2.1 Level AA)

### Keyboard Navigation
- All interactive elements must be keyboard-accessible (Tab + Enter/Space)
- Focus indicators must be visible and clear
- Focus order must be logical and match visual layout
- Skip links for keyboard users to bypass repeated content
- Modal dialogs must trap focus and return focus on close

### Screen Readers
- Every image must have meaningful alt text (or alt="" for decorative)
- Every icon-only button must have aria-label describing the action
- Every form input must have an associated label (visible or aria-label)
- Dynamic content updates must use aria-live regions
- Landmarks (header, nav, main, aside, footer) for page structure
- Headings must form a logical hierarchy (h1 → h2 → h3, no skipping)

### Color & Contrast
- WCAG AA contrast minimum:
  - Normal text (< 18pt): 4.5:1
  - Large text (≥ 18pt or bold ≥ 14pt): 3:1
  - UI components and graphical objects: 3:1
- Color must never be the only indicator — pair with text, icon, or pattern
- Links must be distinguishable from surrounding text (underline, weight, or color + another differentiator)

### Focus Management
- Custom interactive elements must have:
  - Appropriate role attribute
  - tabIndex={0} for keyboard access
  - onKeyDown handler for Enter/Space
  - aria-label for screen readers
- Focus must be visible (never `outline: none` without alternative)
- Focus must move logically through the interface

### Form Accessibility
- Every input has an associated label (for attribute or aria-labelledby)
- Error messages are announced to screen readers (aria-describedby, aria-invalid)
- Required fields are indicated (required attribute + visual indicator)
- Field constraints are communicated (aria-describedby for hints)
- Form validation provides clear, actionable feedback

### Motion & Animation
- Respect prefers-reduced-motion for users with motion sensitivity
- Animations must not be essential to understanding content
- Provide alternatives to auto-playing content
- Parallax and scroll-triggered animations should be subtle or toggleable

## Anti-Patterns

| Don't | Do Instead |
|-------|------------|
| Fixed pixel widths without responsive overrides | Responsive widths (base: full, large: fixed) |
| Desktop-only multi-column layouts | Mobile-first (base: 1-col, large: multi-col) |
| Unscrollable wide tables | Horizontal scroll wrapper or card layout |
| Tiny touch targets (< 44px) | Minimum 44px touch area on mobile |
| Hidden content without breakpoint control | Intentional responsive hiding with breakpoints |
| Hover-only interactions | Hover + touch alternative |
| Hover-only tooltips | Tap-to-show on touch, hover on mouse |
| Fixed-position elements that cover content | Sticky or relative positioning |
| Tiny text (< 14px for body) | Minimum 14px for readable content |
| Color-only status indicators | Color + icon or text label |
| Keyboard-inaccessible custom controls | Proper role, tabIndex, keyboard handlers |
| Images without alt text | Meaningful alt for content, alt="" for decorative |
| Missing form labels | Associated labels for all inputs |
| Low-contrast text | WCAG AA minimum (4.5:1 for normal text) |

## Framework-Specific Notes

When implementing responsive and accessible UI:

**CSS frameworks (Tailwind, Bootstrap, etc.):**
- Use the framework's responsive prefix system consistently
- Follow mobile-first methodology
- Leverage built-in accessibility utilities where available

**Component libraries (Radix, Headless UI, Material UI, etc.):**
- Prefer accessible component libraries with built-in ARIA support
- Verify keyboard navigation and screen reader announcements
- Customize touch targets for mobile where needed

**JavaScript frameworks (React, Vue, Angular, Svelte, etc.):**
- Use semantic HTML elements where possible
- Manage focus programmatically for dynamic content
- Test with assistive technologies specific to your framework

**Testing:**
- Use the project's E2E framework at multiple viewport sizes
- Test keyboard navigation in automated tests where possible
- Manual testing with screen readers (VoiceOver, NVDA, JAWS)
- Use browser DevTools accessibility audits (Lighthouse, axe)
