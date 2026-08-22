# Non-Engineer-Safe Coding

When a non-engineer drives the work — a founder, PM, support agent, or operator describing what they
want — the agent supplies the engineering judgment they cannot. The driver owns the *intent*; the agent
owns *how it's built safely*. These guardrails keep "just make it do X" from quietly becoming a risky
change nobody reviewed.

## Guardrails

1. **Clarify intent before acting.** Turn the request into a goal, scope, and success criteria first;
   if any is unclear, ask in plain language — don't guess. See
   `rule://prompt-to-task-conversion` and `rule://ambiguity-resolution`.
2. **Smallest safe scope.** Make the minimal change that meets the goal. State an explicit out-of-scope
   line and never silently expand it.
3. **Never touch sensitive areas without an engineer.** Auth, payments, secrets, production data,
   migrations, and infrastructure are off-limits to a non-engineer-driven change — stop and bring in an
   engineer (these are at least **high** risk per `rule://risk-classification`).
4. **Always require tests + review.** No change ships without the project's test runner passing and a
   human review. Don't lower the quality bar because the driver isn't technical.
5. **Human approval before implementation.** Present the plan and get an explicit yes before editing —
   stay within `rule://autonomy-levels`; if the task needs more autonomy than granted, ask.
6. **Plain-language summaries.** Before and after, say in non-technical terms *what will change and why*,
   and *what to verify*. The driver must be able to confirm it's right without reading code.

## When to STOP and escalate

- The request reaches a sensitive area (rule 3), or risk classifies as high/restricted.
- Intent, scope, or "done" can't be made concrete after asking once.
- The safe change is larger than the driver expects, or needs a dependency, config, or data change.

When you stop, follow the escalation protocol in `rule://human-in-the-loop`: state the
decision, why it's a stop, the options with a recommendation, and what's safe to do meanwhile.

> Part of {{ provider.executable.cli }}'s organization capability layer (vibe-coding). Cross-refs
> `rule://prompt-to-task-conversion`, `rule://ambiguity-resolution`,
> `rule://autonomy-levels`, `rule://risk-classification`,
> `rule://human-in-the-loop`. The `prompt-to-safe-task` skill applies this rule interactively.
