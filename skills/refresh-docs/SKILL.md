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
   - **If the project ships a deterministic doc-freshness checker** (a script that reports which docs are stale), run it first and use its output as the source of truth — don't re-derive by hand what a script already decides.
   - If `$ARGUMENTS` is a file path: skip the scan, just refresh that specific doc.
   - If `$ARGUMENTS` contains `--since`: run `git diff --name-only HEAD~N` to find changed source files in the last N commits.
   - Otherwise: compare each doc's last-modified / last-commit time against the source files it documents to find stale documentation.

2. **Map changes to docs**: Determine which docs are affected by the changes. (The mapping below is
   an **example shape** — build your project's own change→doc table and keep it here):
   - Component changes → the component-inventory doc, `CLAUDE.md` (architecture section)
   - Data/schema changes → the data-model doc
   - Route/endpoint changes → the routing/API doc
   - New pages/features → the user-journey/spec doc

3. **Diff the documented surface against the code surface.** Timestamp staleness (step 1) says
   *when* a doc fell behind; this step says *what* is actually wrong. For each affected doc,
   extract the surface it documents (endpoints, public functions, CLI options, config keys) and
   compare against what the code exposes today. Classify **every** divergence:

   | Class | Meaning | Severity guide |
   |-------|---------|----------------|
   | `missing_in_docs` | exists in code, absent from docs | med (undocumented surface) |
   | `missing_in_code` | documented but no longer exists | **high** — actively misleading |
   | `signature_mismatch` | in both, but params/types/returns differ | **high** — code written from the doc breaks |
   | `description_mismatch` | prose contradicts actual behavior | med–high, by how misleading |

   Low severity is reserved for cosmetic drift (naming, ordering). The classification drives what
   gets fixed first — `missing_in_code` and `signature_mismatch` before anything else.

4. **Categorize results**: Group into:
   - **Existing docs to refresh**: docs that exist but have newer source files
   - **Missing docs to create**: coverage gaps
   Present both lists to the user with counts, with each divergence's class + severity attached.

5. **Ask the user what to refresh**: Use AskUserQuestion to ask which docs to update.

6. **For each doc to refresh/create**:
   - **Read the source files** that affect this doc
   - **Read the existing doc** to understand current structure
   - **Update the doc** following the existing structure and conventions:
     - For existing docs: update only the sections affected by source changes
     - Include file paths with line numbers for key components
     - Keep the doc concise but comprehensive

7. **Verify**: Run `git diff --stat` to confirm what was changed.

8. **Summarize**: Tell the user what was updated, what was created, and what (if anything) was skipped.

## Key Documentation Files

Maintain your project's own doc→source dependency table here (the rows below are an **example
shape**, not shipped paths):

| Doc | Source Dependencies |
|-----|-------------------|
| `CLAUDE.md` | core source dirs, project structure |
| the developer-handoff / architecture doc | all application source |
| each reference doc | the specific data/config files it documents |

## Guidelines

- **Don't rewrite docs that are only slightly stale.** If the source change was minor (a small bug fix, import reorder), note it but skip the update.
- **Preserve existing structure.** When updating, match the existing doc's heading structure and level of detail.
- **Use the Explore agent** to understand source files before writing docs. Don't guess at behavior from file names alone.
- **Parallelize with subagents** when refreshing 5+ docs — spawn general-purpose subagents to handle batches concurrently.
