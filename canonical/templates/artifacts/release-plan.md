# Release plan: <version / change>

## Summary
What's shipping and the user-visible impact.

## Pre-flight
- [ ] All quality gates green (review, tests, security; pipeline/observability if applicable).
- [ ] Migrations reviewed and reversible; back-fill plan for new constraints.
- [ ] Config / env vars / feature flags documented and set per environment.

## Steps
1. …
2. …

## Verification (post-deploy)
- Health/readiness checks pass; key user journeys smoke-tested.
- Dashboards/alerts show expected baselines.

## Rollback
Exact steps to revert (deploy + data). Trigger conditions.

## Comms
Who to notify, changelog entry, and any user-facing notes.
