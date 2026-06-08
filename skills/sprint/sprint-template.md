# Sprint Plan: {Item Title} (Backlog #{N})

> **Scope Doc**: [{Item Title}](./{slug}/scope.md)
> **Assignee**: {agent team or person}
> **Date**: {YYYY-MM-DD}

---

## Deliverables

1. {deliverable with acceptance criteria}
2. {deliverable with acceptance criteria}

## Task Breakdown

### Components

| # | Task | Files | Depends On |
|---|------|-------|------------|
| C1 | | | — |

### Data / Mock Data

| # | Task | Files | Depends On |
|---|------|-------|------------|
| D1 | | | — |

### Integration / Wiring

| # | Task | Files | Depends On |
|---|------|-------|------------|
| I1 | | | — |

## Parallelization

Which tasks can run concurrently across agents?

```
Agent 1 (frontend-dev): Task D1 → C1 → C2
Agent 2 (frontend-dev): Task D2 → C3 → C4
Integration:            ----waits---- → I1 (verify all)
```

## Verification Checklist

- [ ] TypeScript compiles (`npm run build`)
- [ ] No lint errors (`npm run lint`)
- [ ] No regressions in existing pages
- [ ] New components follow design system rules
- [ ] All interactive elements have appropriate `aria-label`
- [ ] Dev server renders correctly (`npm run dev`)

---

## Sprint Report

> **Completed**: {YYYY-MM-DD}
> **Team**: {agent count and types}

### Results

| Deliverable | Target | Actual | Status |
|-------------|--------|--------|--------|
| | | | |

### Metrics

| Metric | Value |
|--------|-------|
| Tasks planned | |
| Tasks completed | |
| Regressions found | |

### What Went Well

- {positive outcome}

### What Went Wrong

- {issue encountered}

### Learnings

1. {actionable lesson for future sprints — reference docs/reference/post-sprint-learnings.md for existing learnings}

### Unresolved / Carry-Over

| # | Issue | Details |
|---|-------|---------|
| K1 | | |
