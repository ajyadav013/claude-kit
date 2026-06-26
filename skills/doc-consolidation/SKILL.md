---
name: doc-consolidation
description: Harvest the ephemeral report/analysis markdown that agent runs leave behind (REPORT/ANALYSIS/AUDIT/SUMMARY files, untracked scratch notes) into canonical, committed documentation — then delete the sources. Triage candidates → extract the durable knowledge → route each chunk to the right home (ADR, plan, changelog, existing doc) → get approval → merge → remove the originals. Stack-agnostic; operates on markdown, not code. Use when working-tree markdown artifacts have piled up, before raising a PR, or to preserve insights from a review/audit before they rot. Do NOT use to author a doc from scratch or write an ADR (use documentation-and-adrs), to judge prose quality (use documentation-and-adrs' generated-doc quality gate), or to consolidate code/config (this is markdown-only).
---

# Doc Consolidation (ephemeral reports → canonical docs)

> Re-derived (stack-agnostic) from the MIT-licensed
> [`athola/claude-night-market`](https://github.com/athola/claude-night-market) `doc-consolidation`
> skill (© 2025 athola). Re-cast around this kit's `docs/decisions/` ADR layout, CHANGELOG, and the
> confirm-before-delete posture of `.claude/rules/human-in-the-loop.md`. Not vendored.

## What this is (and is not)

An autonomous run generates markdown as a by-product — `*_REPORT.md`, `*_ANALYSIS.md`, `AUDIT.md`,
review write-ups, scratch plans. Each holds a little durable knowledge wrapped in a lot of one-time
framing, and it tends to sit **untracked** in the working tree until it either gets committed by
accident or deleted with its insight unsaved. This skill is the **cleanup pass that rescues the
signal and removes the noise**: it pulls the keepable knowledge into permanent, committed docs and
then deletes the source artifacts.

It is *not* doc authoring. Writing a fresh guide, a README, or a net-new ADR — and judging whether
the prose is human-quality — is `documentation-and-adrs` (and its generated-doc quality gate). This
skill **moves and merges knowledge that already exists** in throwaway files. Run the quality gate on
the result if the merged prose was itself agent-generated.

## When to use

- Untracked `*_REPORT.md` / `*_ANALYSIS.md` / `AUDIT.md` / `*_SUMMARY.md` have accumulated from runs
- Preparing a PR and the working tree shows analysis files that should not be committed as-is
- You want to preserve findings from a code review, refactor, or audit before they're lost
- A long run's CONTINUITY / scratch notes contain a decision worth promoting to an ADR

**When NOT to use:** files already live in a proper home (`docs/`, `skills/`); they're intentional
short-lived scratch the user wants kept verbatim; or they hold no extractable value (pure log/tool
dumps) — in which case just propose deleting them.

## Two-phase workflow (triage is read-only; execution is approval-gated)

Deleting files you did not author is a **confirm-tier action** (`.claude/rules/human-in-the-loop.md`,
`.claude/rules/agent-guardrails.md`): present the plan and get a yes before any merge-and-delete.

### Phase 1 — Triage (read-only, propose a plan)

1. **Detect candidates.** Untracked markdown (`git status --porcelain`) outside the standard doc
   dirs, with non-canonical names (ALL-CAPS, `_REPORT`/`_ANALYSIS` suffixes) or LLM-output markers
   (an "Executive Summary", "Findings", "Action Items" heading).
2. **Extract & categorize** each file's sections into chunks, tagging each by category (below) and a
   value score (high / medium / low). Low-value generic boilerplate is dropped, not merged.
3. **Route** each keepable chunk to a destination + a merge strategy.
4. **Present the plan** as a table and stop for approval. This is the gate — nothing is written or
   deleted yet.

A cheaper model tier can do the read-only triage (`.claude/rules/model-tiers.md`); keep the merge
itself on the working tier where judgement matters.

### Phase 2 — Execute (after the user approves)

1. **Merge** each chunk into its destination using the chosen strategy.
2. **Verify** the merge: destination frontmatter intact, structure preserved, nothing clobbered.
3. **Delete the sources** only after their content is confirmed merged.
4. **Report** what was created / updated / deleted so the diff is reviewable before commit.

## Routing — where each kind of knowledge belongs

| Content category | Canonical home |
|------------------|----------------|
| Decisions / architecture choices | a new ADR in `docs/decisions/` (via `documentation-and-adrs`) |
| Actionable items / next steps | a dated plan under `docs/plans/` (or the issue tracker) |
| Findings / insights / audit results | weave into the best-matching existing doc |
| Metrics / before-after baselines | the benchmarks/eval doc (`.claude/rules/evals.md` artifacts) |
| API / breaking changes / deprecations | `CHANGELOG.md` and the API docs |
| A durable lesson, not a doc | promote to `agent-memory/` via `remember`, don't make a doc |

## Merge strategies

- **Weave** — insert into a matching existing section, preserving its voice. *When:* the destination
  has a relevant section and the content is additive.
- **Replace** — swap a stale section for the more detailed/newer content. *When:* new content is
  materially more complete or supersedes the old.
- **Append** — add a dated, source-referenced section. *When:* no matching section exists.
- **Create** — a standalone new doc. *When:* no suitable destination exists and it warrants its own
  file (a new ADR is the common case — hand off to `documentation-and-adrs`).

## Cardinal rules

1. **No deletion before the merge is verified.** Confirm the knowledge landed in its destination
   *before* removing the source. A lost insight is worse than a stray file.
2. **Approval gates the whole execution phase.** Triage freely (read-only); never merge-and-delete
   without the user's yes on the plan.
3. **Deletion beats dilution.** Drop low-value/generic chunks rather than padding canonical docs with
   them — over-merging is how good docs rot.
4. **Promote, don't hoard.** A durable lesson goes to `agent-memory/` (`remember`), not into a doc;
   keep this aligned with the promote-don't-hoard rule in `.claude/rules/continuity.md`.

## Related

- `documentation-and-adrs` — authoring the canonical docs/ADRs this skill routes into; its
  generated-doc quality gate vets the merged prose
- `.claude/rules/human-in-the-loop.md` / `.claude/rules/agent-guardrails.md` — deleting files you
  didn't create is confirm-tier; this skill obeys that gate
- `.claude/rules/continuity.md` — promote-don't-hoard; durable lessons go to `agent-memory/`, not docs
- `.claude/rules/model-tiers.md` — run the read-only triage on a cheaper tier
- `remember` skill — where a durable lesson goes instead of a doc
