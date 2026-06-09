# RARV Cycle — Reason, Act, Reflect, Verify

A short self-check every agent runs **before declaring its stage done and handing off**. It turns "I wrote some code / a review / a test" into "I confirmed this is correct against the spec." It is the per-agent discipline that the pipeline gates assume has already happened.

RARV is lightweight by design — it is a habit, not a phase. For trivial work it is two sentences of self-check; for a full implementation it is the difference between a clean gate and a defect loop.

## The Four Steps

| Step | Question | Concrete action |
|------|----------|-----------------|
| **Reason** | What exactly am I doing and what does done look like? | Read `CONTINUITY.md` + the relevant `{feature-name}_spec.md` section + the rule files for your stack. Restate the goal and the acceptance criteria you own. Check `agent-memory/` for prior learnings that apply. |
| **Act** | Do the work. | Implement / review / test the narrowest thing that satisfies the goal. No speculative scope. |
| **Reflect** | Did I actually meet the goal, or just produce output? | Re-read your own diff/report against the spec and the rule files. Hunt your own happy-path bias: empty, null, zero, max, boundary conditions, authorization scoping (for multi-tenant/role-based systems), concurrency, accessibility. |
| **Verify** | Prove it mechanically. | Run the real checks for your stack (below). Green is required, not assumed. Update `CONTINUITY.md` with what passed. |

## Verify — the mechanical proof per role

- **Developer (backend):** Run the project's linter, formatter, type checker (if applicable), and test runner
- **Developer (frontend):** Run the project's type checker, build, and test runner (if present)
- **Reviewer / Merge reviewer:** every acceptance criterion traced to a code path; every finding classified by `.claude/rules/quality-gates.md` severity
- **Tester / Senior tester:** every acceptance criterion mapped to a passing test; edge + failure cases exercised
- **DevOps:** Validate deployment configuration, perform a clean build and deployment verification with healthy services
- **Observability:** health endpoint responds, alert rules parse, logs are structured and meet project standards

## Rules

1. **No handoff before Verify is green.** If you cannot prove it, you are not done — say so in `CONTINUITY.md` and keep the task `in_progress`.
2. **Reflect on your own work adversarially.** The cheapest defect to fix is the one you catch in Reflect, before the gate.
3. **A failed Verify is a learning.** Log the miss to `CONTINUITY.md`; promote durable ones to `agent-memory/`.
4. **Scale the rigor to the task.** Fast-track (Mode D) still does RARV — just lighter. Never skip Verify.
5. **Verify means run it, not imagine it.** Never report a check as passing without executing it.
