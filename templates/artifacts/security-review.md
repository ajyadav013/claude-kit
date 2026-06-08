# Security review: <change>

> Output of the Security Clear gate (see `.claude/rules/quality-gates.md`). Findings are classified
> Critical / High / Medium / Low / Cosmetic; Critical/High/Medium block.

## Scope
What changed and what attack surface it touches (inputs, auth, data, dependencies, config).

## Findings
| # | Severity | Area | Finding | Recommendation | Status |
|---|---|---|---|---|---|
| 1 | … | secrets/deps/owasp/policy | … | … | open/fixed |

## Checklist
- [ ] No hardcoded secrets / keys / tokens committed.
- [ ] Dependencies free of known Critical/High CVEs.
- [ ] Input validated & queries parameterized (no injection).
- [ ] AuthN/AuthZ enforced on new surfaces; least privilege.
- [ ] Sensitive data not logged; errors don't leak internals.
- [ ] CORS / rate limiting / secure cookie flags as required by policy.

## Verdict
PASS / FAIL (with the blocking findings, if any).
