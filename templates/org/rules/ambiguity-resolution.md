# Ambiguity Resolution

When a request is unclear, the choice is **ask or assume** — and the wrong call is expensive either way:
a needless question stalls flow; a silent guess ships the wrong thing. This rule sets the line so agents
ask when it matters and proceed when it doesn't.

## Ask when

1. **The goal is unclear** — you can't state in one sentence what "done" means.
2. **The scope is unclear** — you don't know which areas it should (and should not) touch.
3. **Success is unmeasurable** — there's no test, check, or observable behavior that proves it works.
4. **Interpretations compete** — two or more readings would lead to materially different work.
5. **It's high-risk** — auth, payments, secrets, production data, migrations, or infrastructure are
   involved. Default to **asking** here even if you have a plausible default (`.claude/rules/risk-classification.md`).

## Assume when

- A sensible default exists, the cost of being wrong is low, and the work is easy to reverse. **State the
  assumption out loud and proceed** — don't manufacture a question for a choice you can safely make.

## Rules

- **Present competing interpretations; never silently pick one.** When readings diverge, lay out each
  option with its trade-off and your recommendation — let the human choose.
- **Record assumptions explicitly.** Surface every inference so a human can correct it before it hardens
  into shipped work. Never fabricate a missing requirement — reasoning cannot supply a fact you were
  never given.
- **Keep questions few and high-leverage.** Batch the smallest set that unblocks the most work; ask the
  question whose answer changes what you build, not trivia. One question at a time when extracting intent.
- **Bias to asking as risk rises.** A cheap question now beats an expensive wrong-direction unwind later;
  the higher the risk tier, the lower the bar for stopping.

> Part of claude-kit's organization capability layer (vibe-coding). Cross-refs
> `.claude/rules/prompt-to-task-conversion.md`, `.claude/rules/human-in-the-loop.md`,
> `.claude/rules/risk-classification.md`. The `interview-me` and `idea-refine` skills extract true intent
> one question at a time when a request is underspecified.
