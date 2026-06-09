# Quality & Review

The verification loop: test planning, regression analysis, PR review, security review, performance
review, accessibility review, and acceptance review — everything that gates a change before it ships.

**Primary teams:** QA · Engineering · **Default risk:** medium · **Manifest:** `pack.yaml`

## Who uses it
QA engineers and any engineer wearing a reviewer or tester hat — the pack for verifying work, not
producing it. Pairs with `engineering-core` (which builds) and `security-and-compliance` (deeper
security gates).

## Role → component mapping
This pack bundles components that already ship with claude-kit (reused, not duplicated). It introduces
no competing agents — every reviewer and tester role maps to an existing pipeline agent.

| Need | Use |
|------|-----|
| Review a PR / change for correctness and quality | `/code-review-and-quality` → `sdlc-code-reviewer` |
| Plan and write tests before/with the change | `/test-driven-development` → `tester` |
| Add or strengthen unit coverage | `/unit-test` → `unit-tester` |
| Verify end-to-end / acceptance flows | `e2e-tester` (then `acceptance-reviewer`) |
| Independently re-verify coverage and findings | `senior-tester` |
| Security review of the change | `/security-verification` (`threat-model` for design risk) |
| Performance review / regression check | `/performance-optimization` |
| Accessibility review | `/accessibility-review` |
| Stress-test a unanimous PASS (anti-sycophancy) | `devils-advocate` |
| Probe assumptions before approving | `/doubt-driven-development` |
| Manual / smoke check before sign-off | `/manual-test`, `/smoke-test` |
| Confirm cross-stream coverage has no gaps | `merge-reviewer` |

## Rules it leans on
`quality-gates.md` (severity model + blind review + Devil's Advocate), `testing.md` (coverage
expectations and lanes), `rarv-cycle.md` (every reviewer shows a green Verify before handoff).

## Hooks it expects
`warn-missing-tests` (flags changes that touch behavior without test coverage), plus `lint-fix` and
`type-check` so review starts from a clean baseline.

## Examples
```
/review-pr Check the latest change to the items service                # → code-review-and-quality
/write-tests Add regression coverage for the failed-login path         # → test-driven-development
/security-verification Review the new file-upload handler              # → security-verification
/accessibility-review Audit the new settings screen                    # → accessibility-review
```

## Autonomy & risk
Reviewers and testers **plan and delegate only** — they do not write or run application code; they
verify, classify findings (Critical/High/Medium/Low/Cosmetic), and gate. A gate passes only with zero
Critical/High/Medium open (`quality-gates.md`). Anything in a sensitive area (auth, payments, secrets,
migrations, infrastructure) is at least **high** risk and requires security + test review plus explicit
human approval before the gate counts (`.claude/rules/risk-classification.md`).
