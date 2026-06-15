# Examples

Worked, end-to-end illustrations of what a claude-kit `/sdlc` run produces — the artifacts that land
and the gate verdicts between phases.

> ⚠️ **ILLUSTRATIVE / SYNTHETIC.** These files are a hand-authored walkthrough written to teach the
> shape of a run — they are **not** the captured transcript of a real execution, and the diff is not
> from a real commit. They depict the **default stack** (React + Python/FastAPI + PostgreSQL) on the
> **`standard`** profile, team scope. Your own runs will differ; treat these as a map, not a recording.

These docs are repo reference (like `docs/`). They are **not** part of the scaffolded payload — nothing
here is installed into your project or bundled into the wheel.

## Walkthroughs

| Example | Stack · profile | What it shows |
|---------|-----------------|---------------|
| [`react-fastapi-postgres-feature/`](react-fastapi-postgres-feature/) | React + FastAPI + Postgres · `standard` | A small feature end to end: request → spec → story breakdown → gate verdicts (incl. one defect-loop cycle) → sample PR diff |

Read them in file-number order (`01-…` → `05-…`). The narrative tying them together is in each
example's own `README.md`.
