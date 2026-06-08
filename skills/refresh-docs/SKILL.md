---
name: refresh-docs
description: Scan for stale reference docs and update them by reading current source code and data files.
argument-hint: [--since N | path/to/doc.md]
disable-model-invocation: true
---

Refresh stale documentation by scanning source code and updating docs that have fallen behind.

## Arguments

- No args: full scan of all reference and spec docs
- `--since N`: only check source files changed in the last N commits
- `path/to/doc.md`: refresh a specific doc file

## Steps

1. **Identify what changed**:
   - If `$ARGUMENTS` is a file path: skip the scan, just refresh that specific doc.
   - If `$ARGUMENTS` contains `--since`: run `git diff --name-only HEAD~N` to find changed source files in the last N commits.
   - Otherwise: compare docs against source files to find stale documentation.

2. **Map changes to docs**: Determine which docs are affected by the changes:
   - Component changes → `docs/reports/DEVELOPER_HANDOFF.md` (component inventory), `CLAUDE.md` (architecture section)
   - Data file changes → `docs/reports/DEVELOPER_HANDOFF.md` (data model section)
   - Route changes → `docs/reports/DEVELOPER_HANDOFF.md` (routing section)
   - KPI/RAG threshold changes → `docs/reference/AOCT_Apex_CT_RAG_Definitions.md`, `docs/reference/Apex_CT_Metric_Formulas.md`
   - New pages/features → `docs/specs/USER_JOURNEY.md`

3. **Categorize results**: Group into:
   - **Existing docs to refresh**: docs that exist but have newer source files
   - **Missing docs to create**: coverage gaps
   Present both lists to the user with counts.

4. **Ask the user what to refresh**: Use AskUserQuestion to ask which docs to update.

5. **For each doc to refresh/create**:
   - **Read the source files** that affect this doc
   - **Read the existing doc** to understand current structure
   - **Update the doc** following the existing structure and conventions:
     - For existing docs: update only the sections affected by source changes
     - Include file paths with line numbers for key components
     - Keep the doc concise but comprehensive

6. **Verify**: Run `git diff --stat` to confirm what was changed.

7. **Summarize**: Tell the user what was updated, what was created, and what (if anything) was skipped.

## Key Documentation Files

| Doc | Source Dependencies |
|-----|-------------------|
| `CLAUDE.md` | `src/components/ui/`, `src/lib/`, `src/hooks/`, project structure |
| `docs/reports/DEVELOPER_HANDOFF.md` | All `src/` files |
| `docs/reference/Apex_CT_Metric_Formulas.md` | `src/data/ragThresholds.ts`, `src/data/kpiRegistry.ts` |
| `docs/reference/AOCT_Apex_CT_RAG_Definitions.md` | `src/data/ragThresholds.ts`, `src/data/mockControlTower.ts` |

## Guidelines

- **Don't rewrite docs that are only slightly stale.** If the source change was minor (a small bug fix, import reorder), note it but skip the update.
- **Preserve existing structure.** When updating, match the existing doc's heading structure and level of detail.
- **Use the Explore agent** to understand source files before writing docs. Don't guess at behavior from file names alone.
- **Parallelize with Task agents** when refreshing 5+ docs — spawn `frontend-dev` agents to handle batches concurrently.
