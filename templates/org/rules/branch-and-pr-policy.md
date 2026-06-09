# Branch & PR Policy

Code reaches the main line through one path only: a feature branch, a small reviewed pull request, and
a merge after approval. Never commit straight to `main`/`master`, and never push to it directly — the
`guard-push-main` hook blocks it, but the policy holds even where no hook runs.

## Always work on a branch

1. **Branch from the main line** for every change — features, fixes, docs, config. One branch per task.
2. **Name it for the work** — a short, descriptive slug (e.g. `feat/<thing>`, `fix/<thing>`); avoid
   long-lived shared branches that drift.
3. **Keep `main` releasable.** It builds, passes the project's test runner and linter, and is never the
   target of a direct commit or push.

## Keep PRs small and single-purpose

- **One concern per PR.** A PR does one thing — don't bundle a refactor, a feature, and a config change.
  If it grows, split it.
- **Smallest reviewable diff** that delivers the change; large PRs hide defects and slow review.
- **No drive-by edits.** Touch only what the task needs (see the surgical-changes rule of conduct).

## Write a clear PR

Every PR description states, in plain language:

1. **What & why** — the change and the reason for it, not just the mechanism.
2. **Scope** — what it touches, and what it deliberately leaves out.
3. **How it was verified** — tests, checks, or observable behavior proving it works.
4. **Checklist** — gates passed, docs updated, no secrets, breaking changes called out.

## Review before merge

- **Human review is required** before merge — at least one approval. Code review is a quality gate, not
  a formality (`.claude/rules/quality-gates.md`).
- **Quality gates pass first.** Build, linter, tests, and security checks are green before review counts.
- **Merging is an outward-facing, hard-to-reverse action** — it stays within the granted autonomy level
  (`.claude/rules/autonomy-levels.md`); opening or merging to a protected branch needs human approval.

> Part of claude-kit's organization capability layer. Enforced by the `guard-push-main` hook. The
> `/git-workflow-and-versioning` skill drives branching and PRs interactively, and the `pr-raiser` agent
> opens the PR. Cross-refs `.claude/rules/quality-gates.md`, `.claude/rules/autonomy-levels.md`.
