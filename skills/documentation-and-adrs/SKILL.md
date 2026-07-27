---
name: documentation-and-adrs
description: Records decisions and documentation. Use when making architectural decisions, changing public APIs, shipping features, or when you need to record context that future engineers and agents will need to understand the codebase.
---

# Documentation and ADRs

## Overview

Document decisions, not just code. The most valuable documentation captures the *why* — the context, constraints, and trade-offs that led to a decision. Code shows *what* was built; documentation explains *why it was built this way* and *what alternatives were considered*. This context is essential for future humans and agents working in the codebase.

## When to Use

- Making a significant architectural decision
- Choosing between competing approaches
- Adding or changing a public API
- Shipping a feature that changes user-facing behavior
- Onboarding new team members (or agents) to the project
- When you find yourself explaining the same thing repeatedly

**When NOT to use:** Don't document obvious code. Don't add comments that restate what the code already says. Don't write docs for throwaway prototypes. To *consolidate* ephemeral `*_REPORT.md` / `*_ANALYSIS.md` artifacts into canonical docs (rather than author new ones), use `doc-consolidation`.

## Architecture Decision Records (ADRs)

ADRs capture the reasoning behind significant technical decisions. They're the highest-value documentation you can write.

### When to Write an ADR

- Choosing a framework, library, or major dependency
- Designing a data model or database schema
- Selecting an authentication strategy
- Deciding on an API architecture (REST vs. GraphQL vs. tRPC)
- Choosing between build tools, hosting platforms, or infrastructure
- Any decision that would be expensive to reverse

### ADR Template

Store ADRs in `docs/decisions/` with sequential numbering:

```markdown
# ADR-001: Use PostgreSQL for primary database

## Status
Accepted | Superseded by ADR-XXX | Deprecated

## Date
2025-01-15

## Context
We need a primary database for the task management application. Key requirements:
- Relational data model (users, tasks, teams with relationships)
- ACID transactions for task state changes
- Support for full-text search on task content
- Managed hosting available (for small team, limited ops capacity)

## Decision
Use PostgreSQL with Prisma ORM.

## Alternatives Considered

### MongoDB
- Pros: Flexible schema, easy to start with
- Cons: Our data is inherently relational; would need to manage relationships manually
- Rejected: Relational data in a document store leads to complex joins or data duplication

### SQLite
- Pros: Zero configuration, embedded, fast for reads
- Cons: Limited concurrent write support, no managed hosting for production
- Rejected: Not suitable for multi-user web application in production

### MySQL
- Pros: Mature, widely supported
- Cons: PostgreSQL has better JSON support, full-text search, and ecosystem tooling
- Rejected: PostgreSQL is the better fit for our feature requirements

## Consequences
- Prisma provides type-safe database access and migration management
- We can use PostgreSQL's full-text search instead of adding Elasticsearch
- Team needs PostgreSQL knowledge (standard skill, low risk)
- Hosting on managed service (Supabase, Neon, or RDS)
```

### ADR Lifecycle

```
PROPOSED → ACCEPTED → (SUPERSEDED or DEPRECATED)
```

- **Don't delete old ADRs.** They capture historical context.
- When a decision changes, write a new ADR that references and supersedes the old one.

### Retroactive Backfill (existing codebases)

An established codebase full of unrecorded decisions doesn't need a historian — it needs the
handful of decisions that **still bind today**. Time-box the whole exercise to a few hours:

1. **Mine the history for decision points:**

   ```bash
   git log --all --oneline --grep="decide\|choose\|instead\|switch\|migrate\|refactor"
   git log --reverse --format="%ad %s" --date=short | head    # project timeline, oldest first
   ```

2. **Sketch the eras.** Group the history into 3–6 phases around major milestones (rewrites,
   version releases, architecture pivots). Phase boundaries are where decisions cluster.
3. **Write only the decisions that still constrain the code** — aim for 5–10 ADRs, not fifty.
   Mark each `Accepted`, and keep the "Reconstructed from `<source>`" provenance line from the
   ADR template so readers know it was back-filled, not contemporaneous.
4. **Stop.** Don't document every commit, and don't invent rationale you can't evidence from
   commits, code, or people — a back-filled ADR that guesses at *why* is worse than no ADR.
   From here forward, record decisions as they're made.

(Backfill process adapted, in this kit's terms, from the MIT-licensed
[`pborenstein/handoff`](https://github.com/pborenstein/handoff) `project-tracking` skill,
© 2026 Philip Borenstein.)

## Inline Documentation

### When to Comment

Comment the *why*, not the *what*:

```typescript
// BAD: Restates the code
// Increment counter by 1
counter += 1;

// GOOD: Explains non-obvious intent
// Rate limit uses a sliding window — reset counter at window boundary,
// not on a fixed schedule, to prevent burst attacks at window edges
if (now - windowStart > WINDOW_SIZE_MS) {
  counter = 0;
  windowStart = now;
}
```

### When NOT to Comment

```typescript
// Don't comment self-explanatory code
function calculateTotal(items: CartItem[]): number {
  return items.reduce((sum, item) => sum + item.price * item.quantity, 0);
}

// Don't leave TODO comments for things you should just do now
// TODO: add error handling  ← Just add it

// Don't leave commented-out code
// const oldImplementation = () => { ... }  ← Delete it, git has history
```

### Document Known Gotchas

```typescript
/**
 * IMPORTANT: This function must be called before the first render.
 * If called after hydration, it causes a flash of unstyled content
 * because the theme context isn't available during SSR.
 *
 * See ADR-003 for the full design rationale.
 */
export function initializeTheme(theme: Theme): void {
  // ...
}
```

## API Documentation

For public APIs (REST, GraphQL, library interfaces):

### Inline with Types (Example)

```typescript
/**
 * Creates a new task.
 *
 * @param input - Task creation data (title required, description optional)
 * @returns The created task with server-generated ID and timestamps
 * @throws {ValidationError} If title is empty or exceeds 200 characters
 * @throws {AuthenticationError} If the user is not authenticated
 *
 * @example
 * const task = await createTask({ title: 'Buy groceries' });
 * console.log(task.id); // "task_abc123"
 */
export async function createTask(input: CreateTaskInput): Promise<Task> {
  // ...
}
```

```python
def create_task(input: CreateTaskInput) -> Task:
    """Create a new task.

    Args:
        input: Task creation data (title required, description optional).

    Returns:
        The created task with server-generated ID and timestamps.

    Raises:
        ValidationError: If title is empty or exceeds 200 characters.
        AuthenticationError: If the user is not authenticated.

    Example:
        >>> task = create_task(CreateTaskInput(title="Buy groceries"))
        >>> print(task.id)  # "task_abc123"
    """
    # ...
```

### OpenAPI / Swagger for REST APIs

```yaml
paths:
  /api/tasks:
    post:
      summary: Create a task
      requestBody:
        required: true
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/CreateTaskInput'
      responses:
        '201':
          description: Task created
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Task'
        '422':
          description: Validation error
```

## README Structure

Every project should have a README that covers:

```markdown
# Project Name

One-paragraph description of what this project does.

## Quick Start
1. Clone the repo
2. Install dependencies: `<package manager install command>`
3. Set up environment: `cp .env.example .env`
4. Run the dev server: `<dev server command>`

## Commands
| Command | Description |
|---------|-------------|
| `<dev command>` | Start development server |
| `<test command>` | Run tests |
| `<build command>` | Production build |
| `<lint command>` | Run linter |

## Architecture
Brief overview of the project structure and key design decisions.
Link to ADRs for details.

## Contributing
How to contribute, coding standards, PR process.
```

## Derived Artifacts: Edit the Source, Regenerate the Output

Some documentation is **generated from a structured source of truth** — API docs rendered from an
OpenAPI spec, config files emitted by a generator script, reference tables built from a registry.
For these, the discipline is absolute:

- **Edits go to the structured input, never the deliverable.** Hand-patching a generated file
  creates a fork the next regeneration silently destroys (or worse, that a drift check now has to
  arbitrate).
- **State which file is source and which is derived** — in the doc's header or the repo's docs — so
  no future editor has to guess. An unlabeled generated file *will* eventually be hand-edited.
- **Regenerate + drift-check in CI.** The generator should have a `--check` mode that fails CI when
  the committed output no longer matches the source; that single check converts the convention into
  a guarantee. (claude-kit itself lives this rule: its hook config files are generated from a
  registry and CI fails on drift.)

## Changelog Maintenance

For shipped features:

```markdown
# Changelog

## [1.2.0] - 2025-01-20
### Added
- Task sharing: users can share tasks with team members (#123)
- Email notifications for task assignments (#124)

### Fixed
- Duplicate tasks appearing when rapidly clicking create button (#125)

### Changed
- Task list now loads 50 items per page (was 20) for better UX (#126)
```

## Documentation for Agents

Special consideration for AI agent context:

- **CLAUDE.md / rules files** — Document project conventions so agents follow them
- **Spec files** — Keep specs updated so agents build the right thing
- **ADRs** — Help agents understand why past decisions were made (prevents re-deciding). When a local ticket store is in use, ADRs are the **decisions** pillar of the project wiki (`docs/project/wiki/decisions.md`) and are linked from the ticket that made them — see `ticketing-and-traceability`.
- **Inline gotchas** — Prevent agents from falling into known traps

## Generated-doc quality gate

When an agent *writes* the docs, the docs inherit the agent's tics: filler, unearned claims, and the
tells of machine prose. The "why over what" principle above governs *what to say*; this gate governs
*how it reads*. Run it on any doc an agent generated or rewrote (README, guide, ADR prose, API docs,
changelog text) before commit — the prose counterpart to the code-review grounding discipline in
`code-review-and-quality`.

> Detection heuristics re-derived (stack-agnostic) from the MIT-licensed
> [`athola/claude-night-market`](https://github.com/athola/claude-night-market) `slop-detector` /
> `doc-generator` skills (© 2025 athola). Not vendored.

### Hard fails — a single hit fails the doc, independent of any other quality

1. **Identity & voice leaks.** Generated-assistant register that leaked into a published artifact:
   "As a large language model", "as of my training cutoff", "I cannot provide"; conversational
   openers ("Great question!", "Hope this helps!", "Sure!"); self-narration of structure ("In this
   section we will…", "Let's dive into…", "By the end of this guide…"). Delete on sight.
2. **Hallucinated references.** Every backticked identifier, function, path, and config key named in
   the prose must actually exist in the codebase; every install command the doc tells the reader to
   run must resolve on its registry (the typosquat/existence check in `dependency-verification`);
   cited URLs should resolve. A confident reference to something that doesn't exist is wrongness, not
   style.
3. **Unverified quality claims.** "Production-ready", "fast", "secure", "scalable", "battle-tested"
   each must point to evidence *in the same repo* (a CI workflow, a benchmark, a test, an audit). No
   evidence → delete the claim. This is the grounded-findings rule (`code-review-and-quality`) applied
   to marketing prose.

### Human-quality writing principles

- **Slop is a density problem, not a word list.** One "comprehensive" is fine; a paragraph of
  "comprehensive / robust / seamless / leverage" is generated text. Don't maintain a banned-words
  list — flag *concentrations* and register mismatch, and prefer the plain word ("use" over
  "leverage", "thorough" over "comprehensive").
- **Thesis-first.** The lead states the single takeaway; a reader who stops after the first paragraph
  still leaves with the message. Echo the thesis at the close; cut every other repetition.
- **Earn every sentence.** A document costs the sum of its readers' time. Each sentence should carry,
  instance, bound, or repeat the thesis — delete the ones that don't. One example is proof; two is
  emphasis; three is filler.
- **Active voice with reasoning.** Explain *why this choice* (which database, which pattern), not
  neutral boilerplate. Don't humanize constructs ("the code wants", "the function speaks to").
- **Prose over bullet waterfalls.** Bullets are for short, parallel lists. Multi-line bullet cascades
  bury the reasoning — convert them to prose so the *why* survives.
- **Drop the machine tells.** Em-dash overuse as a rhetorical pause, tricolons ("fast, reliable, and
  scalable"), contrastive negation ("not just X, but Y" / "it's not X, it's Y"), vapid openers ("In
  today's fast-paced world"), and sycophantic framing. No emojis unless requested. Use the imperative
  mood for docstrings ("Validate input", not "Validates input").

When cleaning an existing doc, change *how* it reads, never *what* it says — if the meaning is
unclear, ask rather than guess. After editing, re-check against the hard fails.

## Common Rationalizations

| Rationalization | Reality |
|---|---|
| "The code is self-documenting" | Code shows what. It doesn't show why, what alternatives were rejected, or what constraints apply. |
| "We'll write docs when the API stabilizes" | APIs stabilize faster when you document them. The doc is the first test of the design. |
| "Nobody reads docs" | Agents do. Future engineers do. Your 3-months-later self does. |
| "ADRs are overhead" | A 10-minute ADR prevents a 2-hour debate about the same decision six months later. |
| "Comments get outdated" | Comments on *why* are stable. Comments on *what* get outdated — that's why you only write the former. |

## Red Flags

- Architectural decisions with no written rationale
- Public APIs with no documentation or types
- README that doesn't explain how to run the project
- Commented-out code instead of deletion
- TODO comments that have been there for weeks
- No ADRs in a project with significant architectural choices
- Documentation that restates the code instead of explaining intent

## Verification

After documenting:

- [ ] ADRs exist for all significant architectural decisions
- [ ] README covers quick start, commands, and architecture overview
- [ ] API functions have parameter and return type documentation
- [ ] Known gotchas are documented inline where they matter
- [ ] No commented-out code remains
- [ ] Rules files (CLAUDE.md etc.) are current and accurate
