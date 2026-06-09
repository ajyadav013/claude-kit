---
name: decision
description: Record an architecture decision as an ADR. Use when making significant technology choices, pattern adoptions, or convention changes.
argument-hint: [decision title or description]
disable-model-invocation: true
---

Record an architecture decision as an ADR. The user will describe the decision as: $ARGUMENTS

## Steps

1. **Read the ADR index**: Read `docs/architecture/decisions/README.md` to find the next available number (look at the last row in the Index table, increment by 1).

2. **Read the template**: Read the [ADR template](adr-template.md) for the output structure.

3. **Generate the slug**: Convert the title argument to a slug (e.g., "Temporal over Celery" → "temporal-over-celery"). Lowercase, hyphens, no special characters.

4. **Gather context**: Based on the decision topic, explore the codebase to understand:
   - What exists today (current state)
   - What alternatives were considered or could be considered
   - What the trade-offs are

5. **Write the ADR**: Create `docs/architecture/decisions/NNNN-{slug}.md` following the template. Fill in:
   - **Status**: `Proposed` for new decisions (the team must accept it)
   - **Date**: today's date
   - **Context**: the problem or force that motivates the decision
   - **Decision**: what is being decided
   - **Alternatives Considered**: at least 2 alternatives with pros/cons
   - **Consequences**: at least 1 positive, 1 negative, and optionally neutral

6. **Update the index**: Add a new row to the Index table in `docs/architecture/decisions/README.md`.

7. **Commit**: Stage both files and commit with message: `adr: add NNNN — {Title}`

8. **Summarize**: Tell the user:
   - The ADR number and file path
   - A brief summary of what was recorded
   - Suggest they review it and change status to `Accepted` once the team agrees

## Guidelines

- ADRs record decisions, not implementations — focus on *why*, not *how*
- Keep ADRs concise — 40-80 lines is ideal
- If a decision supersedes a previous ADR, update the old ADR's status to `Superseded by [NNNN]`
- Don't create ADRs for trivial decisions (library version bumps, minor refactors, bug fixes)
- When unsure whether something deserves an ADR, err on the side of recording it — it's easier to delete than to reconstruct rationale later
