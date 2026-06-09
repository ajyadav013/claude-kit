# AI Working Agreement

This is the charter for how humans and Claude work together in this project. It is the umbrella over
the organization capability layer: a short summary of the contract, with each clause pointing at the
rule that defines it in full. When the rules below conflict, the stricter one wins.

## The agreement

1. **Plan before large edits.** State the goal, scope, and steps before changing anything beyond a
   trivial fix; turn a raw prompt into a scoped, verifiable task first.
   See `.claude/rules/prompt-to-task-conversion.md` and `.claude/rules/mandatory-workflow.md`.
2. **Stay within the granted autonomy level.** Act only as far as you're authorized; if the task needs
   more autonomy than granted, stop and ask. See `.claude/rules/autonomy-levels.md`.
3. **Classify the risk of every change** as low / medium / high / restricted, and apply the matching
   protocol. See `.claude/rules/risk-classification.md`.
4. **Ask when unsure.** Resolve ambiguity instead of guessing; never invent a missing requirement.
   See `.claude/rules/human-in-the-loop.md`.
5. **Make it safe for non-engineers.** Explain in plain language, keep changes reversible, and use the
   guardrails for vibe-coding. See `.claude/rules/non-engineer-safe-coding.md`.
6. **Never touch secrets, production data, or PII without approval.** No reading, writing, copying, or
   exposing them outside the sanctioned path. See `.claude/rules/secrets-policy.md`,
   `.claude/rules/production-data-policy.md`, and `.claude/rules/pii-policy.md`.
7. **Always test and review.** Every change meets the project's linter / test runner / build and passes
   review before it ships. See `.claude/rules/quality-gates.md`.
8. **Use branches and PRs; never push to the protected branch directly.**
   See `.claude/rules/branch-and-pr-policy.md`.
9. **Get human approval for high- and restricted-risk work**, and respect any regulatory obligations.
   See `.claude/rules/human-in-the-loop.md` and `.claude/rules/compliance-policy.md`.

## Rules

- **This charter only summarizes.** The linked rule is always the source of truth for its clause;
  read it before acting in that area.
- **The strictest applicable rule applies.** A higher risk tier or a stricter policy overrides a more
  permissive default.
- **The workflow is non-negotiable.** No clause here lets you skip the pipeline or its gates
  (`.claude/rules/mandatory-workflow.md`, `.claude/rules/quality-gates.md`).

> Part of claude-kit's organization capability layer (vibe-coding). It points at, and is bound by,
> `.claude/rules/autonomy-levels.md`, `.claude/rules/risk-classification.md`,
> `.claude/rules/human-in-the-loop.md`, `.claude/rules/prompt-to-task-conversion.md`,
> `.claude/rules/non-engineer-safe-coding.md`, `.claude/rules/secrets-policy.md`,
> `.claude/rules/production-data-policy.md`, `.claude/rules/pii-policy.md`,
> `.claude/rules/branch-and-pr-policy.md`, `.claude/rules/compliance-policy.md`,
> `.claude/rules/mandatory-workflow.md`, and `.claude/rules/quality-gates.md`.
