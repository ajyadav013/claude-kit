# Token architecture

The reference behind the **three-tier token architecture** framework in `design-system-ops`. Re-derived
stack-agnostic from the MIT `murphytrueman/design-system-ops` `token-architecture` knowledge note.

## The three-tier model

Design tokens are most useful structured in tiers, each serving a distinct purpose. Most systems need
at least two (primitives and semantics); a third (component tokens) is available when complexity or
branding justifies it, but is **not** assumed. Collapsing tiers — only primitives, or skipping
primitives — creates problems that compound over time.

### Tier 1 — Primitives (raw values)

The source of truth for every value. Nothing else may define a raw colour, spacing unit, or type value
that is not first declared as a primitive. Name by **what they are, not what they mean**:

- `color.blue.500` — not `color.primary`
- `spacing.4` (16px on a 4px grid) — not `spacing.medium`
- `font-size.base` — not `font-size.body`

Primitives define the available value space; every higher tier is a *selection* from it.

### Tier 2 — Semantic (intent)

Reference primitives and apply meaning. Someone reading a semantic token should understand what it
communicates without knowing its resolved value. Name by **function, context, or role**:

- `color.action.primary` — the primary interactive action colour
- `color.feedback.error` — communicates an error state
- `spacing.component.gap` — the standard gap between components

Semantics are the tier that **enables theming** — dark/light, brand variants, multi-brand all swap
here, never at the primitive or component tier. A semantic token named for appearance
(`color.semantic.blue`) is a primitive with extra steps; it has failed its purpose.

### Tier 3 — Component (optional, only when justified)

Scope semantic intent to one component context; reference semantics. Name by component/property/state:

- `button.background.default → color.action.primary`
- `button.background.hover → color.action.primary-hover`
- `card.padding.inner → spacing.component.gap`

**Not every system needs this tier.** Introduce it deliberately and record the decision. Common
triggers: white-labelling / multi-brand needing component-level overrides; a component expected to
diverge from the semantic palette across themes; or a complex component (data table, rich text editor)
with enough semantic references that documenting them in a machine-readable way adds value. Otherwise
semantic tokens referenced directly in component code are sufficient.

## Reference rules (strictly downward)

- Component → semantic → primitive. **No token references a higher-specificity tier.**
- An upward reference (a semantic token pointing at a component token) is no longer semantic.
- The most architecturally damaging violation is a **cross-tier reference at the wrong level**:
  `button.background.default: {color.blue.500}` applies the right colour today but breaks the semantic
  contract — a rebrand or theme change that correctly updates the semantic tier never reaches it. This
  is the single highest-value thing a token audit looks for.

## Naming conventions

Names read as hierarchical paths: `category.role.variant.state`. Not all segments are required —
a primitive may be `category.scale-value`; a semantic token needs at least `category.role`; a component
token needs `component.property.state`.

Reserved terms to avoid in **semantic** names:
- Colour names (`blue`, `green`, `red`) — describe appearance, not intent.
- Ambiguous sizes (`large`, `small`, `medium`) — use the scale value or a role.
- Empty qualifiers (`main`, `base`, `default` at the semantic level) — they describe nothing.

Pick one casing convention (kebab `color-action-primary`, dot `color.action.primary`, or camel
`colorActionPrimary`) and apply it without exception.

## Cross-platform

Handle platform differences at the **transformation layer**, not in token names. `spacing.4` transforms
to `16px` (web), `16pt` (iOS), `16dp` (Android) via Style Dictionary or equivalent — never
`spacing.web.4` / `spacing.ios.4`. The only exception is a value that genuinely cannot be normalised
across platforms; document it as an exception, not the norm.

## DTCG 2025.10 alignment

The Design Tokens Community Group shipped its first stable spec (2025.10) in October 2025. Token work
should recognise and work with it natively:

- **Types** — 13 token types via `$type`; flag untyped tokens as a gap. Five are *composite* (typography,
  shadow, border, transition, gradient) combining sub-values.
- **Resolvers** (`.resolver.json`) — compose token files, define modes (light/dark, brands). A semantic
  token declared in a resolver but missing a mode-specific value is a coverage gap.
- **Sets** — collections of tokens (inline or external) enabling multi-file architectures; map set
  membership when auditing coverage.
- **Composite validation** — check sub-value compliance, not just the top level. A typography composite
  with a hardcoded `fontSize` but a proper `fontFamily` reference is a *partial* violation.
- **Migration is a maturity signal, not a violation** — teams on older Style Dictionary / custom JSON
  get an informational DTCG-alignment note, surfaced as its own section in a token audit.

## Governance hook

Record token-architecture decisions — why a naming convention won over alternatives, why the primitive
scale has the values it does, and any debated semantic names — as decision records (route to
`documentation-and-adrs`). See `governance-and-adoption.md`.

## Related references

- `system-health-and-maturity.md` — tokens are one of the seven health dimensions.
- `drift-detection.md` — token drift (raw values, wrong-tier references) detection per styling approach.
- `governance-and-adoption.md` — recording token decisions; token compliance as an adoption signal.
- `ai-readiness.md` — token documentation as machine-readable context.
- Skill overview: `../SKILL.md`. Build-time token styling (Tailwind `@theme`) lives in `radix-tailwind-component-patterns`.
