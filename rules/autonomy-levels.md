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
