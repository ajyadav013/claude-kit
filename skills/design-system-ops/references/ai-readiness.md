# AI-readiness & Component Challenge Rating

The reference behind the **AI-readiness** framework in `design-system-ops`. Re-derived stack-agnostic
from the MIT `murphytrueman/design-system-ops` `ai-readiness` and `component-bestiary-reference`
knowledge notes.

## What AI-readiness means

An AI-ready design system can be consumed, reasoned about, and generated from by agents **without
requiring implicit knowledge that was never written down**. Most systems are built for humans —
designers infer intent from context, developers ask a colleague. Agents cannot infer, ask, or defer;
they work only with what is explicit. "Use this to show important information" gives an agent no basis
to know what "important" means, which components carry that role, or how this differs from three others
that also "show information." The gap AI exposes is not new — the same implicit knowledge has always
confused new hires and external contributors. **AI-readiness is design-systems quality applied with
more precision.**

## The context cascade

Context quality at the source compounds through every downstream consumer. Strong metadata in a
component → accurate AI-generated code → correct implementation → reliable tests. Weak metadata →
hallucinated props → broken implementation → failing tests. There is no neutral handoff — each layer
inherits good context or amplifies bad. So invest at the **source** (design specs, component
descriptions, token docs): every hour making a description explicit saves multiples downstream in
reduced misuse, fewer support requests, and better generated output.

## The three pillars

An agent-ready system needs all three working together:

- **Coverage** — every interactive state documented (not just the happy path), every prop with type +
  default + intent, every edge case (long strings, empty states, max density, RTL). Coverage is the raw
  material; a component with five documented states produces reliable AI output, one with only its
  default does not.
- **Context** — coverage made *machine-consumable*: structured metadata alongside prose, consistent
  section formats an agent can locate and parse, and explicit relationships ("can contain," "contained
  in," "alternative to" — not a vague "related to"). Context is what turns a reference library into
  infrastructure agents can reason about.
- **Validation** — automated checks (prop-type, accessibility, token compliance) plus human sign-off
  gates that confirm agent-generated UI is correct and safe to ship. Coverage provides the material,
  context makes it consumable, validation closes the loop.

## The six dimensions of component AI-readiness

A component is AI-ready when an LLM reading only its description can:

1. **Identify** the correct component for a requirement (distinguished from similar ones).
2. **Configure** it correctly (props with types, defaults, intent).
3. **Avoid** the common misuse patterns (anti-patterns specific to *this* component, not generic).
4. **Place** it correctly (composition rules: what it can contain, what can contain it).
5. **Apply it accessibly** without extra guidance (role, keyboard, focus documented at the component
   level — not a pointer to WCAG).
6. **Generate** correct usage examples that match real-world usage.

Weak descriptions fail these in order; an audit of AI-readiness checks each.

## Component Challenge Rating (CR)

Borrowed from the Component Bestiary (thecomponentbestiary.com), which rates components by
**implementation danger**, not visual complexity. CR calibrates how much documentation, anti-pattern
coverage, and accessibility rigour a component warrants — the cost of an agent getting a modal wrong far
exceeds getting a badge wrong.

| CR | Danger | Examples | Documentation / validation bar |
|----|--------|----------|--------------------------------|
| **1–2** | Low | text, dividers, badges, avatars, skeletons | Light: usage guidelines, basic anti-patterns, standard a11y notes |
| **3–4** | Moderate | buttons (variant misuse), inputs (labelling), tooltips, cards | Full anti-patterns with consequences; edge cases; a11y explicitly tested |
| **5–6** | Significant | modals/dialogs (focus trap), select/combobox (keyboard), nav (landmarks, current state) | Full anti-pattern + explicit composition constraints; thorough AI description |
| **7+** | High | date pickers, data tables, rich text editors, drag-and-drop | **Mandatory a11y audit before release**, a decision record, failure-mode docs, post-release misuse monitoring |

**Use CR to sequence work:** audit and document high-CR components first; they carry the most
accessibility and misuse risk. This is not licence to skip low-CR components — it is about investing
*more time per component* at the high-CR end.

## Related references

- `system-health-and-maturity.md` — AI-readiness is one of the seven health dimensions.
- `governance-and-adoption.md` — high-CR components carry a higher contribution/release bar; decision records for CR 7+.
- `drift-detection.md` — weak machine-readable context is a leading cause of accidental re-implementation.
- `token-architecture.md` — token documentation is part of machine-readable context.
- Skill overview: `../SKILL.md`. Per-component WCAG review is `accessibility-review`; CR tells you which components to send there first.
