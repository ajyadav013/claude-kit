---
name: review-ux-flow
description: Use to review a user journey for UX problems by reading the implementing code statically (no running app) — dead ends, missing empty/error/loading/timeout states, unclear copy, and confusing navigation, rated by user impact. A product-lens read-only review, distinct from an accessibility audit or a live UI test.
---

# Review UX Flow (product lens, static)

A read-only walk of a user journey *through the code that implements it* — without running the app —
to find where the experience breaks down for the user. This is a product/UX lens: it complements the
accessibility audit (`accessibility-review`), the design-system check
(`ui-ux-design` / `design-system-compliance.md`), and live UI testing (`manual-test`, the `tester`
lane) — it overlaps none of them.

**Risk tier:** low — read-only review, no changes. See `.claude/rules/risk-classification.md`.

## When to use
A flow is built (or specced in code) and you want a product-side UX pass before it ships — especially
to catch the non-happy-path states that automated tests and design reviews miss.

## Required inputs
The flow to review (name or entry point) and the code that implements it (components, routes, state).

## What to check — walk the journey state by state
1. **Dead ends.** Every screen has a way forward and a way back; no state strands the user with no
   action.
2. **Missing states.** For each step, are **empty, loading, error, timeout, and partial** states
   actually rendered — or only the success path? Each missing state is a finding tied to what the user
   sees instead.
3. **Unclear copy.** Labels, buttons, and messages say what will happen in the user's terms; flag
   jargon, internal names, and ambiguous CTAs.
4. **Navigation problems.** The path between steps is discoverable and predictable; flag hidden
   transitions, surprising redirects, and lost context on back/refresh.
5. **Recovery.** When something fails, can the user understand it and retry/recover?

Rate each finding by **user impact** (how many users hit it, how badly), mapped to the project's
severity model.

## Quality gates
Every finding cites the component/route/line where the state is (or isn't) handled; must-fix vs
nice-to-have separated; no vague feedback; nothing edited.

## Expected output
A verdict, separated **Issues to Fix** / **Improvements**, and a **state-coverage table** per step
(empty / loading / error / timeout / success — handled?). Severities **Critical / High / Medium /
Low / Cosmetic** (`.claude/rules/quality-gates.md`).

## Stop conditions
Stop and route elsewhere if the request is really an accessibility audit (`/accessibility-review`), a
visual/design-system review (`/ui-ux-design`), or a live behavioral test (the `tester` lane) — this
skill is the static product-UX lens only. Escalate ambiguous product intent via
`.claude/rules/human-in-the-loop.md`.

## Example
```
/review-ux-flow the checkout flow
→ reads the route/components/state, walks each step
→ flags a dead-end on payment failure, missing empty-cart state, ambiguous "Continue" copy
→ verdict + Issues to Fix / Improvements + per-step state-coverage table
```
