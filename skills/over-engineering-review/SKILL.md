---
name: over-engineering-review
description: Scans code for over-engineering ONLY and returns a terse delete-list — what to cut and what replaces it — without applying any change. Use when the user asks "what can we delete", "is this over-engineered", "find the bloat", "lean review", "trim this", or wants a complexity-only pass over a diff or a whole repo. Complements (does not replace) the multi-axis code-review-and-quality skill, and stops short of the refactoring that code-simplification performs.
---

# Over-Engineering Review

> A single-lens scan inspired by the [ponytail](https://github.com/DietrichGebert/ponytail) plugin's
> review/audit commands. Adapted as a stack-agnostic, report-only skill. It is deliberately **narrow**:
> it hunts complexity and nothing else.

## What this is (and is not)

- **This skill:** one lens — over-engineering. Output is a **delete-list**: one line per finding,
  naming what to cut and the leaner replacement. It **reports; it does not edit**.
- **Not `code-review-and-quality`:** that is the full multi-axis gate (correctness, security,
  performance, architecture, readability) you run before merge. Use it for the real review. Use *this*
  when you want the complexity axis alone, in a scannable form, with no other noise.
- **Not `code-simplification`:** that skill *applies* the refactor and preserves behavior step by step.
  This skill produces the list; hand the list to `code-simplification` (or a developer) to execute.
- **Proactive twin — `mandatory-workflow.md` §2a.5:** this skill scans complexity *out* after code
  exists; the **Reuse & YAGNI Gate** (`.claude/rules/mandatory-workflow.md`, stage 2a.5) applies the
  same five lenses *before* code is written. Run the gate to avoid the bloat; run this skill to catch
  what slipped through.

## When to use

- "What can we delete from this?" / "Is this over-engineered?" / "Find the bloat."
- A pre-merge lean pass on a diff, before the full review.
- A periodic whole-repo audit for accreted complexity.

## Scope

- **Diff mode (default):** scan the current change (`git diff`, staged, or a PR). Prefix findings with
  the line; for multi-file diffs prefix with `file:line`.
- **Repo mode:** scan the whole tree. Rank findings biggest-cut-first.

State which mode you ran in one line at the top.

## The five tags

Every finding carries exactly one tag and names its replacement:

- `delete:` — dead code, unused flexibility, a speculative feature. Replacement: nothing.
- `stdlib:` — a hand-rolled thing the language's standard library already ships. Name the function.
- `native:` — a dependency or code doing what the platform already does (a built-in input type, a CSS
  feature, a DB constraint, a framework primitive). Name the feature.
- `yagni:` — an abstraction with one implementation, a config nobody sets, a layer with one caller,
  a factory with one product, a wrapper that only delegates.
- `shrink:` — same logic, fewer lines. Show the shorter form.

## What to hunt (repo mode checklist)

Dependencies the stdlib or platform already ships · single-implementation interfaces · factories with
one product · wrappers that only delegate · modules exporting one thing · dead flags and config ·
hand-rolled stdlib · speculative "for later" scaffolding.

## Burden of proof — scrutinize each addition

The five tags catch complexity that already exists. In **diff mode**, also invert the burden of proof
on what the change *adds* — LLM-written code is additive by default (it reinvents wheels, gilds error
handling, and abstracts for a single caller). **The default answer to "should we add this?" is no;
the addition must earn its place.** For each added file / function / abstraction / config / dependency,
ask:

1. **Priority** — does this serve the current task/spec, or is it a detour?
2. **Criticality** — is it needed *now*, or speculative "for later"?
3. **Simplicity** — does a simpler or subtractive solution exist?
4. **Evidence** — what proves it's needed (a failing test, a real requirement) rather than assumed?
5. **Consequence** — what concretely breaks if it's omitted?

If 4 and 5 can't be answered with evidence, the addition is unjustified. Watch for these **AI-additive
anti-patterns**:

| Anti-pattern | Signal | Challenge |
|---|---|---|
| Wheel reinvention | New helper overlapping existing code/stdlib | "Does X already do this?" |
| Hallucinated issue | A fix for a bug with no reproduction | "Show the failing test before the fix." |
| Test manipulation | Test changed to match new behavior, not the spec | "Did the spec change, or did you change the test?" |
| Complexity creep | Abstraction for a single use case | "Is this the 3rd use, or the 1st?" |
| Priority deviation | Work not traceable to the task/spec | "Which requirement does this serve?" |
| Gold plating | Error handling / flexibility beyond need | "What breaks without this?" |

Give each scrutinized addition a one-word verdict — **justified** (evidence supports it → keep),
**needs-evidence** (plausible but unproven → prove or cut), **unjustified** (no evidence, likely
additive bias → cut) — and fold the cuts into the delete-list below. Before accepting any addition,
ask the subtractive question: *could this be achieved by removing code instead of adding it?*

## Output format

One line per finding. Diff mode:

```
L<line>: <tag> <what>. <replacement>.
file:L<line>: <tag> <what>. <replacement>.   # multi-file
```

Repo mode, ranked biggest-cut-first:

```
<tag> <what to cut>. <replacement>. [path]
```

End with the only metric that matters:

- diff mode: `net: -<N> lines possible.`
- repo mode: `net: -<N> lines, -<M> deps possible.`

If there is nothing worth cutting, say `Lean already. Ship.` and stop. Do not invent findings to look
thorough — a clean report is a valid report.

### Examples (stack-neutral)

```
L12-38: stdlib: 27-line e-mail validator. An "@"/structure check is one line; real validation is the confirmation step.
L4:     native: a date-picker dependency for one field. The platform's built-in date input, 0 deps.
repo/store.*:L88: yagni: AbstractRepository with one implementation. Inline it until a second exists. [src/store]
L52-71: delete: retry wrapper around an idempotent local call. Nothing replaces it.
L30-44: shrink: manual loop building a map. The stdlib zip/dict constructor, 1 line.
net: -120 lines, -1 dep possible.
```

## Boundaries (do not over-cut)

- **Complexity only.** Correctness bugs, security holes, and performance go to a normal review pass
  (`code-review-and-quality`) — not this one. If you spot one, note it in a single line under a
  `# out of scope:` heading; don't fold it into the delete-list.
- **Never flag the required check.** This kit mandates a runnable test/verification for non-trivial
  logic (`.claude/rules/testing.md`, `quality-gates.md`). The smallest test that proves the logic is
  **not** bloat — never list it for deletion.
- **Never flag the carve-outs.** Input validation at trust boundaries, error handling that prevents
  data loss, security controls, and accessibility are not over-engineering. Leave them.
- **Report only.** This skill lists findings and applies nothing. Approving and executing the cuts is a
  separate, deliberate step (`code-simplification` for behavior-preserving edits).
