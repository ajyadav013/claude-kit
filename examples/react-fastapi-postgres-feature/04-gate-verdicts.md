# 04 — Gate verdicts

> The heart of the run: every `standard`-profile gate, its owner, and its verdict under the severity
> model (`.claude/rules/quality-gates.md` — PASS only at **zero Critical/High/Medium**). One gate
> failed first pass and triggered the **defect loop**; only the affected lane re-ran.

## First pass

| # | Gate | Owner | Verdict | Findings |
|---|------|-------|---------|----------|
| 1 | **spec-complete** | `spec-doc-writer` | ✅ PASS | R1–R5 numbered; AC1–AC5 testable |
| 2 | **em-approved** | `em-reviewer` | ✅ PASS | Every requirement has an approach; scope bounded |
| — | coverage (1f) | `story-planner` | ✅ PASS | All ACs mapped (see `03-story-breakdown.md`) |
| 3 | **code-review** (backend lane) | `sdlc-code-reviewer` | ✅ PASS | 0 Critical/High/Medium; 1 Low (naming) noted as TODO |
| 3 | **code-review** (frontend lane) | `sdlc-code-reviewer` | ✅ PASS | 0 Critical/High/Medium |
| — | merge (contract) | `merge-reviewer` | ✅ PASS | Backend response shape matches the frontend type |
| 4 | **build-green** | (lane CI) | ✅ PASS | `ruff` + `mypy` + `pytest` green; `npm run lint/typecheck/build` green |
| 5 | **test-coverage** | `merge-reviewer` (blind testers) | ❌ **FAIL** | **High:** AC3 (invalid body → 422) had **no test**; the endpoint returned **500** on a non-boolean `done` |
| 6 | **security-clear** | `security-reviewer` (+ sub-scanners) | ✅ PASS | No secrets; deps clean; no injection in the new query |
| 7 | **contract-clear** | `merge-reviewer` | ✅ PASS | New endpoint = **additive** (Low/Cosmetic); no breaking delta, so no migration note required |

**Gate 5 blocked delivery** (a High finding is blocking). Into the defect loop.

## Defect loop (only the affected lane re-ran)

1. **Documented & classified:** AC3 uncovered → endpoint 500s instead of 422 on a bad body — **High**,
   backend lane.
2. **Fix:** request schema rejects a non-boolean `done`; FastAPI now returns 422. Added the missing
   test for AC3.
3. **Re-ran the backend lane only:** `code-review` (PASS) → `build-green` (PASS) → `test-coverage`.

| Gate | Owner | Verdict |
|------|-------|---------|
| **test-coverage** (re-run) | `merge-reviewer` (blind testers) | ✅ PASS — AC1–AC5 all covered, all green |

## Anti-sycophancy

The re-run `test-coverage` PASS was **unanimous** across the blind senior testers, which triggered the
**`devils-advocate`** before the gate counted:

> `devils-advocate`: Probed whether AC3's new test actually asserts the 422 *status* (not just "an
> error"), and whether AC5's regression set really exercises delete. Both confirmed against the diff.
> **Verdict: CONFIRMED — PASS stands.**

## Acceptance

`acceptance-reviewer` is an **enterprise** gate, so it did not run on this `standard` profile; the
`standard` run ends at a green `security-clear` + `contract-clear` and hands off to the `pr-raiser`.

**Final: all active `standard` gates green → PR raised (`05-sample-pr.diff`).**
