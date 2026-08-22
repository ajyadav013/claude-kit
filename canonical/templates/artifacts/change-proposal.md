# Change proposal: <name>

> A **delta spec** for an incremental change to an existing, already-specced system — use this
> instead of a full `feature-spec.md` when you are modifying behavior a prior spec/system already
> defines. Reference the base spec's stable requirement ids (R1, R2, …); the **Story Planner**
> (workflow stage 1f) maps every *new or changed* acceptance criterion to a story, exactly as for a
> full spec. Greenfield work uses `feature-spec.md`; externally-exposed API contract deltas also get
> an `api-change-report.md`.

## Motivation / trigger
What changed in the world (a bug, a new requirement, a deprecation, scale) that makes this edit
necessary? Why now?

## Affected requirements (delta)
Only the requirements this change touches. Keep the base spec's ids stable; add new ones with the
next free number. Every ADDED or MODIFIED requirement needs at least one checkable Given/When/Then.

### Added
- **R<new>** — <new requirement>
  - [ ] Given … when … then …

### Modified
- **R<existing>** — was: <old behavior> → now: <new behavior>. Why: <reason>.
  - [ ] Given … when … then …   ← the acceptance delta (what changed about "done")

### Removed
- **R<existing>** — removed because <reason>. Migration / cleanup: <what consumers must do>.

## Scope (changed artifacts only)
The specific files / modules / surfaces this delta touches — nothing else. Note independent lanes if
the change spans more than one.

## Backward compatibility / migration
Is the change **additive** (existing behavior unchanged) or **breaking**? For breaking changes: the
migration path, the deprecation window, and the version bump. For API surfaces, cross-link the
`api-change-report.md` (the contract-clear gate).

## Test plan (delta)
Which existing tests change (and how), and which new tests prove each ADDED / MODIFIED criterion
(reference the R-ids). Untouched requirements keep their existing coverage — do not re-litigate them.

## Rollout / open questions
