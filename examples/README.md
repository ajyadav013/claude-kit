# Examples

Worked, end-to-end illustrations of what a claude-kit `/sdlc` run produces — the artifacts that land
and the gate verdicts between phases.

These docs are repo reference (like `docs/`). They are **not** part of the scaffolded payload — nothing
here is installed into your project or bundled into the wheel.

## ⭐ A real run — executed, not illustrated

**Start here.** [`real-run/`](real-run/) is a genuine run: a real sample app was built, **real
claude-kit agents** were spawned against it, and every gate verdict is backed by the **actual command
output** it cites (`real-run/evidence/`). The headline: a blind code review returned PASS, then the
kit's `devils-advocate` found **two real Critical bugs the review missed** — both reproduced, fixed,
and covered by new regression tests (12 → 14 tests green). It spans six scenarios including edge cases,
a security block, and an out-of-scope request the kit **refuses**.

| Example | What it shows |
|---------|---------------|
| [`real-run/`](real-run/) | **Real** end-to-end run: real sample app, real agents, real captured evidence — 6 scenarios (standard feature · Devil's-Advocate catch · breaking change · security block · test-coverage defect loop · out-of-scope refusal) |

## Synthetic walkthrough

> ⚠️ **ILLUSTRATIVE / SYNTHETIC.** The walkthrough below is hand-authored to teach the *shape* of a
> run — it is **not** the captured transcript of a real execution, and the diff is not from a real
> commit. It depicts the **default stack** (React + Python/FastAPI + PostgreSQL) on the **`standard`**
> profile, team scope. Treat it as a map; for a recording, see [`real-run/`](real-run/) above.

| Example | Stack · profile | What it shows |
|---------|-----------------|---------------|
| [`react-fastapi-postgres-feature/`](react-fastapi-postgres-feature/) | React + FastAPI + Postgres · `standard` | A small feature end to end: request → spec → story breakdown → gate verdicts (incl. one defect-loop cycle) → sample PR diff |

Read them in file-number order (`01-…` → `05-…`). The narrative tying them together is in each
example's own `README.md`.
