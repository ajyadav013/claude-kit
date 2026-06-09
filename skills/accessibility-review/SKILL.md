---
name: accessibility-review
description: Use when reviewing or building UI to check accessibility (WCAG) — keyboard operability, focus management, semantics/ARIA, color contrast, touch-target size, motion, and screen-reader labels. Produces prioritized findings with concrete fixes. Distinct from performance/visual review.
---

# Accessibility Review

Review a UI change (or a whole view) for accessibility and return prioritized, concrete fixes mapped to
WCAG. Design-and-review companion to `frontend-ui-engineering` and `ui-ux-design`.

**Risk tier:** low–medium (raise to high if it gates a legally-required compliance surface — see
`.claude/rules/risk-classification.md`).

## When to use
- Reviewing any frontend/UI change, or auditing an existing view before release.
- The `responsive-and-accessibility.md` rule sets the standards; this skill is the review procedure.

## Who should use it
Frontend engineers, the `ui-designer` agent, QA. Designers/PMs can run it for a first pass.

## Required inputs
The component/view (file paths or a running URL) and which states matter (loading, empty, error, modal).

## Ordered questions to ask
1. Is everything **operable by keyboard** (tab order, visible focus, no traps, Esc closes overlays)?
2. Is the **semantics** right (native elements over `div` soup, headings in order, landmarks, labels
   for every control, `alt` for images)?
3. Do interactive states expose **name/role/value** to assistive tech (ARIA only where native won't do)?
4. Does **color contrast** meet WCAG AA (text ≥ 4.5:1, large text/UI ≥ 3:1) and is color not the only
   signal?
5. Are **touch targets** ≥ 44×44px and is motion reduced under `prefers-reduced-motion`?
6. Are **dynamic updates** announced (live regions) and **forms** clear (labels, errors tied to inputs)?

## Agents to delegate to
`ui-designer` for design-spec gaps; `sdlc-code-reviewer` to land fixes. Reference
`.claude/skills/_references/accessibility-checklist.md` if present.

## Quality gates
No keyboard trap; every control has an accessible name; AA contrast on text/UI; focus visible and
managed across route/modal changes; target sizes met.

## Expected outputs
Prioritized findings (P0 blocks release → P3 polish), each with the element, the WCAG criterion, and the
exact fix.

## Stop conditions
Stop and flag if a fix requires a design change (hand to `ui-designer`) or if a compliance obligation
makes a P0 a release blocker that needs human sign-off.

## Example
```
/accessibility-review the invite-teammate modal
→ P0: focus not trapped in modal + Esc doesn't close → add focus trap + Esc handler (WCAG 2.1.2/2.4.3)
→ P1: "✕" close button has no accessible name → aria-label="Close" (4.1.2)
→ P2: error text only red → add icon/text prefix (1.4.1); contrast 3.9:1 → darken to ≥4.5:1 (1.4.3)
```
