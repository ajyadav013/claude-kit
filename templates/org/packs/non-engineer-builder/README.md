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
This pack bundles components that already ship with claude-kit (reused, not duplicated) plus several
added by the org layer. It does not introduce competing agents.

| Need | Use |
|------|-----|
| Turn a vague request into a safe, scoped task | `/prompt-to-safe-task` (see `prompt-to-task-conversion.md`) |
| Refine a rough idea into something concrete | `/idea-refine` → `pm-copilot` |
| Get interviewed to surface what's really needed | `/interview-me` (see `ambiguity-resolution.md`) |
| Turn an idea into a feature brief | `/feature-from-idea` → `pm-copilot` |
| Build a quick prototype within safe limits | `founder-prototype-agent` (`prototype-boundaries.md`) |
| Promote a prototype toward real, reviewable work | `/prototype-to-production` → `internal-tools-builder` |
| Build a small internal tool | `internal-tools-builder` (plan + delegate only) |
| Turn a customer ticket into a fix | `/customer-issue-to-fix` → `support-ticket-engineer` |
| Shape a data/reporting workflow | `data-workflow-agent` (design only) |
| Learn what a repo does before changing it | `/repo-onboarding` → `Explore` |
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
/prototype-to-production "Make my onboarding-checklist prototype real"   # → scoped tasks + tests + approval
/customer-issue-to-fix "Users say the export button does nothing"        # → reproduced issue → safe fix → review
/feature-from-idea "Let operators bulk-tag records in the admin view"    # → clarified brief → scoped task
```

## Autonomy & risk
Default **high**: this pack assumes the operator can't fully vet the change, so the bar is deliberately
strict. Personas **plan and delegate only**; building is routed through the engineering review chain
with tests and explicit human approval. Anything touching a sensitive area (auth, payments, secrets,
production data, migrations, infrastructure) always requires a plan, human sign-off, and security +
test review before any code is written (`risk-classification.md`, `autonomy-levels.md`).
