# Engineering Core

The everyday engineering loop: feature development, refactoring, debugging, code review, test
generation, and release preparation.

**Primary teams:** Engineering · **Default risk:** medium · **Manifest:** `pack.yaml`

## Who uses it
Backend, frontend, and full-stack engineers — the default pack for any repo doing active development.

## Role → component mapping
This pack bundles components that already ship with claude-kit (reused, not duplicated) plus a couple
added by the org layer. It does not introduce competing agents.

| Need | Use |
|------|-----|
| Run the whole delivery pipeline | `/sdlc` skill → `orchestrator` agent |
| Write a spec before coding | `/spec-driven-development` → `spec-doc-writer` (via the pipeline) |
| Break work into tasks | `/planning-and-task-breakdown` |
| Implement incrementally | `/incremental-implementation` → `developer` |
| Review code | `/code-review-and-quality` → `sdlc-code-reviewer` |
| Simplify / refactor safely | `/code-simplification` |
| Add/adjust tests | `/test-driven-development` → `tester` |
| Debug a failure | `/debugging-and-error-recovery` |
| Branch, commit, PR | `/git-workflow-and-versioning` (see `branch-and-pr-policy.md`) |
| Decide how risky a change is | `risk-classifier` agent (`risk-classification.md`) |

## Rules it leans on
`mandatory-workflow.md`, `rarv-cycle.md`, `quality-gates.md`, `code-organization.md`, `testing.md`,
`autonomy-levels.md`, `risk-classification.md`, `branch-and-pr-policy.md`.

## Hooks it expects
`guard-rm-rf`, `lint-fix`, `type-check`, and (at autonomous levels) `warn-large-edits`,
`warn-missing-tests`.

## Examples
```
/sdlc Add a "completed" flag to items: API field + a checkbox in the UI
/refactor-safely Simplify the billing service without changing behavior   # → code-simplification
/write-tests Add regression coverage for failed password-reset links      # → test-driven-development
```

## Autonomy & risk
Operates under the repo's autonomy level. Anything in a sensitive area (auth, payments, secrets,
migrations, infrastructure) is at least **high** risk — plan, get approval, run security + test review,
and write rollback notes first (`risk-classification.md`).
