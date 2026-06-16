---
name: bug-hunt
description: Proactively hunt for latent defects across a whole feature or module by reading its source and tracing data flow — no failing test, error, or bug report required. Use to discover bugs before they ship (edge cases, unhandled error paths, state/concurrency hazards, rendering glitches, authorization/scoping gaps), as distinct from debugging a known failure (debugging-and-error-recovery) or reviewing a specific diff (code-review-and-quality).
---

# Bug Hunt

## Overview

A **proactive, source-driven** search for bugs that have not surfaced yet. You are not fixing a
reported failure and you are not checking a feature against a spec — you are reading the
implementation as written, building a mental model of how data moves through it, and asking at every
step "what input, ordering, or state makes this go wrong?"

The output is a list of concrete, evidence-backed findings, each rated on the project's standard
severity model and each pointing at an exact location with a way to reproduce it.

This is the discovery counterpart to the kit's other quality skills. Use it when you want to find
*unknown* problems in code that currently "works."

## When to Use

- Before shipping a feature, to surface defects the happy-path tests never exercise.
- After a feature is built but before (or alongside) the formal review gates.
- When inheriting unfamiliar code and you need to know where it is fragile.
- When a class of bug keeps recurring and you want to sweep a module for siblings.

**When NOT to use:**
- A test is failing or an error is in front of you → `debugging-and-error-recovery` (reactive,
  single root cause).
- You are reviewing a specific change/diff → `code-review-and-quality` (change-scoped).
- You need to verify behavior against acceptance criteria on a running app → the `tester` /
  `senior-tester` lane.

## How It Differs

| Skill / agent | Trigger | Scope |
|---|---|---|
| **bug-hunt** (this) | proactive, nothing is broken yet | a whole feature/module, source-only |
| debugging-and-error-recovery | a known failure exists | one root cause |
| code-review-and-quality | a diff/PR is up | the changed lines |
| senior-tester / tester | acceptance criteria + running app | spec-bound verification |
| auditor | a runtime surface to probe | live behavior, not source reading |

## The Hunt

### Step 1 — Map the feature

Read the source for the target feature end to end before judging any single line. Produce a short
map:

- **Entry points** — the functions/handlers/routes/components a user or caller can reach.
- **Data flow** — how a value travels from entry point → transformation → storage/output, and back.
- **Boundaries** — every place the feature crosses a trust or process boundary (user input, network,
  storage, queue/worker, another service, the rendering layer).
- **State** — what is mutated, cached, shared, or persisted, and who else touches it.

You cannot find data-shape or ordering bugs without this map. Spend the time.

### Step 2 — Sweep the scenario taxonomy

For every entry point and boundary on the map, walk this fixed checklist. It is deliberately broad —
the point is coverage, so do not stop at the first finding in a category.

```
1. Input edge cases
   ├── empty / null / missing / default-only payloads
   ├── boundary values (0, negative, max, off-by-one, very large)
   ├── wrong type / malformed / unexpected extra fields
   └── unicode, whitespace, embedded quotes/markup, injection-shaped strings

2. An error state per failure point
   └── for EACH external call, parse, or computation that can fail:
       is the failure caught, surfaced, and recovered — or silently swallowed?
       (a bare catch that hides the error is itself a finding)

3. State management
   ├── stale reads / write-after-read / lost updates
   ├── cache invalidation gaps and shared-mutable state
   └── leaked state between requests, sessions, or test cases

4. Race / concurrency / ordering
   ├── two callers hit the same resource at once
   ├── async results arrive out of order or after teardown
   └── retries/duplicate delivery without idempotency

5. Rendering / display / output
   ├── empty, loading, error, and partial states actually handled
   ├── formatting of numbers/dates/currency/timezones
   └── pagination, truncation, and overflow

6. Authorization & scoping
   ├── can a caller act on data they do not own / outside their tenant?
   ├── missing ownership/permission check on a mutating path
   └── identifiers from the client trusted without re-checking access
```

For each suspicion, **confirm it in the source** before recording it. A hunch is not a finding;
a line of code that demonstrably mishandles the case is.

### Step 3 — Record each finding

One entry per finding, in severity order:

```
### [Severity] Short title
- **Where:** path/to/file.ext:LINE  (the exact site, not "somewhere in X")
- **What:** the incorrect behavior, stated concretely
- **Repro:** the input / ordering / state that triggers it
- **Why:** the root cause in the code (quote the offending lines)
- **Impact:** what a user or the system experiences
- **Fix direction:** the smallest correct change (a pointer, not a full patch)
```

Use the project's standard severity model — **Critical / High / Medium / Low / Cosmetic** (see
`.claude/rules/quality-gates.md`); do not invent a parallel scale. Calibrate by blast radius and
likelihood:

- **Critical** — data loss/corruption, auth bypass, or a crash on a common path.
- **High** — wrong result or unhandled failure on a realistic input.
- **Medium** — edge case that misbehaves; degraded but recoverable.
- **Low / Cosmetic** — minor display or robustness gap.

### Step 4 — Systemic pass

After the per-site sweep, step back: do the individual findings rhyme? A single missing null check
is a bug; the *same* missing check at five sites is a missing pattern (a shared guard, a validation
boundary, an error-handling convention). Record the pattern once, list its instances, and recommend
the systemic fix — it is worth more than the five line-fixes.

### Step 5 — Summarize

Close with:

- A count by severity.
- The **top 3 things to fix first**, chosen by impact × likelihood (not by how many there are).
- Any area you could not fully assess (so the gap is visible, not silently dropped — see
  `.claude/rules/quality-gates.md` §2.5 on evidence).

## Honesty & Evidence

- Every finding cites a real location and a real reproduction. No speculative "this might break."
- If you read a path and it is correct, say so — do not pad the count.
- Report what you did **not** cover. A bounded hunt that names its blind spots beats one that
  implies total coverage. See `.claude/rules/agent-guardrails.md` §2.

## Red Flags

- Findings with no `path:line` or no reproduction.
- Reporting style/lint nits as bugs (that is the linter's job).
- Stopping at the first finding per category instead of sweeping.
- Inflating severity to look thorough.
- Re-running this on a diff instead of using `code-review-and-quality`.

## Verification

- [ ] The feature map (entry points, data flow, boundaries, state) was written before judging lines.
- [ ] Every taxonomy category was swept for every entry point/boundary.
- [ ] Each finding has location + repro + root cause quoted from source.
- [ ] Findings are rated on the Critical/High/Medium/Low/Cosmetic model.
- [ ] A systemic pass grouped recurring findings into pattern-level fixes.
- [ ] The summary names the top 3 fixes and any uncovered area.

## See Also

- `debugging-and-error-recovery` — once a hunt finding (or any failure) needs root-causing and fixing.
- `code-review-and-quality` — change-scoped review of a specific diff.
- `senior-tester` / `tester` agents — spec-bound verification against a running app.
- `auditor` agent — runtime probing of a live surface.
