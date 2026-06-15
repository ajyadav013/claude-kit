# 03 — Story breakdown  *(coverage gate, stage 1f)*

> Produced by `story-planner`. The coverage gate: implementation cannot start until **every** acceptance
> criterion maps to at least one story and every story traces back to a criterion. No orphan stories, no
> uncovered criteria.

| Story | Lane | Covers | Notes |
|-------|------|--------|-------|
| S1 — Add `done` column + migration | backend | R1, AC1 | Additive: nullable → backfill `false` → set default/not-null (expand/contract; see `migration-specialist`) |
| S2 — `PATCH /tasks/{id}` endpoint | backend | R2, AC1, AC2, AC3 | New route; request schema with required boolean `done` |
| S3 — Service + repository toggle | backend | R2, AC1 | `TaskNotFoundError` → 404 in the router |
| S4 — Checkbox in the list | frontend | R3, AC4 | Optimistic toggle, reconcile on response |
| S5 — Completed styling | frontend | R4, AC4 | Struck-through when `done` |
| S6 — Regression guard | both | R5, AC5 | Existing list/create/delete tests must stay green |

### Coverage check
- AC1 → S1, S2, S3 ✓   AC2 → S2 ✓   AC3 → S2 ✓   AC4 → S4, S5 ✓   AC5 → S6 ✓
- Every story traces to a requirement; no orphans. **Coverage gate: PASS.**

The two lanes (backend S1–S3, frontend S4–S5) then proceed **in parallel**, each in its own worktree
with its own code reviewer; `merge-reviewer` joins them at the API contract.
