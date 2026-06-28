# Agent Resilience

**Every retry is bounded; every recovery tells the truth about what's left.**

How the **agent machinery itself** behaves when something goes wrong: a tool errors, a command fails,
a sub-agent returns empty or malformed output, an external service is down or rate-limited, a network
call times out. The book's thesis is that production-grade agents must be treated as **complex
software** — with the same fault-tolerance, state management, and recovery discipline that has
governed traditional systems for decades.

> Adapted from *Agentic Design Patterns* (A. Gulli), Ch. 12 "Exception Handling and Recovery" (and the
> "treat agents as software" thesis of Ch. 18). Concepts paraphrased for this kit.

This is **distinct** from three neighbors:
- `.claude/rules/quality-gates.md` owns *gate* retry **budgets** (a review/test failing on its merits
  and looping the lane). This rule is about *operational* failures of the tooling, not failed verdicts.
- The `debugging-and-error-recovery` skill finds the root cause of a bug in the **product**. This rule
  is about the **agent's own run** surviving a transient or hard failure.
- `.claude/rules/resilience-engineering.md` applies the same vocabulary (circuit-breaker, fallback,
  backpressure, graceful degradation) to the **product's services** — how the system you build survives
  *its* dependencies. This rule is the **agent machinery**; that rule is the **shipped system**.

## When an operation fails

```
Operation fails
  transient? (timeout, rate limit, flaky network, locked resource)
    └─ retry with backoff, up to a small bounded limit (e.g. 3)
        └─ still failing → open the circuit: stop retrying this path
  deterministic? (bad args, missing file, auth denied, malformed output)
    └─ do NOT retry the same way — it will fail identically
        └─ try a fallback, or escalate
  blocked entirely?
    └─ degrade gracefully (deliver partial value) and/or escalate to a human
```

## The techniques

| Technique | Apply when | Discipline |
|-----------|-----------|-----------|
| **Bounded retry + backoff** | Transient failure (timeout, rate-limit, flake) | Cap retries (≈3). Space them out. Retrying forever is a hang, not resilience. |
| **No blind retry of deterministic failures** | Bad input, missing dependency, auth denied | The same call fails the same way. Change something or escalate — don't loop. |
| **Fallback** | A primary tool/source/path is unavailable | Have a defined alternative (another source, a simpler method, manual steps) and say you used it. |
| **Circuit-breaker** | Repeated failures on one path | Stop hammering it after the budget; mark it down and move on or escalate, so one broken path doesn't stall everything. |
| **Graceful degradation** | Can't fully succeed | Deliver the part that works + a clear statement of what's missing and why — never a fake "done." |
| **Idempotency awareness** | Before retrying a side-effecting action | Re-running a commit/write/deploy/API-POST can double-apply. Check state first; make the retry safe. |
| **Checkpointing** | Long runs, before risky steps, pre-compaction | Write `.claude/CONTINUITY.md` so a crash/compaction resumes from the last good state, not from zero. See `.claude/rules/continuity.md`. |

## Fix-attempt discipline (the 3-strike rule)

Bounded retry applies to *fixes*, too. Three failed attempts at the same failure is not a
fourth-attempt problem — it is a signal that you do not yet understand the root cause, or the design
is wrong. Retrying variations of the same fix is the deterministic-failure trap above wearing a
disguise.

- **Attempts 1–2** — allowed, but each must test a *different, explicit* hypothesis, changing one
  variable at a time. The same edit retried (or a near-duplicate) does not count as a new attempt.
- **At the 3rd failed attempt — STOP.** Do not attempt a fourth blind fix. Switch modes: re-derive
  the root cause from first principles (`.claude/skills/debugging-and-error-recovery/SKILL.md`), and
  ask the harder question — is the *approach or architecture* wrong, not the line?
- **Then escalate** (`.claude/rules/human-in-the-loop.md`) with what you tried, what each attempt
  ruled out, and the hypothesis you cannot resolve — not just "it still fails."

This bounds *blind fix attempts within a single issue*; the defect-loop **budget** in
`.claude/rules/quality-gates.md` bounds how many times a finding may cycle review→fix across the
pipeline. Different scopes, same principle: no loop is unbounded.

## Rules

1. **Fail loud, never silent.** A swallowed error that lets work continue on bad state is worse than a
   stop. Surface what failed, what you tried, and the current state. (Blanket error suppression to
   hide a failure is an auto-Critical in `.claude/rules/quality-gates.md`.)
2. **Bounded everything.** Every retry/recovery loop has a limit. Exhausting it routes to a human
   (`.claude/rules/human-in-the-loop.md`), it does not spin.
3. **Truthful state after recovery.** If you fell back or degraded, CONTINUITY and your handoff say so
   — never report full success for a partial result.
4. **Promote recurring failures.** A failure mode worth avoiding next time goes to `agent-memory/` via
   `remember`.

**Self-check before retrying or handing off:** does every loop I'm in have a limit, and does my
reported state match what actually happened (no silent swallow, no fake "done")?

**This rule is working if** no run hangs in an unbounded loop, every fallback or degradation is stated
truthfully in the handoff, and a crash or compaction resumes from the last checkpoint rather than from
zero.

## Relationship to other rules

- **`.claude/rules/continuity.md`** — the checkpoint that makes resume-after-failure possible.
- **`.claude/rules/agent-guardrails.md`** — malformed/hostile input is both a guardrail and a
  resilience event; handle the validation there, the recovery here.
- **`.claude/rules/human-in-the-loop.md`** — the escalation target when recovery budgets are exhausted.
