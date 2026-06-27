# design-system-ops

Operate and maintain a design system as a living product — the work *after* components are built.
Design systems drift: tokens go stale, components fall out of spec, teams fork patterns, and the gap
between intent and implementation compounds silently. This skill is the **operations layer** — auditing,
governing, documenting, validating, and measuring the system the way a staff-level practitioner would,
with explicit frameworks that produce findings and decisions rather than generic advice. Stack-agnostic
(React, Vue, Twig, Tailwind, SCSS, CSS custom properties, Style Dictionary, CSS-in-JS).

> **Boundary.** This is the **system-wide, over-time** operations layer. It does NOT build or style
> components (`component-design`, `radix-tailwind-component-patterns`), set up the frontend app
> (`frontend-ui-engineering`, `frontend-repo-architecture`), check a screen against the design system
> during implementation (`ui-ux-design`), or run a WCAG pass on one UI (`accessibility-review`). Reach
> here for the **health, drift, token architecture, governance, adoption, or maturity of the design
> system itself**.

## What's inside

| File | Covers |
|------|--------|
| `SKILL.md` | The operations lifecycle (audit → govern → document → validate → communicate) and a summary of each framework, with sibling boundaries and output discipline. |
| `references/token-architecture.md` | The three-tier token model (primitive → semantic → component), strictly-downward reference rules, naming conventions, DTCG 2025.10 alignment, and cross-platform handling. |
| `references/system-health-and-maturity.md` | The seven health dimensions, library-type classification (design system / component / pattern library / utility collection), the five maturity stages, and how to grade and calibrate. |
| `references/drift-detection.md` | The four drift kinds (visual / behavioural / API / token), the A/C/E classification, styling-specific token-drift detection, severity, and trend tracking. |
| `references/governance-and-adoption.md` | Deprecation, decision records, contribution + change communication, and the adoption model (coverage ≠ adoption, four signals, leading/lagging, per-team). |
| `references/ai-readiness.md` | The context cascade, the three pillars (coverage / context / validation), the six dimensions of component AI-readiness, and the Component Challenge Rating calibration. |

## Provenance

Frameworks re-derived stack-agnostic (not vendored) from the MIT-licensed
[`murphytrueman/design-system-ops`](https://github.com/murphytrueman/design-system-ops) (© 2026 Murphy
Trueman; designsystemops.com) — a 41-skill pack for Claude Code. This condenses its highest-leverage
*operations* frameworks (the `knowledge-notes/` on token architecture, AI-readiness, adoption
measurement, and the Component Bestiary, plus the `system-health` and `drift-detection` skills) into a
single skill, re-expressed in this kit's idiom with attribution. DTCG references the Design Tokens
Community Group 2025.10 specification. When the upstream pack and this skill disagree, trust upstream.

## When to use

- "How healthy is my design system?" / "audit my tokens" / "where has the system drifted?"
- Inheriting a design system, running a quarterly review, or making the investment case for one.
- Giving tokens a real architecture (primitives vs semantics vs component tokens) or migrating to DTCG.
- Deprecating a token or component, or recording a consequential design-system decision.
- Diagnosing adoption — teams may be re-implementing instead of consuming the library.
- Making the system **AI-ready** so agents use it correctly instead of hallucinating its API.

## Boundary vs siblings

| Skill | Owns | Scope |
|-------|------|-------|
| **design-system-ops** (this) | Drift, token architecture, system health & maturity, governance, adoption, AI-readiness | System-wide, over time |
| **ui-ux-design** | Verifying a screen/feature against the design system during implementation | Per-feature, build-time |
| **component-design** · **radix-tailwind-component-patterns** | Building and styling components (incl. Tailwind `@theme` tokens) | Per-component, build-time |
| **accessibility-review** | WCAG review of a UI | Per-UI |
| **frontend-ui-engineering** · **frontend-repo-architecture** | Building the frontend app | App |

design-system-ops sits **above** the build-time skills: they ship one feature to spec; this one keeps
the spec — the tokens, the inventory, the contracts — healthy across teams and over time.

## Related

- **Build-time siblings:** `ui-ux-design`, `component-design`, `radix-tailwind-component-patterns`, `accessibility-review`, `frontend-ui-engineering`.
- **Decision records:** `documentation-and-adrs` — the home for the records this skill calls for.
- **Rule:** `.claude/rules/documentation.md` — the documentation standard design-system docs must meet.
- **Deep dive:** `SKILL.md` and the five `references/` files above.
