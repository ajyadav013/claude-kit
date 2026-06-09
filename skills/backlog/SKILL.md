---
name: backlog
description: Add a new feature idea to the product backlog. Use when the user wants to log a new idea, feature request, or improvement.
argument-hint: [idea description]
disable-model-invocation: true
---

Add a new idea to the backlog. The user will describe the idea as: $ARGUMENTS

Follow these steps:

1. **Read the unsorted file**: Read `docs/backlog/unsorted.md` to find the next item number (listed at the top as "Next item number: N").

2. **Read the README**: Read `docs/backlog/README.md` to understand the current horizons, prioritization factors, and existing items — so you can suggest the right placement.

3. **Write the new item**: Append the item to `docs/backlog/unsorted.md` (before the closing note if the file is empty, or at the end). Use the format in [item-template.md](item-template.md).

4. **Increment the counter**: Update the "Next item number" in `unsorted.md` to N+1.

5. **Suggest horizon placement**: Based on the prioritization factors in the README, suggest which horizon this item likely belongs to and why. Format as:

   ```
   **Suggested horizon**: {now / next / later} — {one-line reason}
   ```

   Don't move it there yet — the user will do that during triage.

6. **Commit**: Stage `docs/backlog/unsorted.md` and commit with message: `backlog: add #N — {Title}`

7. **Summarize**: Tell the user:
   - Item #{N} added to `docs/backlog/unsorted.md`
   - Your suggested horizon placement
   - Remind them to run `/triage N` to move it into the right horizon file

## Guidelines

- Keep the description concise but specific — enough context for `/scope` to work with later
- Infer priority from urgency cues in the user's description
- If the user gives a very brief description, expand it into something actionable but don't over-engineer
- If the idea is clearly related to existing items, mention them in "Related items"
- Don't modify any horizon files — unsorted items stay in unsorted.md until the user triages
