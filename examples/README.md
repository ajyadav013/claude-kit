# Examples

Worked, end-to-end illustrations of what a claude-kit `/sdlc` run produces — the artifacts that land
and the gate verdicts between phases.

These docs are repo reference (like `docs/`). They are **not** part of the scaffolded payload — nothing
here is installed into your project or bundled into the wheel.

## ⭐ A real run — captured, not illustrated

**Start here.** [`real-run/`](real-run/) is a genuine run, produced by the kit's own
[`capture-sdlc-run.sh`](../scripts/capture-sdlc-run.sh) harness: a real `DELETE /tasks/{id}` feature
driven through every gate on a freshly-scaffolded **Go / net-http** project. The headline — four
reviewers returned a unanimous PASS, then the kit's `devils-advocate` found and **reproduced** a real
Medium bug they missed (id aliasing), the deterministic gate **refused to advance** while it was open,
and a fix + regression test closed it. It includes the verbatim harness bundle, the agent verdicts, the
reproducible Go source, and a genuine terminal recording of the gate checks.

| Example | What it shows |
|---------|---------------|
| [`real-run/`](real-run/) | **Real**, harness-captured run: spec → gates → `devils-advocate` defect loop → fix, with the actual `pipeline-snapshot.json`, agent verdicts, diff, and an asciicast of the green gate checks |

## Synthetic walkthrough

> ⚠️ **ILLUSTRATIVE / SYNTHETIC.** The walkthrough below is hand-authored to teach the *shape* of a
> run — it is **not** the captured transcript of a real execution, and the diff is not from a real
> commit. It depicts the **default stack** (React + Python/FastAPI + PostgreSQL) on the **`standard`**
> profile, team scope. Treat it as a map; for a recording, see [`real-run/`](real-run/) above.

| Example | Stack · profile | What it shows |
|---------|-----------------|---------------|
| [`react-fastapi-postgres-feature/`](react-fastapi-postgres-feature/) | React + FastAPI + Postgres · `standard` | A small feature end to end: request → spec → story breakdown → gate verdicts (incl. one defect-loop cycle) → sample PR diff |

Read it in file-number order (`01-…` → `05-…`). The narrative is in the example's own `README.md`.
