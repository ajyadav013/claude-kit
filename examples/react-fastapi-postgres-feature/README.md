# Worked example — "Mark a task complete"

> ⚠️ **ILLUSTRATIVE / SYNTHETIC** — a hand-authored walkthrough, not a captured run. Stack: React +
> Python/FastAPI + PostgreSQL. Profile: `standard` (team scope). See [`../README.md`](../README.md).

A deliberately small feature — add the ability to mark a to-do task **complete** (a new `PATCH`
endpoint + a checkbox in the list) — taken through the full `standard` pipeline so you can see what
each stage emits and how the gates between them behave.

## The pipeline this run exercised

`standard` profile gates (from `catalog/profiles.yaml`): **spec-complete → em-approved → code-review →
build-green → test-coverage → security-clear**, plus **contract-clear** (this is an API-exposing
FastAPI stack, so the breaking-change gate is active; brief #2 P0-1). Each gate is owned by an agent
and passes only at **zero Critical/High/Medium** findings (`.claude/rules/quality-gates.md`).

## Read in order

| File | Stage | Owner agent(s) |
|------|-------|----------------|
| [`01-request.md`](01-request.md) | The raw human request | — |
| [`02-feature-spec.md`](02-feature-spec.md) | Feature spec + acceptance criteria (`spec-complete`) | `spec-doc-writer`, reviewed by `em-reviewer` |
| [`03-story-breakdown.md`](03-story-breakdown.md) | Coverage gate: every criterion → a story (1f) | `story-planner` |
| [`04-gate-verdicts.md`](04-gate-verdicts.md) | Every gate's verdict, incl. one defect-loop cycle | `sdlc-code-reviewer`, `merge-reviewer`, testers, `security-reviewer`, `devils-advocate` |
| [`05-sample-pr.diff`](05-sample-pr.diff) | The (synthetic) PR diff that resulted | `pr-raiser` |

## What to notice

- **Implementation didn't start until the spec was approved** and every acceptance criterion had a
  story (the `story-planner` coverage gate, stage 1f).
- **A gate caught a real defect** (`04-gate-verdicts.md`, test-coverage lane) — only the affected lane
  re-ran (the defect loop), not the whole pipeline.
- **A unanimous PASS triggered the `devils-advocate`** before the gate counted (anti-sycophancy).
- **`contract-clear` ran** because the change adds a new endpoint — an *additive* change is Low/Cosmetic,
  so it passed without a migration note; a *breaking* change would have required one + a version bump.
