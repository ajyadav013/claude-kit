---
name: consolidate-learnings
description: Merge duplicate and overlapping .claude/agent-memory/ learnings into one canonical entry per rule and rebuild the index. Use when the SessionStart hook nudges or user says consolidate/clean up learnings.
---

# Consolidate Learnings — Duplicate Merge Pass

Keep the agent-memory knowledge base lean and non-redundant. This runs **periodically** (nudged by the SessionStart hook every N sessions) or on demand. The goal is a single canonical entry per distinct learning — no bloat from near-duplicates accumulating as the same rule gets restated over time.

## Guiding rule

**Merge duplicates and overlaps. Do NOT delete distinct learnings.** Every learning is valid by definition. Consolidation only removes *redundancy*, never *information*. If two entries say different things, keep both. If two entries say the same thing (or one fully contains the other), merge into one.

## Procedure

### 1. Read the current state
- Read `.claude/agent-memory/MEMORY.md`.
- For each category folder (`ux/`, `architecture/`, `debugging/`, `patterns/`, `api/`, `performance/`, `gotchas/`), read every `*.md` learning file.
- **Advisory shape check** (while reading): flag any entry missing the `trigger:` frontmatter or a
  body section (`Context` / `Learning` / `Evidence` / `Apply when`). Repair from the entry's own
  content where the fix is obvious (e.g. derive `trigger` from an existing `Apply when`); otherwise
  list it in the step-7 report. **Never delete or skip an entry for non-conformance** — a lossy
  learning beats no learning; the shape exists to make retrieval reliable, not to gate capture.

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
- Union the members' `## Related` lines into the canonical file (dedup), and **repoint** any other
  entry whose `## Related` line targets a merged-away sibling to the canonical file instead.
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

### 6. Promote — graduate proven procedure clusters into always-on artifacts

After the merge pass, check each category for learnings that have outgrown the memory store:

- **Trigger**: 3+ surviving entries in one category encode a repeatable *procedure* for the same
  domain (not isolated facts), OR a single entry's evidence shows it has applied 3+ times.
- **Action**: graduate the cluster into a **project-local skill** at
  `.claude/skills/<domain>/SKILL.md` (for multi-step procedures) or a **user-owned rule** under
  `.claude/rules/` (for always-on constraints). Both are non-kit files, so `claude-kit upgrade`
  never touches them. Replace the graduated entries with ONE pointer line in `MEMORY.md`
  (`- promoted to .claude/skills/<domain>/ — <date>`), so the history of where they went survives.
- **Propose before writing.** Promotion turns quietly-accumulated memory into always-on shared
  config — a scope expansion under `.claude/rules/human-in-the-loop.md` (rules/skills are
  project-wide files). Before creating or updating the artifact, present the cluster, the target
  path, and the update-vs-create choice to the user, and proceed only on confirmation. Carry
  provenance into the promoted artifact: name the source entries (filenames + dates) it was
  distilled from, so its authority is traceable back to the evidence.
- **Update-vs-create decision tree** (apply in order):
  1. An existing skill already covers the domain → **update it, never fork** a sibling.
  2. Partial overlap → **broaden the existing skill** to absorb the new procedure.
  3. Zero coverage → create a new skill **at the category level only** (one `debugging-<project>`
    skill, not one skill per gotcha).
  Prefer updating over creating — **fewer rich skills beat many thin ones**.
- **Why**: memory entries are recalled *probabilistically* (index line → maybe opened); a skill or
  rule is *reliably* loaded when its trigger fires. A procedure the project keeps needing deserves
  the reliable path. This closes the pipeline: observation → learning (capture) → merged learning
  (steps 1-5) → **always-on artifact** (this step).

### 7. Report
Tell the user concisely what changed, e.g.:
> Consolidated UX: merged 3 entries about spacing into `ux/spacing-rules.md`. No information lost. 9 learnings → 7. Promoted the 4 deploy-pipeline gotchas into `.claude/skills/deploy-debugging/SKILL.md`.

## What NOT to do
- Do not delete a learning because it seems minor or old — age is not staleness; these are durable rules.
- Do not rewrite the substance of a learning beyond merging — preserve the user's intent and wording.
- Do not merge across categories unless a file is clearly miscategorized.
