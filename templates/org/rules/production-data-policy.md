# Production Data Policy

Never operate on production data without explicit, recorded human approval. Production data is the
highest-trust surface in the project — getting it wrong is rarely reversible. Default to synthetic,
sample, or anonymised data for every build, test, and demo; touch the real data store only when there
is no safe alternative and a human has said yes in writing.

## Default posture

1. **Prefer fake data.** Use synthetic, sample, or anonymised fixtures for development, tests, and
   prototypes. If you need realistic data, generate or anonymise it — never copy production records.
2. **No destructive operations against production.** No deletes, overwrites, bulk updates, truncation,
   or schema drops on the live data store. These are at least **high** risk per
   `.claude/rules/risk-classification.md`.
3. **Least-privilege read only.** Read access to production is granted only when justified, scoped to
   what the task needs, and time-boxed. Never request write access by default.
4. **No exfiltration.** Don't copy production data into logs, prompts, fixtures, screenshots, or
   external services. Personal data is additionally governed by `.claude/rules/pii-policy.md`.

## Rules

- **Explicit, recorded approval.** Any operation on production data stops and asks a human; record who
  approved, what was approved, and when. See `.claude/rules/human-in-the-loop.md`.
- **Approval is scoped and single-use.** Permission for one read/operation does not extend to the next
  or to a wider dataset — re-confirm each time.
- **Migrations follow the high-risk protocol.** A migration that runs against production is high risk:
  write a plan, capture rollback notes (how to undo, and the point of no return), get approval before
  running, and report the outcome faithfully — including failures.
- **State the blast radius.** Before any approved operation, say what it touches, how many records, and
  whether it can be undone, so the human can weigh the cost of getting it wrong.

> Part of claude-kit's organization capability layer. Cross-refs
> `.claude/rules/risk-classification.md`, `.claude/rules/pii-policy.md`, and
> `.claude/rules/human-in-the-loop.md`. Sensitive-area escalation is also wired into
> `.claude/rules/prompt-to-task-conversion.md`.
