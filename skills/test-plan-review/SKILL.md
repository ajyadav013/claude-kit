---
name: test-plan-review
description: Review a proposed test plan or test-infrastructure design BEFORE the tests are written. Use when someone has drafted a testing strategy, fixture/factory approach, or coverage plan and you need to find weaknesses early — weak data generation, shallow validation, test-infra failure modes, missing layers — as distinct from verifying already-written tests on a running app (senior-tester) or writing tests yourself (test-driven-development).
---

# Test Plan Review

## Overview

A read-only critique of a **test plan or test-infrastructure design while it is still a document** —
before any test code exists. The cheapest place to catch a testing gap is in the plan: a fixture
strategy that will produce false passes, a validation approach that won't catch schema drift, or an
entire test layer nobody scoped. This skill interrogates the *design*, not the tests (there are
none yet).

Every finding ties a specific weakness in the plan to the concrete production incident it would let
through. "This is thin" is not a finding; "this fixture strategy passes even when the schema loses a
required field, so a breaking API change ships green" is.

## When to Use

- A test plan, coverage plan, or test-infra/fixture design has been drafted and needs review.
- You are about to invest in a test harness (factories, fixture generators, contract suites) and
  want the strategy stress-tested first.
- A team keeps shipping bugs the tests "should" have caught — review the *plan* that produced them.

**When NOT to use:**
- Tests already exist and run → `senior-tester` (verify executed tests against a running app) or
  the `tester` lane.
- You are writing the tests → `test-driven-development`, `unit-test`.
- You need coverage thresholds/standards → `.claude/rules/testing.md`.

## Review Lenses

Walk all five. Each names what to interrogate and the failure it prevents.

### 1. Data-generation strategy

How will test inputs be produced, and will they stay honest as the code evolves?

- **Source of fixtures:** hand-written literals · factories/builders · schema-derived · captured
  snapshots. Hand-written and snapshot fixtures **rot**: when the real data shape changes, they keep
  passing against the old shape.
- **The stale-fixture / stale-schema false pass:** if both the fixture and the validation are
  hand-maintained, a field can be added, renamed, or retyped in production while every test still
  passes. Ask: *when the data shape changes, what forces the fixtures to change with it?*
- **Variant coverage:** does the strategy generate nested structures, enums, nullable/optional
  fields, computed/derived fields, and the minimal vs maximal forms — or only the easy flat case?

### 2. Validation depth

When a test asserts on a result, how deeply does it actually check?

- **Recursive/strict vs top-level:** does validation reject unexpected, missing, or retyped fields
  anywhere in the structure, or only eyeball a couple of top-level keys?
- Apply the **drift matrix** — for the planned assertions, ask "would this catch it?" for each:

  | Change to the data | Caught by the plan? |
  |---|---|
  | a field **added** | |
  | a field **renamed** | |
  | a field **retyped** (e.g. number→string) | |
  | an **extra** unexpected field | |
  | an **enum value** changed/removed | |
  | a **nullable** flipped to required (or back) | |

  Any "no" is a finding.

### 3. Test-infra failure modes

The harness itself can fail or lie. Probe:

- Does the generator/factory **crash or skip silently** on a type it doesn't support?
- Can CI **race** the fixture/data generation (parallel workers, shared temp state)?
- Does a partially-completed run look the same as a clean one? (no canary / self-test)
- **Maintenance ownership:** when the schema changes, who updates the harness, and what breaks if
  they forget?

### 4. Coverage by domain & layer

- Map planned tests against the feature's domains/modules — which are unscoped entirely?
- Are whole **layers** missing (unit · contract/API · integration · end-to-end)? Name the absent
  layer, don't just note "could be more thorough."

### 5. Tie each gap to an incident

For every weakness above, state the concrete failure it would allow to reach production. This is what
makes the review actionable and prioritizable.

## Output Format

```
# Test Plan Review: [plan name]
> Verdict: Approve / Approve with fixes / Needs revision

## Gaps to Fix   (each blocks until resolved)
### [Severity] Title
- Weakness in the plan: …
- Incident it allows: …
- What to change: …  (concrete, not "consider improving")

## Improvements Worth Considering   (non-blocking)
- …

## Coverage Map
| Domain / layer | Planned? | Gap |
```

Rate findings on the project's standard severity model — **Critical / High / Medium / Low /
Cosmetic** (`.claude/rules/quality-gates.md`). Keep "Gaps to Fix" and "Improvements" strictly
separate; never blur a must-fix with a nice-to-have. Be specific — no softening language.

## Red Flags

- Vague feedback ("testing could be more thorough") with no incident tied to it.
- Reviewing test *code* here instead of the *plan* (that's `senior-tester` / `code-review-and-quality`).
- Accepting a hand-fixture + hand-validation plan without flagging the false-pass trap.
- Skipping the drift matrix because the plan "looks fine."

## Verification

- [ ] All five lenses applied to the plan.
- [ ] The drift matrix was filled in; every "no" became a finding.
- [ ] Each gap names the production incident it would allow.
- [ ] A coverage map shows which domains/layers are unscoped.
- [ ] Gaps-to-fix and improvements are in separate sections with explicit severities.

## See Also

- `senior-tester` agent — verifies already-executed tests against a running app (post-implementation).
- `test-driven-development`, `unit-test` — writing the tests.
- `.claude/rules/testing.md` — coverage thresholds and per-test standards.
