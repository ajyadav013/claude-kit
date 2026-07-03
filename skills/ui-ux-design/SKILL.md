---
name: ui-ux-design
description: Verify and enforce UI/UX design system compliance before and during implementation. Ensures every component follows the project's visual language.
argument-hint: [component or page name]
disable-model-invocation: true
---

Verify UI/UX design compliance for $ARGUMENTS.

## Steps

1. **Read the design system**: Read `.claude/rules/ui-design-system.md` (foundations & index — colors, typography, spacing, icons, tokens) and its companions `.claude/rules/ui-components.md` (cards, badges, buttons, form controls, states, compound components) and `.claude/rules/ui-layout-and-motion.md` (page layout, motion, accessibility, page blueprints). (Installed as overlay rules when the React stack is selected.) These files are **authoritative**: if the quick-check table below ever conflicts with them, follow the rule files.

2. **Read the UX patterns docs**: Read `.claude/rules/ux-patterns.md` for status expression rules, empty state guidelines, breadcrumb conventions, page blueprint selection, and data color rules, and `.claude/rules/ux-dashboard-patterns.md` for chart standards, tab-bar limits, KPI-grid layouts, and the global filter strip. For responsive/native specifics, also read `.claude/rules/mobile-design-guidelines.md`.

3. **Identify the page archetype**: Determine if the target is a **List**, **Dashboard**, **Detail**, or **Config** page. Each archetype has specific compound components and hooks it should use.

4. **Audit the target**: Read the component/page file(s) for `$ARGUMENTS`. Check against these rules:

   ### Visual Rules
   | Rule | Correct | Incorrect |
   |------|---------|-----------|
   | Border radius | `rounded-lg` | `rounded-xl`, `rounded-2xl` |
   | Card padding | `p-3` or `p-4` | `p-5`, `p-6`, `p-7`, `p-8` |
   | Card structure | `bg-white rounded-lg border border-gray-200 p-3` | Any other card pattern |
   | Card titles | `text-sm font-semibold` | `text-lg`, `text-xl` |
   | Card hover | `hover:border-primary/30 hover:shadow-md transition-all duration-200` | Custom hover |
   | Grid gaps | `gap-3` | `gap-1`, `gap-2`, `gap-4`+ |
   | Headings | `font-bold text-gray-900` | Other heading styles |
   | Body text | `text-gray-700` | `text-gray-800`, `text-black` |
   | Muted text | `text-gray-500` | `text-gray-300`, `text-gray-400` |

   ### Icon Sizing
   | Context | Size |
   |---------|------|
   | Metadata | `w-3 h-3` |
   | Body content | `w-4 h-4` |
   | Stats/headers | `w-5 h-5` |

   ### Page Headers
   - Title + CTA only
   - No icons in headers
   - No subtitles

   ### Component Usage
   - All interactive elements use Radix UI primitives
   - All UI components imported from `@/components/ui` barrel
   - No raw `<select>`, `<input>`, `<button>` elements
   - Compound components used where they exist

   ### Accessibility
   - Icon-only buttons have `aria-label`
   - Interactive elements have `focus-visible:ring-*`
   - Color is never the only indicator of state (must pair with text/icon)

5. **Report findings**: Output a table grouped by severity:

   | File | Line | Issue | Rule | Suggested Fix |
   |------|------|-------|------|---------------|

   Severity levels: **Critical** (breaks design system), **Warning** (inconsistency), **Info** (improvement opportunity).

6. **Recommend fixes**: List the top 3 highest-impact fixes to make first.

## References

- Design system: `.claude/rules/ui-design-system.md` (foundations), `.claude/rules/ui-components.md`, `.claude/rules/ui-layout-and-motion.md`
- UX patterns: `.claude/rules/ux-patterns.md`, `.claude/rules/ux-dashboard-patterns.md`
- Mobile / responsive: `.claude/rules/mobile-design-guidelines.md`
- Sidebar navigation: `docs/references/ui/sidebar-navigation.md` (project-specific, if present)
- UI components: `src/components/ui/index.ts`
- Existing pages: `src/pages/` (look at similar archetype)

**Scope boundary.** This skill verifies *one* screen/feature against the design system *during
implementation*. For the **system-wide, over-time** operations layer — token architecture, drift
detection, system health & maturity, governance, adoption, and AI-readiness of the design system
itself — use `design-system-ops`.
