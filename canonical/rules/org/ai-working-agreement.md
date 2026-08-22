# AI Working Agreement

This is the charter for how humans and the coding agent work together in this project. It is the umbrella over
the organization capability layer: a short summary of the contract, with each clause pointing at the
rule that defines it in full. When the rules below conflict, the stricter one wins.

## The agreement

1. **Plan before large edits.** State the goal, scope, and steps before changing anything beyond a
   trivial fix; turn a raw prompt into a scoped, verifiable task first.
   See `rule://prompt-to-task-conversion` and `rule://mandatory-workflow`.
2. **Stay within the granted autonomy level.** Act only as far as you're authorized; if the task needs
   more autonomy than granted, stop and ask. See `rule://autonomy-levels`.
3. **Classify the risk of every change** as low / medium / high / restricted, and apply the matching
   protocol. See `rule://risk-classification`.
4. **Ask when unsure.** Resolve ambiguity instead of guessing; never invent a missing requirement.
   See `rule://human-in-the-loop`.
5. **Make it safe for non-engineers.** Explain in plain language, keep changes reversible, and use the
   guardrails for vibe-coding. See `rule://non-engineer-safe-coding`.
6. **Never touch secrets, production data, or PII without approval.** No reading, writing, copying, or
   exposing them outside the sanctioned path. See `rule://secrets-policy`,
   `rule://production-data-policy`, and `rule://pii-policy`.
7. **Always test and review.** Every change meets the project's linter / test runner / build and passes
   review before it ships. See `rule://quality-gates`.
8. **Use branches and PRs; never push to the protected branch directly.**
   See `rule://branch-and-pr-policy`.
9. **Get human approval for high- and restricted-risk work**, and respect any regulatory obligations.
   See `rule://human-in-the-loop` and `rule://compliance-policy`.

## Rules

- **This charter only summarizes.** The linked rule is always the source of truth for its clause;
  read it before acting in that area.
- **The strictest applicable rule applies.** A higher risk tier or a stricter policy overrides a more
  permissive default.
- **The workflow is non-negotiable.** No clause here lets you skip the pipeline or its gates
  (`rule://mandatory-workflow`, `rule://quality-gates`).

> Part of {{ provider.executable.cli }}'s organization capability layer (vibe-coding). It points at, and is bound by,
> `rule://autonomy-levels`, `rule://risk-classification`,
> `rule://human-in-the-loop`, `rule://prompt-to-task-conversion`,
> `rule://non-engineer-safe-coding`, `rule://secrets-policy`,
> `rule://production-data-policy`, `rule://pii-policy`,
> `rule://branch-and-pr-policy`, `rule://compliance-policy`,
> `rule://mandatory-workflow`, and `rule://quality-gates`.
