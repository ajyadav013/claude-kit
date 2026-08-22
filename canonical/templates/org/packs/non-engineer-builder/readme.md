# Non-Engineer Builder

Safe vibe-coding for people who don't write code day to day: turn a request into a clarified, scoped,
approval-gated task, build a prototype or internal tool within tight boundaries, and never ship a
sensitive or large change without tests and a human saying yes.

**Primary teams:** Product · Design · Founders · Support · Data · **Default risk:** high · **Manifest:** `pack.yaml`

## Who uses it
PMs, founders, designers, operators, support agents, and data folks building prototypes or internal
tools without an engineer in the loop. The personas here **plan and delegate** — they clarify, scope,
and route work behind approval gates; they never write or run code themselves.

## Role → component mapping
This pack bundles components that already ship with {{ provider.executable.cli }} (reused, not duplicated) plus several
added by the org layer. It does not introduce competing agents.

| Need | Use |
|------|-----|
| Turn a vague request into a safe, scoped task | `command://prompt-to-safe-task` (see `prompt-to-task-conversion.md`) |
| Refine a rough idea into something concrete | `command://idea-refine` → `pm-copilot` |
| Get interviewed to surface what's really needed | `command://interview-me` (see `ambiguity-resolution.md`) |
| Turn an idea into a feature brief | `command://feature-from-idea` → `pm-copilot` |
| Build a quick prototype within safe limits | `founder-prototype-agent` (`prototype-boundaries.md`) |
| Promote a prototype toward real, reviewable work | `command://prototype-to-production` → `internal-tools-builder` |
| Build a small internal tool | `internal-tools-builder` (plan + delegate only) |
| Turn a customer ticket into a fix | `command://customer-issue-to-fix` → `support-ticket-engineer` |
| Shape a data/reporting workflow | `data-workflow-agent` (design only) |
| Learn what a repo does before changing it | `command://repo-onboarding` → a read-only research role |
| Decide how risky a change is | `risk-classifier` agent (`risk-classification.md`) |

## Rules it leans on
`non-engineer-safe-coding.md`, `prompt-to-task-conversion.md`, `prototype-boundaries.md`,
`ambiguity-resolution.md`, `autonomy-levels.md`, and `risk-classification.md` for tiering.

## Hooks it expects
`warn-sensitive-files` (flags edits to secrets/config/auth/data areas), `warn-large-edits` (keeps a
plan-only flow from quietly turning into a big change), and `warn-missing-tests` (blocks "done" until
the project's test runner has coverage for the change).

## Examples
```
Use `{{skill_invocation:skill://prototype-to-production}}` to turn an onboarding-checklist prototype into scoped, tested, approval-gated work.
Use `{{skill_invocation:skill://customer-issue-to-fix}}` to reproduce and safely route a broken export-button report.
Use `{{skill_invocation:skill://feature-from-idea}}` to turn a bulk-tagging idea into a clarified brief and scoped task.
```

## Autonomy & risk
Default **high**: this pack assumes the operator can't fully vet the change, so the bar is deliberately
strict. Personas **plan and delegate only**; building is routed through the engineering review chain
with tests and explicit human approval. Anything touching a sensitive area (auth, payments, secrets,
production data, migrations, infrastructure) always requires a plan, human sign-off, and security +
test review before any code is written (`risk-classification.md`, `autonomy-levels.md`).
