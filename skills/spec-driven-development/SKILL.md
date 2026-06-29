---
name: spec-driven-development
description: Creates specs before coding. Use when starting a new project/feature with unclear or ambiguous requirements. NOT when a spec exists and you're ready to implement (use test-driven-development).
---

# Spec-Driven Development

## Overview

Write a structured specification before writing any code. The spec is the shared source of truth between you and the human engineer — it defines what we're building, why, and how we'll know it's done. Code without a spec is guessing.

## When to Use

- Starting a new project or feature
- Requirements are ambiguous or incomplete
- The change touches multiple files or modules
- You're about to make an architectural decision
- The task would take more than 30 minutes to implement

**When NOT to use:** Single-line fixes, typo corrections, or changes where requirements are unambiguous and self-contained.

**Full spec vs delta spec.** A brand-new project or feature gets a full spec (the `feature-spec.md` template). An *incremental change to a system that already has a spec* — modify existing behavior, add one route, deprecate a field — gets a **delta change-proposal** instead: capture only the `ADDED` / `MODIFIED` / `REMOVED` requirements against the base spec's stable ids, not a full rewrite. Use the `change-proposal.md` template (`.claude/templates/change-proposal.md`). It keeps the base spec authoritative, makes the diff reviewable, and still feeds the stage-1f coverage gate (every new or changed acceptance criterion maps to a story). Externally-exposed API contract deltas additionally get an `api-change-report.md`.

**A third mode for major changes — the RFC track (see below).** When a change introduces or breaks a **public API / cross-service contract**, or is large and cross-cutting enough that getting the *interface* wrong is expensive to undo, a full or delta spec isn't enough governance. Run the heavier-weight **RFC process** instead.

## RFC track for major / cross-cutting changes

Some changes are **one-way doors**: a public API, a wire/schema contract, a shared library's surface, or an architectural commitment that downstream consumers will build on and that is costly to reverse once shipped. For these, escalate from a spec to a structured **RFC (Request for Comments)** so the interface is debated and signed off *before* implementation — not discovered in code review.

The RFC track adds four things on top of a normal spec:

1. **Work backwards from the result.** Before designing the mechanism, write the artifacts as if the feature already shipped: the future **CHANGELOG entry**, the **README/usage docs** a consumer would read, and a short "press release" of the user-visible win. If you can't write a crisp, compelling "after," the change isn't ready to design — and the working-backwards docs *become* the acceptance target.
2. **A designated API reviewer ("bar raiser") with veto over the interface.** Name one reviewer — independent of the author — who is accountable for the **public-interface quality** specifically (naming, consistency, extensibility, backward-compatibility) and can block on interface grounds alone. This is distinct from the EM/architecture review of the *plan*; it guards the *contract*.
3. **A multi-stage lifecycle with explicit gates.** Track the RFC through states, each a gate that must close before the next opens:
   `proposed → feedback period (open comment) → final-comment period (last call, default-accept) → API sign-off → implementation planning → implementing → shipped`.
   Record the current state in the RFC document (and link it from `CONTINUITY.md`); a stalled RFC is visible, not silently abandoned.
4. **Separate API approval from implementation approval.** The interface is signed off (gate 4) *before* the implementation plan is built (gate 5). Approving *what the contract is* is a different decision from approving *how/when it's built* — conflating them is how bad interfaces ship under schedule pressure.

**When to use the RFC track (vs. a plain spec):** a new or changed **public/cross-service API**, a data/wire format other teams depend on, a shared-library surface, a security/privacy-relevant contract, or any architectural one-way door. **When NOT to:** internal-only changes behind a stable interface, anything a delta change-proposal already covers — don't bureaucratize a two-file change. The RFC is the proposal artifact; once API sign-off lands, implementation still follows the gated workflow below.

> Stack-agnostic adaptation of a formal RFC process (working-backwards artifacts, a designated API "bar raiser" with interface veto, a staged feedback → final-comment → API-sign-off lifecycle, and API approval separated from implementation approval) from the Apache-2.0 [`aws/aws-cdk-rfcs`](https://github.com/aws/aws-cdk-rfcs). Re-derived in prose; not vendored — the process is about review governance, independent of any language or framework.

## The Gated Workflow

Spec-driven development has four phases. Do not advance to the next phase until the current one is validated.

```
SPECIFY ──→ PLAN ──→ TASKS ──→ IMPLEMENT
   │          │        │          │
   ▼          ▼        ▼          ▼
 Human      Human    Human      Human
 reviews    reviews  reviews    reviews
```

### Phase 1: Specify

Start with a high-level vision. Ask the human clarifying questions until requirements are concrete.

**Surface assumptions immediately.** Before writing any spec content, list what you're assuming:

```
ASSUMPTIONS I'M MAKING:
1. This is a web application (not native mobile)
2. Authentication uses session-based cookies (not token-based)
3. The database is relational (based on existing schema)
4. We're targeting modern clients only
→ Correct me now or I'll proceed with these.
```

Don't silently fill in ambiguous requirements. The spec's entire purpose is to surface misunderstandings *before* code gets written — assumptions are the most dangerous form of misunderstanding.

**Write a spec document covering these six core areas:**

1. **Objective** — What are we building and why? Who is the user? What does success look like?

2. **Commands** — Full executable commands with flags, not just tool names.
   ```
   Build: <project's build command>
   Test: <project's test runner command with flags>
   Lint: <project's linter command with auto-fix>
   Dev: <project's dev server command>
   ```

3. **Project Structure** — Where source code lives, where tests go, where docs belong.
   ```
   src/           → Application source code
   src/components → UI components
   src/lib        → Shared utilities
   tests/         → Unit and integration tests
   e2e/           → End-to-end tests
   docs/          → Documentation
   ```

4. **Code Style** — One real code snippet showing your style beats three paragraphs describing it. Include naming conventions, formatting rules, and examples of good output.

5. **Testing Strategy** — What framework, where tests live, coverage expectations, which test levels for which concerns.

6. **Boundaries** — Three-tier system:
   - **Always do:** Run tests before commits, follow naming conventions, validate inputs
   - **Ask first:** Database schema changes, adding dependencies, changing CI config
   - **Never do:** Commit secrets, edit vendor directories, remove failing tests without approval

**Spec template:**

```markdown
# Spec: [Project/Feature Name]

## Objective
[What we're building and why. User stories or acceptance criteria.]

## Tech Stack
[Framework, language, key dependencies with versions]

## Commands
[Build, test, lint, dev — full commands]

## Project Structure
[Directory layout with descriptions]

## Code Style
[Example snippet + key conventions]

## Testing Strategy
[Framework, test locations, coverage requirements, test levels]

## Boundaries
- Always: [...]
- Ask first: [...]
- Never: [...]

## Success Criteria
[How we'll know this is done — specific, testable conditions]

## Open Questions
[Anything unresolved that needs human input]
```

**Reframe instructions as success criteria.** When receiving vague requirements, translate them into concrete conditions:

```
REQUIREMENT: "Make the dashboard faster"

REFRAMED SUCCESS CRITERIA:
- Dashboard LCP < 2.5s on 4G connection
- Initial data load completes in < 500ms
- No layout shift during load (CLS < 0.1)
→ Are these the right targets?
```

This lets you loop, retry, and problem-solve toward a clear goal rather than guessing what "faster" means.

### Phase 2: Plan

With the validated spec, generate a technical implementation plan:

1. Identify the major components and their dependencies
2. Determine the implementation order (what must be built first)
3. Note risks and mitigation strategies
4. Identify what can be built in parallel vs. what must be sequential
5. Define verification checkpoints between phases

The plan should be reviewable: the human should be able to read it and say "yes, that's the right approach" or "no, change X."

### Phase 3: Tasks

Break the plan into discrete, implementable tasks:

- Each task should be completable in a single focused session
- Each task has explicit acceptance criteria
- Each task includes a verification step (test, build, manual check)
- Tasks are ordered by dependency, not by perceived importance
- No task should require changing more than ~5 files

**Task template:**
```markdown
- [ ] Task: [Description]
  - Acceptance: [What must be true when done]
  - Verify: [How to confirm — test command, build, manual check]
  - Files: [Which files will be touched]
```

### Phase 4: Implement

Execute tasks one at a time following `skills/incremental-implementation/SKILL.md` (`incremental-implementation`) and `skills/test-driven-development/SKILL.md` (`test-driven-development`). Use `skills/context-engineering/SKILL.md` (`context-engineering`) to load the right spec sections and source files at each step rather than flooding the agent with the entire spec.

## Keeping the Spec Alive

The spec is a living document, not a one-time artifact:

- **Update when decisions change** — If you discover the data model needs to change, update the spec first, then implement.
- **Update when scope changes** — Features added or cut should be reflected in the spec.
- **Capture substantial changes as a delta, not a rewrite** — once a spec exists, a later change to that system is a `change-proposal.md` (ADDED/MODIFIED/REMOVED against the base R-ids), keeping history legible and the base spec authoritative rather than overwriting it.
- **Commit the spec** — The spec belongs in version control alongside the code.
- **Reference the spec in PRs** — Link back to the spec section that each PR implements.

## Common Rationalizations

| Rationalization | Reality |
|---|---|
| "This is simple, I don't need a spec" | Simple tasks don't need *long* specs, but they still need acceptance criteria. A two-line spec is fine. |
| "I'll write the spec after I code it" | That's documentation, not specification. The spec's value is in forcing clarity *before* code. |
| "The spec will slow us down" | A 15-minute spec prevents hours of rework. Waterfall in 15 minutes beats debugging in 15 hours. |
| "Requirements will change anyway" | That's why the spec is a living document. An outdated spec is still better than no spec. |
| "The user knows what they want" | Even clear requests have implicit assumptions. The spec surfaces those assumptions. |

## Red Flags

- Starting to write code without any written requirements
- Asking "should I just start building?" before clarifying what "done" means
- Implementing features not mentioned in any spec or task list
- Making architectural decisions without documenting them
- Skipping the spec because "it's obvious what to build"

## Verification

Before proceeding to implementation, confirm:

- [ ] The spec covers all six core areas
- [ ] The human has reviewed and approved the spec
- [ ] Success criteria are specific and testable
- [ ] Boundaries (Always/Ask First/Never) are defined
- [ ] The spec is saved to a file in the repository
