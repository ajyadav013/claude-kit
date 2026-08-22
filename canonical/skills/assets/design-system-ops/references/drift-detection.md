# Drift detection

The reference behind the **drift-detection** framework in `design-system-ops`. Re-derived stack-agnostic
from the MIT `murphytrueman/design-system-ops` `drift-detection` skill.

Drift is the **normal condition** of a used design system — the accumulated distance between intent and
actual implementation across consuming products. The question is never *whether* the system has drifted
(it has) but whether the drift is **intentional**, how **severe**, and whether it is **compounding**.
Not all drift is bad: a documented, deliberate exception is a design decision; an unknowing
re-implementation with slightly different spacing is maintenance debt. The response differs, so every
finding must be classified before it gets a recommendation.

## Step 1 — Scope and reference point

Scope tightly: a specific product, component set, or token scope produces a far more actionable report
than "the whole system." Then fix the **source of truth** drift is measured against — the Figma library,
the published package at a version, or the documented spec. If there is no single source of truth, that
is itself the top finding.

## Step 2 — Detect across four kinds of drift

### Visual drift
Differences in visual treatment vs the reference — spacing, colour (especially non-token values),
typography, radius, shadow, icon usage. Note whether each looks intentional or accidental.

### Behavioural drift
Differences in interactive behaviour — state transitions, animation, timing, keyboard behaviour, focus
management. Hardest to detect without testing, highest risk because it includes **accessibility
regressions**.

### API drift
Components implemented with different props, prop names, or prop semantics than the published API —
common when a team built a local version before the system component existed and never migrated.

### Token drift
Raw values where tokens belong; tokens referenced at the wrong tier; local overrides conflicting with
semantic intent; inconsistent token names. Detection is **styling-specific**:

| Styling | Look for |
|---------|----------|
| CSS custom properties | raw values outside `var()` |
| SCSS | raw literals not using `$` variables (tier inferred from naming: `$color-blue-500` → primitive, `$color-action-primary` → semantic) |
| Tailwind | arbitrary-value brackets (`h-[12px]`, `bg-[#ff0000]`); standard utilities resolving to configured tokens are **not** drift |
| CSS-in-JS | raw values outside theme-object references |

(See `token-architecture.md` for the tier model token drift is measured against.)

## Step 3 — Classify every instance

Classification drives the response:

- **A — Intentional divergence.** Deliberate, documented exception → candidate to fold back as a
  contribution, or to formalise as a variant.
- **C — Accidental drift.** Unknowing re-implementation / local override → correct it **and** address
  the root cause (often a discoverability or onboarding gap).
- **E — System gap.** The drift exists because the system is *missing* something teams needed → the
  fix is a system change (new component/token/pattern), not a correction to the consumer.

(Intentional-but-undocumented and persistent drift escalate in severity — see trend, below.)

## Step 4 — Severity and response

Rate each finding by user impact and compounding risk (accessibility regressions rank highest), give a
recommended response tied to its classification, and end with a prioritised list. A drift report that
lists everything at equal weight is not actionable.

## Recurring runs — track the trend

Compare against the previous report: new drift, resolved drift, **persistent** drift (present 2+
cycles → escalate), and classification shift. Report **drift velocity** (is new drift accumulating
faster than it is resolved?) and whether the mix is shifting toward system gaps (E) or accidental drift
(C). A rising share of E means the system is falling behind its consumers' needs.

## Small-system note (fewer than 5 components)

Scope to the full system (no need to sample); drift is more likely intentional (A) or a system gap (E)
than accidental in small, aligned teams. Simplify the output to a per-component checklist; if nothing
has drifted, say so and recommend a review cadence.

## Related references

- `token-architecture.md` — the tier model token drift is measured against.
- `system-health-and-maturity.md` — drift feeds the Components and Tokens health dimensions.
- `governance-and-adoption.md` — intentional drift may become a contribution; accidental drift signals adoption friction.
- `ai-readiness.md` — weak machine-readable context is a leading cause of accidental re-implementation.
- Skill overview: `../SKILL.md`. Checking ONE component against its spec is build-time `ui-ux-design`, not this system-wide sweep.
