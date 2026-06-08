---
name: ui-ux-design
description: Verify and enforce UI/UX design system compliance before and during implementation. Ensures every component follows the project's visual language.
argument-hint: [component or page name]
disable-model-invocation: true
---

Verify UI/UX design compliance for $ARGUMENTS.

## Steps

1. **Read the design system**: Read `docs/references/ui/ui-design-system.md` to load the full design rules — colors, typography, spacing, cards, icons, badges, components, and accessibility.

2. **Read the UX patterns doc**: Read `docs/references/ui/ux-patterns.md` for status expression rules, empty state guidelines, breadcrumb conventions, page blueprints, and data color rules.

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

- Design system: `docs/references/ui/ui-design-system.md`
- UX patterns: `docs/references/ui/ux-patterns.md`
- Sidebar navigation: `docs/references/ui/sidebar-navigation.md`
- UI components: `src/components/ui/index.ts`
- Existing pages: `src/pages/` (look at similar archetype)
