---
name: design-system-ops
description: >-
  Operate and maintain a design system as a living product over time — the work AFTER components are
  built. Use for design-system drift detection (tokens/components decaying out of spec), three-tier
  token architecture governance (primitive → semantic → component, DTCG-aligned), system-health and
  maturity assessment (library-type classification, maturity stages, AI-readiness), adoption
  measurement (coverage ≠ adoption), and the governance lifecycle (deprecation, decision records,
  change communication). Stack-agnostic (React/Vue/Twig/Tailwind/SCSS/CSS vars/Style Dictionary). Do
  NOT use to BUILD or style components or check per-screen design compliance (use component-design /
  radix-tailwind-component-patterns / ui-ux-design / frontend-ui-engineering), nor for WCAG review of a
  single UI (use accessibility-review) — this is the system-wide, over-time operations layer above them.
---

# Design System Ops

Building a design system is the easy part; keeping it alive is the work. Used systems **drift** —
tokens go stale, components fall out of spec, teams fork patterns, and the gap between intent and
implementation compounds silently. This skill is the **operations layer**: auditing, governing,
documenting, and measuring a design system as a living product, the way a staff-level practitioner
would — with explicit frameworks that produce findings and decisions, not generic advice.

> Frameworks re-derived (stack-agnostic, not vendored) from the MIT-licensed
> [`murphytrueman/design-system-ops`](https://github.com/murphytrueman/design-system-ops)
> (© 2026 Murphy Trueman). The original is a 41-skill pack for Claude Code; this is a single
> condensed skill carrying its highest-leverage operations frameworks.

> **Sibling boundary.** This skill is the **over-time, system-wide operations** layer. It does NOT
> build or style components (that is `component-design` and `radix-tailwind-component-patterns`), set
> up the frontend app (`frontend-ui-engineering`, `frontend-repo-architecture`), check a screen
> against the design system during implementation (`ui-ux-design`), or run a WCAG pass on one UI
> (`accessibility-review`). Reach here when the question is about the **health, drift, governance,
> token architecture, adoption, or maturity of the design system itself** — not about shipping one
> feature.

## When to use

- "How healthy is my design system?" / "audit my tokens" / "where has the system drifted?"
- A design system is being inherited, reviewed quarterly, or pitched for investment.
- Tokens need a real architecture (primitives vs semantics vs component tokens) or a DTCG migration.
- A component or token must be **deprecated**, or a consequential design-system decision recorded.
- Adoption is unclear — teams may be re-implementing instead of consuming the library.
- The design system needs to become **AI-ready** (machine-readable enough that agents use it correctly).

## The operations lifecycle

Design-system ops is a repeating loop, not a one-off. Each stage routes to a framework below.

```
AUDIT      → token-audit · component-audit · drift-detection · system-health   (what is the state?)
GOVERN     → deprecation · decision records · contribution · change communication (control change)
DOCUMENT   → usage guidelines · AI-component descriptions · token docs          (make intent explicit)
VALIDATE   → design-to-code · token compliance · accessibility-per-component    (enforce the contract)
COMMUNICATE→ adoption report · stakeholder brief · onboarding                   (close the loop)
```

Always **calibrate to the system's maturity and type** (see `references/system-health-and-maturity.md`):
a pattern library is not a design system with gaps, and an ad-hoc system should not be judged for
lacking platform-grade governance. Findings are framed "appropriate / below expectations for this
stage," never against an absolute scale.

## Core frameworks

### Three-tier token architecture

Tokens are structured in tiers, each with a distinct job; references flow **strictly downward**.

- **Primitives** — raw values, the source of truth. Name by *what they are*: `color.blue.500`,
  `spacing.4`. Never `color.primary`.
- **Semantic** — encode *intent*; reference primitives. Name by function/role: `color.action.primary`,
  `color.feedback.error`. This is the tier theming swaps at. A semantic token named for appearance
  (`color.semantic.blue`) has failed.
- **Component** *(optional, only when justified)* — scope semantic intent to a component context:
  `button.background.default → color.action.primary`. Use for white-labelling, divergent components,
  or large complex components; most mature systems run on primitives + semantics alone.

The most damaging violation is a **cross-tier reference at the wrong level** —
`button.background.default: {color.blue.500}` looks fine but breaks the semantic contract, so a rebrand
or theme change never reaches it. Align to **DTCG 2025.10** (`$type`, resolvers, sets, composite-token
sub-value validation). Full model, naming rules, and cross-platform handling:
`references/token-architecture.md`.

### System health & maturity

A holistic, findings-based assessment across **seven dimensions** — tokens, components, documentation,
adoption, governance, AI-readiness, platform maturity — not a deep dive into one. First **classify the
library type** (design system / component library / pattern library / utility collection) from
codebase signals, *not* the README, then **baseline the maturity stage** (ad-hoc → managed →
systematic → measured → optimised) and grade each dimension Strong / Functional / Weak relative to that
stage. See `references/system-health-and-maturity.md`.

### Drift detection

Drift is the **normal condition** of a used system; the question is whether it is intentional,
how severe, and whether it is compounding. Detect across four kinds — **visual, behavioural, API,
token** — then **classify each instance** (intentional divergence → maybe a contribution; accidental
re-implementation → correct + fix root cause; system gap → the system is missing something). Token
drift detection is styling-specific (raw values outside `var()`, SCSS literals, Tailwind arbitrary
brackets `bg-[#ff0000]`, raw values outside a CSS-in-JS theme). See `references/drift-detection.md`.

### Adoption (coverage ≠ adoption)

Coverage = does the system provide what teams need; adoption = do teams actually use it. A system can
have 100% coverage and 20% adoption. Measure four signals — installation, component consumption, token
compliance, pattern adherence — split **leading vs lagging** indicators, and always break down
**per-team** (a healthy system-wide average hides struggling teams). See
`references/governance-and-adoption.md`.

### Governance lifecycle

Deprecation with a migration path and timeline; **decision records** for consequential token/component
choices (route to `documentation-and-adrs` for the ADR itself); contribution workflow; and change
communication sized to blast radius. The governance frameworks live in
`references/governance-and-adoption.md`.

### AI-readiness & Component Challenge Rating

An AI-ready system can be consumed and generated-from by agents without implicit knowledge. It rests on
three pillars — **coverage, context, validation** — and component descriptions that let an agent pick,
configure, and use a component correctly. Calibrate documentation/audit depth by **Component Challenge
Rating** (CR): a date picker or data table (CR 7+) needs a mandatory a11y audit + decision record + full
anti-pattern coverage; a badge (CR 1–2) needs little. See `references/ai-readiness.md`.

## Output discipline

- Produce **findings, not advice** — each finding names the artefact, the problem, a severity, and a
  recommended response; end with a prioritised action list.
- **Calibrate to maturity and library type** (above) — never project a platform-grade roadmap onto a
  utility collection.
- Distinguish **measured from estimated** — if you assessed by interview rather than inspection, say
  so and flag what needs direct verification.
- For recurring assessments, report the **trend** (improved / steady / regressed) against the prior run,
  not just the current snapshot.
- A consequential decision becomes a **decision record** (`documentation-and-adrs`), not a buried note.

## References

- `references/token-architecture.md` — the three-tier model, downward-reference rules, naming conventions, DTCG 2025.10 alignment, and cross-platform handling.
- `references/system-health-and-maturity.md` — the seven health dimensions, library-type classification, the five maturity stages, and how to grade/calibrate.
- `references/drift-detection.md` — the four drift kinds, the classification scheme, styling-specific token-drift detection, severity, and trend tracking.
- `references/governance-and-adoption.md` — deprecation, decision records, contribution + change communication, and the adoption-measurement model (four signals, leading/lagging, per-team).
- `references/ai-readiness.md` — the context cascade, the three pillars (coverage/context/validation), the six dimensions of component AI-readiness, and the Component Challenge Rating calibration.

## Provenance

Frameworks re-derived stack-agnostic from the MIT-licensed
[`murphytrueman/design-system-ops`](https://github.com/murphytrueman/design-system-ops) (© 2026 Murphy
Trueman; designsystemops.com) — its `knowledge-notes/` (token architecture, AI-readiness, adoption
measurement, the Component Bestiary reference) and the `system-health` / `drift-detection` skills.
DTCG references the Design Tokens Community Group 2025.10 specification. Nothing vendored; concepts are
re-expressed in this kit's idiom with attribution. When the upstream pack and this skill disagree,
trust upstream — it is the deeper, actively-maintained source.

## Related

- `ui-ux-design` — build-time design-system **compliance** of a screen/feature (this skill is the system-wide, over-time counterpart).
- `component-design` · `radix-tailwind-component-patterns` — **building/styling** components (incl. Tailwind `@theme` tokens); this skill governs the token *architecture* and component *inventory* above them.
- `accessibility-review` — WCAG review of a UI; design-system-ops sequences a11y work by Component Challenge Rating and tracks it per-component across the system.
- `frontend-ui-engineering` · `frontend-repo-architecture` — building the frontend app the design system serves.
- `documentation-and-adrs` — the home for the decision records this skill calls for.
- `.claude/rules/documentation.md` — the kit's documentation standard that design-system docs must meet.
