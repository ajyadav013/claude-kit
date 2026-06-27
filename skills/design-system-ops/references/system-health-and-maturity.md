# System health & maturity

The reference behind the **system-health assessment** framework in `design-system-ops`. Re-derived
stack-agnostic from the MIT `murphytrueman/design-system-ops` `system-health` skill.

A health assessment is a **holistic, cross-cutting snapshot** of the whole system — useful for
prioritisation, a quarterly review artefact, or a stakeholder conversation about where to invest. It is
*not* a deep dive into one area; for that, route to the focused work (token audit, component audit,
`drift-detection.md`, etc.). Health is how well the dimensions work *together*: excellent tokens with
terrible governance is still fragile; high adoption with thin documentation is one departure from
collapse.

## Step 0 — Classify the library type (from the codebase, not the README)

Not everything is a design system, and the type changes what advice is useful. A repo named
"design-system" with 4 components, no tokens, and no docs is an early **component library**, not a
design system with gaps. Detect from signals: token files (JSON/DTCG/SCSS vars/CSS custom
properties/Tailwind config/Style Dictionary), component count, a docs platform config (Storybook,
Fractal, Zeroheight), publishing config, and whether there are versioned releases.

| Type | What it is | Assess | Don't flag |
|------|-----------|--------|-----------|
| **Design system** | Tokens + components + docs + governance, versioned, multi-team | all seven dimensions | — |
| **Component library** | Shared component package, no formal governance/adoption tracking | Tokens, Components, Documentation | Governance/Adoption are "when you're ready," not gaps |
| **Pattern library** | Documented UI patterns (Fractal/Storybook/static), reference-first | Documentation, Components | Token architecture is often absent *by design* |
| **Utility collection** | Shared helpers/mixins/base styles — a first step toward shared UI | what's there, what's consistent | don't project a design-system roadmap onto it |

Put the classification in the report header and calibrate every recommendation to it.

## Step 1 — Baseline the maturity stage

Before grading any dimension, place the system on the maturity scale. This calibrates expectations — an
ad-hoc system should not be judged for lacking platform-grade capabilities.

1. **Ad-hoc** — components exist but are ungoverned.
2. **Managed** — a library exists with some governance.
3. **Systematic** — consistent processes across the system.
4. **Measured** — quantitative tracking and recurring reviews.
5. **Optimised** — platform infrastructure with consumer contracts.

Frame findings as "appropriate for this stage" or "below expectations for this stage," never against an
absolute scale. A *managed* system with no AI-readiness is expected; a *measured* one with none is a
significant gap.

## Step 2 — Grade the seven dimensions

Assess each and assign a status:

- **Strong** — meeting/exceeding expectations for this maturity level.
- **Functional** — working, with notable gaps.
- **Weak** — present but causing problems, or significantly behind expectations.

| Dimension | What "healthy" looks like |
|-----------|---------------------------|
| **Tokens** | Tiered architecture, downward references, consistent naming, DTCG-aware (see `token-architecture.md`) |
| **Components** | Clear APIs, full state coverage, sensible complexity distribution, documented |
| **Documentation** | Usage guidelines + anti-patterns per component; coverage tracked against inventory |
| **Adoption** | Teams consume rather than re-implement; token compliance high; per-team (see `governance-and-adoption.md`) |
| **Governance** | Contribution workflow, deprecation process, decision records, change communication |
| **AI-readiness** | Machine-readable context; agents can pick/configure/use components correctly (see `ai-readiness.md`) |
| **Platform maturity** | Versioned releases, consumer contracts, recurring review cadence |

## Small-system note (fewer than 5 components)

The assessment still works, with adjustments: complexity distribution is meaningless at 1–4 components
(skip it) — assess API clarity, state coverage, and per-component docs instead. Redefine adoption as
"what share of the team's real needs the system serves," not raw component count: 3 components covering
80% of needs is healthier than 30 covering 20%.

## Output

A findings-based executive summary: the library-type classification and maturity stage in the header, a
status per dimension with the evidence behind it, and a **prioritised action list**. Distinguish
measured from estimated findings; if assessed by interview rather than inspection, say so and flag what
needs verification. For a recurring review, add a **health-trend** section (per-dimension improved /
steady / regressed since the last report) and call out any regression explicitly.

## Related references

- `token-architecture.md` — the Tokens dimension in depth.
- `drift-detection.md` — the system-wide divergence sweep that feeds the Components/Tokens dimensions.
- `governance-and-adoption.md` — the Governance and Adoption dimensions.
- `ai-readiness.md` — the AI-readiness dimension.
- Skill overview: `../SKILL.md`. Per-screen build-time compliance is `ui-ux-design`; WCAG review is `accessibility-review`.
