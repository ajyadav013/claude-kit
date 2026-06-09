# Prototype Boundaries

A prototype exists to learn — to answer a question, prove a flow, or show an idea — not to serve real
users. It runs under relaxed process so it can move fast, which is only safe while its blast radius stays
tiny. The moment a prototype is meant to handle real traffic, data, or money, it stops being a prototype
and must be hardened first.

## A prototype MAY

- Use fake, synthetic, or seeded sample data; placeholder copy; and throwaway accounts.
- Skip the full review chain and run under the lighter non-engineer flow (`.claude/rules/non-engineer-safe-coding.md`).
- Cut corners on edge cases, polish, and breadth — enough to demonstrate the idea, no more.
- Live in a clearly disposable place (a scratch branch, a sandbox, a demo space) labeled **PROTOTYPE**.

## A prototype MUST NOT

- **Use real secrets** — no live API keys, tokens, or credentials (`.claude/rules/secrets-policy.md`).
- **Touch production data** — no real customer or user records, read or write (`.claude/rules/production-data-policy.md`).
- **Reach real users or external systems** — no production endpoints, no money movement, no outbound
  messages to real people.
- **Be silently promoted.** Shipping a prototype as-is is forbidden; promotion goes through the checklist.

## Hardening checklist — required BEFORE promotion to production

A prototype is **medium or higher** risk once promotion is proposed (`.claude/rules/risk-classification.md`).
Every item below must pass before it serves real traffic or data:

- [ ] **Input validation** — all external input is validated and rejected when malformed.
- [ ] **Authn / authz** — real authentication and authorization replace any bypass or stub.
- [ ] **Error handling** — failures are caught and handled; no crashes or leaked internals on bad input.
- [ ] **Structured logging** — observable events are logged (no secrets/PII), per `.claude/rules/devops-observability.md`.
- [ ] **Tests** — meaningful tests exist and pass via the project's test runner (`.claude/rules/testing.md`).
- [ ] **Rate limiting / quotas** — abuse and runaway cost are bounded.
- [ ] **Real data & secrets swapped in** — synthetic data and placeholder keys replaced by managed ones.
- [ ] **Review** — the change goes through the full review chain (`.claude/rules/mandatory-workflow.md`).

> Part of claude-kit's organization capability layer (vibe-coding). Cross-refs
> `.claude/rules/risk-classification.md`, `.claude/rules/non-engineer-safe-coding.md`,
> `.claude/rules/production-data-policy.md`, `.claude/rules/secrets-policy.md`. The
> `prototype-to-production` skill applies this rule and walks the hardening checklist.
