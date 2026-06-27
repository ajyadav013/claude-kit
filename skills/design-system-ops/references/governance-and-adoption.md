# Governance & adoption

The reference behind the **governance lifecycle** and **adoption measurement** frameworks in
`design-system-ops`. Re-derived stack-agnostic from the MIT `murphytrueman/design-system-ops`
governance skills and the `adoption-measurement` knowledge note.

## Governance

Governance is how change enters the system without breaking the consumers who depend on it.

### Deprecation

Never silently remove a token or component. A deprecation has: a **reason**, a **replacement** (the
migration target), a **migration path** (often a codemod where mechanical), a **timeline** with a hard
removal version, and a **communication** sized to the blast radius. Mark the artefact deprecated in the
docs and the code (annotation/lint) *before* removal, and track how many consumers still use it — you
remove it when usage reaches zero or the timeline expires, whichever the policy says.

### Decision records

Consequential design-system decisions must be recorded so they are not re-litigated: token naming
conventions, the primitive scale, debated semantic names, whether to introduce component tokens,
deprecations, and any deliberate divergence promoted from drift. Write the record itself with the kit's
`documentation-and-adrs` skill — this skill decides *what* deserves a record; that skill is *how* to
write it. A rejected proposal is worth recording too.

### Contribution workflow

Define how consumers propose changes: where requests land, who triages, what bar a contribution must
clear (tests, docs, a11y for high-Challenge-Rating components — see `ai-readiness.md`), and how it gets
released. The goal is to convert **intentional drift** (see `drift-detection.md`) into contributions
rather than forks.

### Change communication

Size the communication to the change. A patch-level token tweak needs a changelog line; a breaking
component API change or a deprecation needs an explicit, targeted notice to affected teams with the
migration path. Under-communicating a breaking change is how adoption erodes.

## Adoption measurement

### Coverage ≠ adoption

**Coverage** = does the system provide what teams need. **Adoption** = do teams actually use what it
provides. A system can have 100% coverage and 20% adoption if teams build custom implementations instead
of consuming the library. The interventions differ: low coverage is a *supply* problem (build more);
low adoption with high coverage is a *demand* problem (understand why teams aren't consuming).

### The four signals

1. **Installation & integration** — are teams using the packages at all? Install counts, version
   currency (how far behind latest each consumer is), and whether they import the token layer, the
   component layer, or both. Necessary but not sufficient — a team can install and not use.
2. **Component consumption** — import analysis across consuming codebases: which components, how often,
   by how many teams. Watch the **long tail**: 5 components driving 90% of imports with 30 rarely used
   is a tail adoption problem even if the headline looks fine.
3. **Token compliance** — are teams using tokens rather than hardcoding values? Scan consumers for raw
   values that should be token references. This is the signal most directly tied to system *value* —
   token adoption is what makes theming, rebranding, and consistency possible.
4. **Pattern adherence** — are teams following documented composition/layout/interaction patterns?
   Hardest to automate; needs periodic manual or heuristic review.

### Leading vs lagging indicators

Report **both**. Leading indicators predict future health: onboarding time, contribution rate, support
ticket volume/topics, documentation views and search patterns. Lagging indicators confirm past
outcomes: import counts, token-compliance %, version currency, count of custom implementations that
duplicate system functionality. Leading alone is aspirational; lagging alone is retrospective.

### Always break down per-team

System-level averages mask team-level variation: 85% overall token compliance might be three teams at
98% and two at 40%. The team-level view is where the actionable insight lives. Pair it with **adoption
maturity stages** per team — *Aware* (knows it exists, not integrated → onboarding, not pressure) →
integrating → consuming → contributing — and calibrate the intervention to the stage, not the average.

## Related references

- `token-architecture.md` — what token decisions records capture; token compliance as the highest-value adoption signal.
- `drift-detection.md` — intentional drift → contributions; accidental drift signals adoption friction.
- `system-health-and-maturity.md` — Governance and Adoption are two of the seven health dimensions.
- `ai-readiness.md` — contribution bars are higher for high-Challenge-Rating components.
- Skill overview: `../SKILL.md`. Write the decision records themselves with `documentation-and-adrs`.
