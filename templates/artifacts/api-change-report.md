# API change report: <feature / version>

> Produced by the **contract-clear** gate (`merge-reviewer`, standard+ / API-exposing stacks). It
> diffs the externally-exposed API contract against the base branch. Backward-incompatible deltas for
> already-shipped consumers block the gate unless an approved migration note + version bump accompany
> them. The gate self-skips when no contract surface (OpenAPI / GraphQL / typed routes) is found.

## Contract source
- Spec: <openapi.(json|yaml) | GraphQL SDL | generated-from-typed-routes>
- Base ref: <branch/commit the working copy was diffed against>

## Added (non-breaking)
- <new endpoint / new optional field / new enum value>

## Changed
| Delta | Endpoint / field | Severity | Backward-incompatible? | Migration note |
|-------|------------------|----------|------------------------|----------------|
| <type narrowed / new required field / status code changed / renamed> | … | Critical/High/Medium/Low | yes/no | <link or N/A> |

## Removed / deprecated
- <removed or renamed endpoint/field> — deprecation + removal plan: <link to `.claude/skills/deprecation-and-migration` output>

## Backward-compatibility verdict
- Breaking deltas: <count> · each carries an approved migration note + version bump: <yes/no>
- Version bump: <major | minor | patch> — <old → new>
- **contract-clear:** <PASS / FAIL> (PASS only at zero Critical/High/Medium per `.claude/rules/quality-gates.md`)

## Affected consumers
- <known internal/external consumers of the changed surfaces, and how each is migrated>
