# Autonomy Levels

How much an agent may do on its own before a human must act. The level is chosen at install time
(organization scope) and recorded in the project config; **assisted** is the default everywhere. State
the active level in working memory and operate within it. This is the operating posture; the
deterministic parts are enforced by hooks and `settings.permissions`, the rest is followed as policy.

| Level | May do | Must NOT do without a human |
|-------|--------|------------------------------|
| **advisory** | inspect, explain, plan, review | edit files unless explicitly asked |
| **assisted** (default) | edit files **after** explaining the plan | broad/cross-cutting changes without asking first |
| **autonomous-local** | implement changes within repo boundaries; must run the project's validation (or explain why it could not) | push, open PRs, touch anything outside the repo |
| **autonomous-pr** | create branches + PR-ready changes | **merge** — human review is required before merge |
| **enterprise-controlled** | work only through strict gates with an audit trail | edit sensitive files without approval; complete without the security + review agents passing |

## Precedence — overrides may only tighten

When org policy and a repo- or user-level setting disagree, the resolution is always the **stricter**
of the two: effective autonomy = **min(org, repo)**; allow-lists **intersect**; deny-lists **union**;
a warn may be escalated to a block locally, but a block is never downgraded to a warn. A repo can
run *more* cautiously than its org demands, never less — there is no repo-level "loosen" switch.
Legitimate exceptions go through the named bypass surfaces (the "Bypass contract" in
`docs/org-capabilities.md` of the claude-kit repo), which are explicit and auditable — not a quiet
config override.

## Rules

- **Never exceed the active level.** If a task needs more autonomy than granted, stop and ask — do not
  silently escalate. See `.claude/rules/human-in-the-loop.md`.
- **Risk can lower the effective ceiling.** High-risk or restricted work (auth, payments, secrets,
  production data, migrations, infrastructure) always requires explicit approval and review regardless
  of level. See `.claude/rules/risk-classification.md`.
- **Higher levels add guardrail hooks, not fewer checks.** `autonomous-*` and `enterprise-controlled`
  enable warn/block hooks (large-edit, missing-tests, sensitive-file, settings/frontmatter validation,
  push guard, and a local audit log) — they make more autonomy *safer*, not looser.
- **Default to the lower interpretation.** When unsure whether an action is permitted at the current
  level, treat it as not permitted and ask.

> Part of claude-kit's organization capability layer. Cross-refs `.claude/rules/human-in-the-loop.md`,
> `.claude/rules/mandatory-workflow.md`, `.claude/rules/quality-gates.md`.
