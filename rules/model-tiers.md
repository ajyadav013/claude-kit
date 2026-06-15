# Model Tiers

Each agent declares an explicit `model:` in its frontmatter — pick the tier deliberately. Three tiers
balance capability against cost (the most capable model costs several times the cheapest per token), so
spend the strongest reasoning where a wrong answer is expensive and the cheapest where the work is
mechanical. This is the concrete assignment policy behind the "resource-aware effort" guidance in
`.claude/rules/reasoning-techniques.md`.

> Adapted from a portfolio project's model-tiers rule; aligned to claude-kit's agent roster. Model
> names are Claude tiers, not a tech stack — the tier *intent* matters more than the exact alias.

## Policy

| Tier | Model | Use for | Agents |
|------|-------|---------|--------|
| **Critical** | `opus` | Architecture decisions, deep code/security reasoning, orchestration, adversarial review | `orchestrator`, `developer`, `devils-advocate`, `owasp-reviewer` |
| **Default** | `sonnet` | Specs, reviews, testing, infra, coordination, scanning, incident command, risk classification | `spec-doc-writer`, `story-planner`, `technical-architect`, `em-reviewer`, `senior-backend-dev`, `senior-frontend-dev`, `ui-designer`, `merge-reviewer`, `sdlc-code-reviewer`, `unit-tester`, `e2e-tester`, `tester`, `senior-tester`, `acceptance-reviewer`, `risk-classifier`, `security-reviewer`, `secret-scanner`, `dependency-scanner`, `policy-validator`, `devops-engineer`, `observability-engineer`, `pr-raiser`, `incident-responder` |
| **Fast** | `haiku` | Mechanical, read-only reporting | `auditor` |

Stack **overlay** agents (e.g. `postgres-specialist`, `mongodb-specialist`, `migration-specialist`,
`db-performance-reviewer`) and the organization persona agents (`pm-copilot`, `founder-prototype-agent`,
`support-ticket-engineer`, `data-workflow-agent`, `internal-tools-builder`) default to the **Default**
tier — they are focused specialists/personas, not deep-reasoning orchestrators.

## Notes

- **Per-session promotion.** For a high-risk change (auth, migrations, billing) or a SEV1 incident,
  start the session on the most capable model, or temporarily bump a Default agent's frontmatter to
  `opus`. The senior-dev reviewers and `incident-responder` are the most common candidates. See
  `.claude/rules/human-in-the-loop.md` for when such changes are human-gated.
- **`owasp-reviewer` stays `opus`** (vulnerability reasoning) even though its sibling scanners
  (`secret-scanner`, `dependency-scanner`, `policy-validator`) are `sonnet` (pattern/tool work).
- **Re-map when names/prices change.** Keep the tier *intent* (Critical / Default / Fast); swap the
  concrete alias if Anthropic's model lineup shifts.

## Profile cost expectations

Token cost scales with the **profile** (the agent / skill / hook set it installs — see
`catalog/profiles.yaml`): more agents and more parallel review lanes mean more model turns. As a
*relative* guide (not a currency figure):

- **lean** — cheapest: ~5 agents, a single review lane, no Devil's Advocate, fewest gates. Only
  `orchestrator` + `developer` run on `opus`; the rest are `sonnet`/`haiku`.
- **standard** — adds the spec / design / test / security lanes and the blind-review + Devil's
  Advocate pass: mostly `sonnet` reviewers and scanners layered on top of lean.
- **enterprise** — heaviest: adds the DevOps / Observability / audit agents, `skills: all`, and
  `hooks: all`, with more gates — but still only the four `opus` agents (`orchestrator`, `developer`,
  `devils-advocate`, `owasp-reviewer`); everything it adds is `sonnet`/`haiku`.

Scale effort to the work, not the ceremony: pick the smallest profile that fits, and use the per-agent
tier table above plus `.claude/rules/reasoning-techniques.md` ("resource-aware effort") to avoid
spending `opus` on mechanical turns.
