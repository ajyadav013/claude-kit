---
name: triage
description: Triage unsorted backlog items into the appropriate execution horizon. Review, confirm placement, and move items from unsorted.md to their horizon file.
argument-hint: [item number or "all"]
disable-model-invocation: true
---

Triage unsorted backlog items. Argument: $ARGUMENTS

If the argument is a specific item number, triage just that item. If the argument is "all" or empty, triage all unsorted items one by one.

## Steps

1. **Read unsorted items**: Read `docs/backlog/unsorted.md` and parse all items. If there are no unsorted items, tell the user and stop.

2. **Read the README**: Read `docs/backlog/README.md` to understand the current horizons, prioritization factors, dependency chain, and existing item counts.

3. **For each item to triage**, present a summary and ask the user to confirm placement:

   Show:
   - Item number and title
   - Priority
   - Brief description (first 1-2 sentences)
   - Related items (if listed)
   - Your suggested horizon with reasoning

   If the item overlaps or duplicates an existing backlog item, flag it clearly and recommend merging or deleting before asking for placement.

   Ask the user which horizon to place it in:
   - **A: Now** — `now.md`
   - **B: Next** — `next.md`
   - **C: Later** — `later.md`
   - **Merge into #N** — merge this item's scope into an existing item, then delete this one
   - **Skip** — leave in unsorted for now
   - **Delete** — remove from backlog entirely

4. **Move the item**: For each confirmed placement:

   a. **Read the target horizon file** (e.g., `docs/backlog/now.md`).

   b. **Append the item** to the end of the horizon file (before any trailing whitespace), preserving its full content from unsorted.md.

   c. **Update the items list** at the top of the horizon file. Each horizon file has an `Items:` line listing item numbers — update the count.

   d. **Remove the item** from `docs/backlog/unsorted.md`. If it was the last item, restore the `*(No unsorted items yet.)*` placeholder.

   e. **Update the README**: In `docs/backlog/README.md`:
      - Add a row for the item in the Index table
      - Update the item count in the Summary table

5. **Handle merges**: If the user chose "Merge into #N":

   a. Find item #N in its horizon file.
   b. Append any new scope from the unsorted item into item #N's description or "What to implement" section. Don't duplicate content that already exists — only add genuinely new points.
   c. Add the unsorted item's number to item #N's "Related items" if not already listed.
   d. Remove the unsorted item from `unsorted.md`. If it was the last item, restore the placeholder.
   e. Do NOT add the merged item to the README index — it no longer exists as a standalone item.
   f. Note the merge in the summary.

6. **Handle deletions**: If the user chose "Delete", simply remove the item from `unsorted.md` without adding it anywhere. Note the deletion in the summary.

7. **Commit**: Stage all modified backlog files and commit with a message describing what was triaged. Format:
   - Single item placed: `backlog: triage #N → now`
   - Single item merged: `backlog: merge #N into #M`
   - Single item deleted: `backlog: delete #N`
   - Multiple items: `backlog: triage N items` with details in the commit body

8. **Summarize**: After all items are triaged, tell the user:
   - How many items were placed and where
   - How many were skipped or deleted
   - Any items that might need dependency links added

## Horizon File Reference

| Horizon | File | Focus |
|---------|------|-------|
| A (Now) | `docs/backlog/now.md` | Current sprint — production readiness, critical fixes |
| B (Next) | `docs/backlog/next.md` | Next sprint — feature enhancements, integrations |
| C (Later) | `docs/backlog/later.md` | Future — advanced features, scaling |

## Guidelines

- Default to the horizon suggested by `/backlog` when the item was added, but let the user override
- If an item is clearly a duplicate of an existing item, flag it and suggest merging or deleting
- When adding to a horizon file, maintain the `---` separator between items
- Keep the README index sorted by item number
- If an item has dependencies on items in a later horizon, flag the inconsistency
