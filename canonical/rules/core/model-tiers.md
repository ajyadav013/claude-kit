# Model Tiers

Each agent declares a semantic model tier in its definition — pick the tier deliberately. Three tiers
balance capability against cost (the most capable model costs several times the cheapest per token), so
spend the strongest reasoning where a wrong answer is expensive and the cheapest where the work is
mechanical. This is the concrete assignment policy behind the "resource-aware effort" guidance in
`rule://reasoning-techniques`.

> Adapted from a portfolio project's model-tiers rule; aligned to {{ provider.executable.cli }}'s agent roster. Model
> names are provider model tiers, not a tech stack — the tier *intent* matters more than the exact alias.

## Policy

| Tier | Model | Use for | Agents |
|------|-------|---------|--------|
| **Critical** | `{{ provider.model.deep }}` | Architecture decisions, deep code/security reasoning, orchestration, adversarial review | `orchestrator`, `developer`, `devils-advocate`, `owasp-reviewer` |
| **Default** | `{{ provider.model.balanced }}` | Specs, reviews, testing, infra, coordination, scanning, incident command, risk classification | `spec-doc-writer`, `story-planner`, `technical-architect`, `em-reviewer`, `senior-backend-reviewer`, `senior-frontend-reviewer`, `senior-backend-dev`, `senior-frontend-dev`, `ui-designer`, `merge-reviewer`, `sdlc-code-reviewer`, `unit-tester`, `e2e-tester`, `tester`, `senior-tester`, `acceptance-reviewer`, `auditor`, `risk-classifier`, `security-reviewer`, `secret-scanner`, `dependency-scanner`, `policy-validator`, `devops-engineer`, `observability-engineer`, `pr-raiser`, `incident-responder` |
| **Fast** | `{{ provider.model.fast }}` | Mechanical, read-only reporting | *(currently unassigned — `auditor` moved to Default: driving a multi-step browser-MCP audit is tool orchestration, not mechanical reporting. Reserve this tier for genuinely mechanical single-pass work.)* |

Stack **overlay** agents (e.g. `postgres-specialist`, `mongodb-specialist`, `migration-specialist`,
`db-performance-reviewer`) and the organization persona agents (`pm-copilot`, `founder-prototype-agent`,
`support-ticket-engineer`, `data-workflow-agent`, `internal-tools-builder`) default to the **Default**
tier — they are focused specialists/personas, not deep-reasoning orchestrators.

## Notes

- **Per-session promotion.** For a high-risk change (auth, migrations, billing) or a SEV1 incident,
  start the session on the most capable model, or temporarily raise a Default agent's semantic tier to
  `{{ provider.model.deep }}`. The senior-dev reviewers and `incident-responder` are the most common candidates. See
  `rule://human-in-the-loop` for when such changes are human-gated.
- **`owasp-reviewer` stays `{{ provider.model.deep }}`** (vulnerability reasoning) even though its sibling scanners
  (`secret-scanner`, `dependency-scanner`, `policy-validator`) are `{{ provider.model.balanced }}` (pattern/tool work).
- **Re-map when names/prices change.** Keep the tier *intent* (Critical / Default / Fast); provider
  adapters may swap concrete aliases as their model lineups shift.

## Probe before fan-out

Tier availability is a property of the *deployment*, not the payload — a tier mapping can
name a model the provider account doesn't serve, and the failure signature is an **instant,
zero-token spawn death**, easily mistaken for an agent bug. So before a run's **first** fan-out:
probe-spawn one trivial agent (a one-word reply) per model tier the run plans to use. A tier whose
probe dies instantly is unavailable here: **fall back one tier** (Fast → Default → Critical),
record the override in `state://continuity`, and keep it for the rest of the run — don't re-discover the
same failure lane by lane. The probe also doubles as the credential-freshness check for long runs:
verify auth by the probe's *behavior*, never by reading secrets or `.env`
(`rule://agent-guardrails`). Deployment-neutral by design — probe tiers, not provider
names.

## When to escalate a tier

The table above is the *default* assignment. Mid-task, an agent may want to **escalate** to a more
capable model (or a human asks "should we move this to {{ provider.model.deep }}?"). Escalation trades cost for reasoning
depth, so it must be **justified, not reflexive**.

> **The Iron Law: no escalation without investigation first.** Escalation is never a shortcut for
> "maybe a smarter model will figure it out." If you can't articulate *why* the current tier is
> insufficient, escalating is premature — investigate the root cause first.

**Four questions to answer before escalating:**

1. **Understood?** Can I state specifically what reasoning the current tier is missing — is this a
   *capability* gap or just a *knowledge* gap? (A knowledge gap → gather information, don't escalate.)
2. **Investigated?** Have I done the systematic work (read the code, traced the data, reproduced the
   failure) — see `rule://reasoning-techniques` — rather than guessing?
3. **Right lever?** Is more model capability actually the fix, or is the real problem a wrong approach,
   a missing requirement (`rule://human-in-the-loop`), or insufficient context?
4. **Worth it?** Does the stakes/consequence justify the added cost (`rule://risk-classification`)?

**Legitimate triggers:** genuine nuance/judgment (security trade-offs), multi-step reasoning under
uncertainty (architecture), novel patterns with no precedent, high stakes (production/irreversible),
or weighing several valid interpretations.

**Anti-rationalizations — these mean STOP and investigate, not escalate:**

| Rationalization | Reality |
|---|---|
| "Maybe a smarter model will figure it out" | Thrashing — find the root cause first |
| "Several attempts already failed" | Suggests a wrong approach, not insufficient capability — question your assumptions |
| "We're under time pressure" | Urgency doesn't change task complexity; systematic investigation is faster than guess-and-escalate |
| "Just to be safe / just in case" | False safety — assess the *actual* complexity before spending the capability |

The same discipline governs the **fix-attempt** loop in `rule://agent-resilience` (3-strike
rule) and the budget-exhaustion escalations in `rule://quality-gates`: investigate, then
escalate to a tier *or a human* deliberately.

## Profile cost expectations

Token cost scales with the **profile** (the agent / skill / hook set it installs — see
`catalog/profiles.yaml`): more agents and more parallel review lanes mean more model turns. As a
*relative* guide (not a currency figure):

- **lean** — cheapest: ~5 agents, a single review lane, no Devil's Advocate, fewest gates. Only
  `orchestrator` + `developer` run on `{{ provider.model.deep }}`; the rest are `{{ provider.model.balanced }}`.
- **standard** — adds the spec / design / test / security lanes and the blind-review + Devil's
  Advocate pass: mostly `{{ provider.model.balanced }}` reviewers and scanners layered on top of lean.
- **enterprise** — heaviest: adds the DevOps / Observability / audit agents, `skills: all`, and
  `hooks: all`, with more gates — but still only the four `{{ provider.model.deep }}` agents (`orchestrator`, `developer`,
  `devils-advocate`, `owasp-reviewer`); everything it adds is `{{ provider.model.balanced }}`.

Scale effort to the work, not the ceremony: pick the smallest profile that fits, and use the per-agent
tier table above plus `rule://reasoning-techniques` ("resource-aware effort") to avoid
spending `{{ provider.model.deep }}` on mechanical turns.

## Enforcing the tier policy (provider adapter)

Everything above is advisory unless the active host can gate worker creation by semantic tier or
logical agent id. A provider adapter may translate those two stable inputs into its native
permission syntax. Keep that translation outside this rule: parameter-matching rules, aliases,
headless prompt behavior, and settings locations differ by host and version.

When enforcement is available:

- Gate the logical **deep** tier and named high-cost agents, not a particular provider model alias.
- Cover both a tier requested at dispatch time and a tier declared in agent metadata.
- Treat unattended approval prompts as denials unless the provider explicitly documents another
  safe behavior.
- Keep the default kit policy provider-neutral and opt in to billing or organization-specific
  permission gates at the project or user policy layer.
