---
name: consolidate-learnings
description: Periodic maintenance pass over .claude/agent-memory/ that merges duplicate and overlapping learnings into one canonical entry and tidies the index. Use when the SessionStart hook nudges consolidation, when a category folder has grown large, or when the user says "consolidate/merge/clean up the learnings". Never deletes distinct, still-valid learnings — only merges true duplicates and overlaps.
---

# Consolidate Learnings — Duplicate Merge Pass

Keep the agent-memory knowledge base lean and non-redundant. This runs **periodically** (nudged by the SessionStart hook every N sessions) or on demand. The goal is a single canonical entry per distinct learning — no bloat from near-duplicates accumulating as the same rule gets restated over time.

## Guiding rule

**Merge duplicates and overlaps. Do NOT delete distinct learnings.** Every learning is valid by definition. Consolidation only removes *redundancy*, never *information*. If two entries say different things, keep both. If two entries say the same thing (or one fully contains the other), merge into one.

## Procedure

### 1. Read the current state
- Read `.claude/agent-memory/MEMORY.md`.
- For each category folder (`ux/`, `architecture/`, `debugging/`, `patterns/`, `api/`, `performance/`, `gotchas/`), read every `*.md` learning file.

### 2. Group within each category
Compare entries **within the same category** (cross-category merges are rare — only do them if a learning is clearly filed in the wrong category; then move it). Identify:
- **Exact duplicates** — same rule stated twice.
- **Overlaps** — one entry is a subset/restatement of another, or two entries cover the same rule with slightly different wording or added nuance.
- **Distinct** — different rules. Leave untouched.

### 3. Merge each duplicate/overlap group
For each group of 2+ redundant entries, produce ONE canonical file:
- Keep the clearest `title` and the most specific `trigger` / `Apply when`.
- Combine the `Learning` text so no nuance from any member is lost — union of the directives, deduplicated.
- Keep the **earliest** `date` as the origin; optionally note "(consolidated YYYY-MM-DD)".
- Concatenate distinct `Evidence` if it adds value; otherwise keep the strongest.
- Write the merged content into the best-named existing file, then delete the now-redundant sibling files in that group.

Preserve the standard entry format (frontmatter: `title`, `category`, `date`, `trigger`; body: `Context`, `Learning`, `Evidence`, `Apply when`).

### 4. Detect and resolve contradictions
If two entries genuinely conflict (one says "do X", another "never do X"), do NOT silently pick one. Surface it to the user and ask which is current. Only then merge to the correct rule.

### 5. Rebuild the index
Regenerate `.claude/agent-memory/MEMORY.md` so it has exactly one line per surviving learning file, under the right `###` section, in the format:

```markdown
- [Title](category/filename.md) — one-line hook | applies when: {trigger}
```

Remove index lines pointing to files you merged away. Keep the placeholder `<!-- -->` comment for any category that ends up empty.

### 6. Report
Tell the user concisely what changed, e.g.:
> Consolidated UX: merged 3 entries about spacing into `ux/spacing-rules.md`. No information lost. 9 learnings → 7.

## What NOT to do
- Do not delete a learning because it seems minor or old — age is not staleness; these are durable rules.
- Do not rewrite the substance of a learning beyond merging — preserve the user's intent and wording.
- Do not merge across categories unless a file is clearly miscategorized.
