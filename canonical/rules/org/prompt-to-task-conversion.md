# Prompt → Task Conversion

A natural-language prompt is not yet a safe task. Before acting on any free-form request — especially
from a non-engineer — convert it into a scoped, risk-classified, verifiable task. This is the front door
for vibe-coding; it makes "just build X" safe.

## Convert every prompt into

1. **Goal** — the outcome in one sentence (what "done" means), not the mechanism.
2. **Scope** — the files/areas it should touch, and an explicit **out-of-scope** line.
3. **Risk tier** — low / medium / high / restricted per `rule://risk-classification`.
4. **Success criteria** — how the result will be verified (tests, a check, an observable behavior).
5. **Plan** — the ordered steps; for anything above low risk, write it down before editing.
6. **Approval point** — who must say yes, and before which step (see below).

## Rules

- **Resolve ambiguity first.** If the goal, scope, or success is unclear, ask — do not guess. See
  `rule://ambiguity-resolution`.
- **Smallest safe scope.** Prefer the minimal change that meets the goal; never silently expand scope.
- **Match the autonomy level.** Stay within `rule://autonomy-levels`; if the task needs more
  autonomy than granted, stop and ask.
- **Sensitive areas escalate automatically.** Auth, payments, secrets, production data, migrations, and
  infrastructure are at least **high** risk — apply the high-risk protocol and get explicit approval.
- **State assumptions.** Surface what you inferred so a human can correct it before work proceeds.

> Part of {{ provider.executable.cli }}'s organization capability layer (vibe-coding). Cross-refs
> `rule://non-engineer-safe-coding`, `rule://ambiguity-resolution`,
> `rule://risk-classification`, `rule://autonomy-levels`. The `prompt-to-safe-task`
> skill applies this rule interactively.
