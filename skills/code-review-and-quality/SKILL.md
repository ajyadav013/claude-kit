---
name: code-review-and-quality
description: Multi-axis code review (correctness, security, performance, design) before merging any change. Use to assess quality; not to refactor (use code-simplification) or hunt complexity only (use over-engineering-review).
---

# Code Review and Quality

## Overview

Multi-dimensional code review with quality gates. Every change gets reviewed before merge — no exceptions. Review covers five axes: correctness, readability, architecture, security, and performance.

**The approval standard:** Approve a change when it definitely improves overall code health, even if it isn't perfect. Perfect code doesn't exist — the goal is continuous improvement. Don't block a change because it isn't exactly how you would have written it. If it improves the codebase and follows the project's conventions, approve it.

## When to Use

- Before merging any PR or change
- After completing a feature implementation
- When another agent or model produced code you need to evaluate
- When refactoring existing code
- After any bug fix (review both the fix and the regression test)

## The Five-Axis Review

Every review evaluates code across these dimensions:

### 1. Correctness

Does the code do what it claims to do?

- Does it match the spec or task requirements?
- Are edge cases handled (null, empty, boundary values)?
- Are error paths handled (not just the happy path)?
- Does it pass all tests? Are the tests actually testing the right things?
- Are there off-by-one errors, race conditions, or state inconsistencies?

### 2. Readability & Simplicity

Can another engineer (or agent) understand this code without the author explaining it?

- Are names descriptive and consistent with project conventions? (No `temp`, `data`, `result` without context)
- Is the control flow straightforward (avoid nested ternaries, deep callbacks)?
- Is the code organized logically (related code grouped, clear module boundaries)?
- Are there any "clever" tricks that should be simplified?
- **Could this be done in fewer lines?** (1000 lines where 100 suffice is a failure)
- **Are abstractions earning their complexity?** (Don't generalize until the third use case)
- Would comments help clarify non-obvious intent? (But don't comment obvious code.)
- Are there dead code artifacts: no-op variables (`_unused`), backwards-compat shims, or `// removed` comments?

**If you cannot understand it, that *is* the finding.** When a reviewer genuinely can't follow what a
piece of code does after a fair effort, do not approve it and do not wave it through with a guess — the
incomprehensibility is itself a defect, because code the next reader (human or agent) can't understand
can't be safely changed or debugged later. "I don't understand this — please clarify or simplify" is a
legitimate, blocking review comment, not an admission of reviewer inadequacy; the burden is on the
author to make the code understandable, not on the reviewer to decode it. (This is also a signal the
code may be too complex — see `over-engineering-review`.)

> Per Google's Code Review Developer Guide (google.github.io/eng-practices) — if a reviewer doesn't
> understand a change, it is likely too complex, and the reviewer should ask for clarification or
> simplification rather than approve.

### 3. Architecture

Does the change fit the system's design?

- Does it follow existing patterns or introduce a new one? If new, is it justified?
- Does it maintain clean module boundaries?
- Is there code duplication that should be shared?
- Are dependencies flowing in the right direction (no circular dependencies)?
- Is the abstraction level appropriate (not over-engineered, not too coupled)?

### 4. Security

For detailed security guidance, see `security-and-hardening`. Does the change introduce vulnerabilities?

- Is user input validated and sanitized?
- Are secrets kept out of code, logs, and version control?
- Is authentication/authorization checked where needed?
- Are database queries parameterized (no string concatenation)?
- Are outputs encoded to prevent XSS?
- Are dependencies from trusted sources with no known vulnerabilities?
- Is data from external sources (APIs, logs, user content, config files) treated as untrusted?
- Are external data flows validated at system boundaries before use in logic or rendering?

### 5. Performance

For detailed profiling and optimization, see `performance-optimization`. Does the change introduce performance problems?

- Any N+1 query patterns?
- Any unbounded loops or unconstrained data fetching?
- Any blocking operations in async contexts?
- Any unnecessary re-renders in UI components?
- Any missing pagination on list endpoints?
- Any large objects created in hot paths?

## Cover Every Changed File: Partition, Plan, Then Weight Depth

On a large changeset the signature failure of an AI reviewer is **silently skipping files** —
reviewing a plausible subset while implying the whole. Coverage is a *mechanical* property: guarantee
it with engineering, not model discretion, **before** deciding where to spend depth (next section).

- **Enumerate deterministically.** Take the changed-file list from the diff itself and treat it as the
  checklist of record — every file is reviewed or explicitly marked out-of-scope with a reason. The
  model never decides which files "seem worth" looking at.
  ```bash
  git diff --name-only <base>...<head>   # the coverage checklist — nothing falls off it
  ```
- **Bundle related files into one review unit.** Group files that must be understood together — a
  function and its tests, an interface and its implementations, paired translation/config files
  (`messages.en.json` + `messages.zh.json`), a schema and its migration. A bundle reviewed as a unit
  catches cross-file contract breaks that a one-file-at-a-time pass misses.
- **Review each bundle in isolated context, concurrently.** Give each bundle its own focused context
  (its own sub-agent/lane) instead of streaming the whole changeset through one window —
  divide-and-conquer keeps quality stable on very large changes and parallelizes naturally (the
  `.claude/rules/mandatory-workflow.md` lane model, within the Brooks's-law caution in
  `.claude/rules/tool-design.md` §7). Context gathered for one bundle is for *understanding only* — a
  discovery in file B doesn't become a comment on the unrelated file A.
- **Plan before the deep pass on a big diff.** For a large change, first emit a one-paragraph change
  summary plus risk points ranked high→low and the context each needs, then review against that plan.
  A cheap planning pass beats diving in file-by-file blind.
- **Reconcile at the end.** Merge the per-bundle findings and confirm every file on the enumerated list
  got a verdict. **Coverage = every file accounted for; depth = how hard you looked, allocated next.**

> Partition-for-coverage (deterministic file selection, related-file bundling, isolated-context
> concurrent review, plan-phase for large diffs) is a stack-agnostic adaptation of the hybrid
> architecture in the Apache-2.0
> [`alibaba/open-code-review`](https://github.com/alibaba/open-code-review) — engineering guarantees
> coverage, the model supplies judgment. Re-derived in prose; not vendored.

## Where to Focus: Change Hotspots & Coupling

Once every changed file is accounted for (above), allocate *depth* — you can't give every line equal
attention; on a large change or an unfamiliar codebase, spend the most scrutiny where defects actually
cluster. The project's own git history surfaces this for free, no special tooling required:

- **Hotspots (churn × complexity).** Files that change *often* **and** are *large/complex* carry the most risk. List the frequently-changed files and weight review toward the complex ones among them — a rarely-touched file is usually stable, while a hotspot edited in *this* change deserves extra correctness and test scrutiny.
  ```bash
  # Most-churned files over the last 6 months — pair the top hits with their size/complexity
  git log --since="6 months ago" --name-only --pretty=format: | sort | uniq -c | sort -rn | head -20
  ```
  Use the project's own complexity tooling if it has one; file size is only a rough proxy for complexity.
- **Co-change coupling (hidden dependencies).** Files historically committed together often share an implicit contract. If this change touches one side of a known pair but not the other, ask whether the coupled file also needs updating — `git log` on a changed file reveals what usually moves with it.
- **Single-owner / bus-factor files.** Code with one dominant author has had fewer eyes. Treat changes there with extra care and prefer a second reviewer.

These are deterministic signals an agent can derive from `git log` alone. If a codebase-intelligence MCP server is configured (e.g. the optional **repowise** server in the catalog), its `get_risk` / `get_health` tools surface the same hotspot, coupling, and change-risk signals precomputed — use them when available, but treat the output as **advisory input to your judgment, never a blocking gate**.

## Change Sizing

Small, focused changes are easier to review, faster to merge, and safer to deploy. Target these sizes:

```
~100 lines changed   → Good. Reviewable in one sitting.
~300 lines changed   → Acceptable if it's a single logical change.
~1000 lines changed  → Too large. Split it.
```

**Count *quantified* lines, not raw diff lines.** A raw `+N/-M` overstates review burden — a thousand
lines of regenerated lockfile or a vendored snapshot is not a thousand lines to *read*. Before judging a
change against the thresholds above, normalize:

- **Exclude what needs no line-by-line review** — generated/auto-formatted output, lockfiles, vendored
  code, large fixtures/snapshots, pure moves/renames. Verify these by *intent*, not by line (see "When
  large changes are acceptable").
- **Weight by reviewability, not character count** — whitespace, import reordering, and comment-only
  edits cost little attention; new branching logic costs a lot. Two diffs with the same `+/-` can be a
  10-minute review and a 2-hour one.
- **Calibrate "large" to the repo, not an absolute** — the same line count is routine in one codebase
  and alarming in another; read the thresholds as percentiles of *this* project's typical change.

The point is to size by **how much a reviewer must actually reason about**, so the split decision
tracks real review load rather than a misleading raw number.

> The quantified-lines methodology (exclude generated/whitespace/comment lines, weight by reviewability,
> calibrate to repository context) is a stack-agnostic adaptation of the MIT
> [`microsoft/PullRequestQuantifier`](https://github.com/microsoft/PullRequestQuantifier). Re-derived in
> prose; not vendored.

**What counts as "one change":** A single self-contained modification that addresses one thing, includes related tests, and keeps the system functional after submission. One part of a feature — not the whole feature.

**Splitting strategies when a change is too large:**

| Strategy | How | When |
|----------|-----|------|
| **Stack** | Submit a small change, start the next one based on it | Sequential dependencies |
| **By file group** | Separate changes for groups needing different reviewers | Cross-cutting concerns |
| **Horizontal** | Create shared code/stubs first, then consumers | Layered architecture |
| **Vertical** | Break into smaller full-stack slices of the feature | Feature work |

**When large changes are acceptable:** Complete file deletions and automated refactoring where the reviewer only needs to verify intent, not every line.

**Separate refactoring from feature work.** A change that refactors existing code and adds new behavior is two changes — submit them separately. Small cleanups (variable renaming) can be included at reviewer discretion.

## Change Descriptions

Every change needs a description that stands alone in version control history.

**First line:** Short, imperative, standalone. "Delete the FizzBuzz RPC" not "Deleting the FizzBuzz RPC." Must be informative enough that someone searching history can understand the change without reading the diff.

**Body:** What is changing and why. Include context, decisions, and reasoning not visible in the code itself. Link to bug numbers, benchmark results, or design docs where relevant. Acknowledge approach shortcomings when they exist.

**Anti-patterns:** "Fix bug," "Fix build," "Add patch," "Moving code from A to B," "Phase 1," "Add convenience functions."

## Review Process

### Step 1: Understand the Context

Before looking at code, understand the intent:

```
- What is this change trying to accomplish?
- What spec or task does it implement?
- What is the expected behavior change?
```

### Step 2: Review the Tests First

Tests reveal intent and coverage:

```
- Do tests exist for the change?
- Do they test behavior (not implementation details)?
- Are edge cases covered?
- Do tests have descriptive names?
- Would the tests catch a regression if the code changed?
```

### Step 3: Review the Implementation

Walk through the code with the five axes in mind:

```
For each file changed:
1. Correctness: Does this code do what the test says it should?
2. Readability: Can I understand this without help?
3. Architecture: Does this fit the system?
4. Security: Any vulnerabilities?
5. Performance: Any bottlenecks?
```

### Step 4: Categorize Findings

Label every comment with its severity so the author knows what's required vs optional:

| Prefix | Meaning | Author Action |
|--------|---------|---------------|
| *(no prefix)* | Required change | Must address before merge |
| **Critical:** | Blocks merge | Security vulnerability, data loss, broken functionality |
| **Nit:** | Minor, optional | Author may ignore — formatting, style preferences |
| **Optional:** / **Consider:** | Suggestion | Worth considering but not required |
| **FYI** | Informational only | No action needed — context for future reference |

This prevents authors from treating all feedback as mandatory and wasting time on optional suggestions.

#### Every finding must be grounded

A review finding is a **claim about a specific place in the code**, so it must be falsifiable — a
citation a second pass (human or agent) can mechanically re-read and confirm. AI reviewers in
particular hallucinate locations and issues; grounding is what stops that.

Every finding carries:

- **Location** — `file:line` (a concrete, current line, not "somewhere in the auth module").
- **Anchor** — a short *verbatim* snippet copied from that line, so the citation can be re-verified by
  matching text even if line numbers shift.

Verify before reporting: re-read each cited `file:line` and confirm the anchor text is actually
present. A finding whose location or anchor doesn't resolve is **dropped or labelled `UNVERIFIED`** —
it never enters the verdict. This is the review-level form of the evidence rule in
`.claude/rules/quality-gates.md` (§2.5): an uncited finding is a TODO, not a finding.

### Step 5: Verify the Verification

Check the author's verification story:

```
- What tests were run?
- Did the build pass?
- Was the change tested manually?
- Are there screenshots for UI changes?
- Is there a before/after comparison?
```

## Multi-Model Review Pattern

Use different models for different review perspectives:

```
Model A writes the code
    │
    ▼
Model B reviews for correctness and architecture
    │
    ▼
Model A addresses the feedback
    │
    ▼
Human makes the final call
```

This catches issues that a single model might miss — different models have different blind spots.

**Example prompt for a review agent:**
```
Review this code change for correctness, security, and adherence to
our project conventions. The spec says [X]. The change should [Y].
Flag any issues as Critical, Important, or Suggestion.
```

## Dead Code Hygiene

After any refactoring or implementation change, check for orphaned code:

1. Identify code that is now unreachable or unused
2. List it explicitly
3. **Ask before deleting:** "Should I remove these now-unused elements: [list]?"

Don't leave dead code lying around — it confuses future readers and agents. But don't silently delete things you're not sure about. When in doubt, ask.

```
DEAD CODE IDENTIFIED:
- formatLegacyDate() in src/utils/date.ts — replaced by formatDate()
- OldTaskCard component in src/components/ — replaced by TaskCard
- LEGACY_API_URL constant in src/config.ts — no remaining references
→ Safe to remove these?
```

## Review Speed

Slow reviews block entire teams. The cost of context-switching to review is less than the waiting cost imposed on others.

- **Respond within one business day** — this is the maximum, not the target
- **Ideal cadence:** Respond shortly after a review request arrives, unless deep in focused coding. A typical change should complete multiple review rounds in a single day
- **Prioritize fast individual responses** over quick final approval. Quick feedback reduces frustration even if multiple rounds are needed
- **Large changes:** Ask the author to split them rather than reviewing one massive changeset

## Handling Disagreements

When resolving review disputes, apply this hierarchy:

1. **Technical facts and data** override opinions and preferences
2. **Style guides** are the absolute authority on style matters
3. **Software design** must be evaluated on engineering principles, not personal preference
4. **Codebase consistency** is acceptable if it doesn't degrade overall health

**Don't accept "I'll clean it up later."** Experience shows deferred cleanup rarely happens. Require cleanup before submission unless it's a genuine emergency. If surrounding issues can't be addressed in this change, require filing a bug with self-assignment.

## Honesty in Review

When reviewing code — whether written by you, another agent, or a human:

- **Don't rubber-stamp.** "LGTM" without evidence of review helps no one.
- **Don't soften real issues.** "This might be a minor concern" when it's a bug that will hit production is dishonest.
- **Quantify problems when possible.** "This N+1 query will add ~50ms per item in the list" is better than "this could be slow."
- **Push back on approaches with clear problems.** Sycophancy is a failure mode in reviews. If the implementation has issues, say so directly and propose alternatives.
- **Accept override gracefully.** If the author has full context and disagrees, defer to their judgment. Comment on code, not people — reframe personal critiques to focus on the code itself.

## Dependency Discipline

Part of code review is dependency review:

**Before adding any dependency:**
1. Does the existing stack solve this? (Often it does.)
2. How large is the dependency? (Check bundle/binary impact.)
3. Is it actively maintained? (Check last commit, open issues.)
4. Does it have known vulnerabilities? (Use the project's security scanner.)
5. What's the license? (Must be compatible with the project.)

**Rule:** Prefer standard library and existing utilities over new dependencies. Every dependency is a liability.

For a full pre-add evaluation of a specific candidate (maintenance/bus-factor, license, supply-chain history, transitive weight, lock-in, adopt/reject decision), use the `library-review` skill — this 5-point list is its quick form.

## The Review Checklist

```markdown
## Review: [PR/Change title]

### Context
- [ ] I understand what this change does and why
- [ ] Every changed file is accounted for — reviewed or explicitly marked out-of-scope (no silent skips)
- [ ] For a large/unfamiliar change, I focused review on the riskiest files (hotspots, coupled files)

### Correctness
- [ ] Change matches spec/task requirements
- [ ] Edge cases handled
- [ ] Error paths handled
- [ ] Tests cover the change adequately

### Readability
- [ ] Names are clear and consistent
- [ ] Logic is straightforward
- [ ] No unnecessary complexity

### Architecture
- [ ] Follows existing patterns
- [ ] No unnecessary coupling or dependencies
- [ ] Appropriate abstraction level

### Security
- [ ] No secrets in code
- [ ] Input validated at boundaries
- [ ] No injection vulnerabilities
- [ ] Auth checks in place
- [ ] External data sources treated as untrusted

### Performance
- [ ] No N+1 patterns
- [ ] No unbounded operations
- [ ] Pagination on list endpoints

### Verification
- [ ] Tests pass
- [ ] Build succeeds
- [ ] Manual verification done (if applicable)

### Verdict
- [ ] **Approve** — Ready to merge
- [ ] **Request changes** — Issues must be addressed
```
## See Also

- For detailed security review guidance, see `.claude/skills/_references/security-checklist.md`
- For performance review checks, see `.claude/skills/_references/performance-checklist.md`

## Common Rationalizations

| Rationalization | Reality |
|---|---|
| "It works, that's good enough" | Working code that's unreadable, insecure, or architecturally wrong creates debt that compounds. |
| "I wrote it, so I know it's correct" | Authors are blind to their own assumptions. Every change benefits from another set of eyes. |
| "We'll clean it up later" | Later never comes. The review is the quality gate — use it. Require cleanup before merge, not after. |
| "AI-generated code is probably fine" | AI code needs more scrutiny, not less. It's confident and plausible, even when wrong. |
| "The tests pass, so it's good" | Tests are necessary but not sufficient. They don't catch architecture problems, security issues, or readability concerns. |

## Red Flags

- PRs merged without any review
- Review that only checks if tests pass (ignoring other axes)
- "LGTM" without evidence of actual review
- Security-sensitive changes without security-focused review
- Large PRs that are "too big to review properly" (split them)
- No regression tests with bug fix PRs
- Review comments without severity labels — makes it unclear what's required vs optional
- Accepting "I'll fix it later" — it never happens

## Verification

After review is complete:

- [ ] All Critical issues are resolved
- [ ] All Important issues are resolved or explicitly deferred with justification
- [ ] Tests pass
- [ ] Build succeeds
- [ ] The verification story is documented (what changed, how it was verified)
