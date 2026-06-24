# A real `/sdlc` run — executed, not illustrated

The sibling example ([`../react-fastapi-postgres-feature/`](../react-fastapi-postgres-feature/)) is a
**synthetic** walkthrough — hand-written to show the shape of the pipeline. **This one is real.** A
genuine sample app was built, real claude-kit agents were run against it, and every gate verdict here
is backed by the actual command output it cites (`evidence/`). Nothing below is fabricated — which is
the whole point of the kit's [§2.5 evidence rule](../../rules/quality-gates.md).

## The headline

A blind code review of the sample app returned **PASS**. Its 12 tests were green and `ruff` was clean.
Then the kit's **`devils-advocate`** agent — the one spawned precisely *because* a verdict looks
comfortably clean — read the same code and found **two real Critical bugs the review missed**:

- `POST /tasks` with a non-object JSON body (e.g. an array) crashed the handler (`AttributeError`).
- A non-numeric `Content-Length` header crashed the handler (`ValueError`).

Both were **reproduced** (`evidence/02-bugs-before.txt`), **fixed**, and covered by **two new
regression tests** — the suite went 12 → **14 green** (`evidence/02-pytest-after.txt`). That is the
defect loop working on real code. See [`scenarios/02-devils-advocate-catch.md`](scenarios/02-devils-advocate-catch.md).

## How to reproduce

The sample app has **zero third-party dependencies** (Python standard library only), so the gate
checks run anywhere with `pytest` + `ruff` available:

```bash
# from the repo root, with the kit's dev env (or any venv with pytest + ruff):
bash examples/real-run/sample-app/run-checks.sh
# or directly:
python -m pytest examples/real-run/sample-app/tests -v
ruff check examples/real-run/sample-app/tasktracker examples/real-run/sample-app/tests
```

Captured output from the real runs lives in [`evidence/`](evidence/) (lint, green suite, the two
crash reproductions, the defect-loop RED→GREEN, the breaking-change diff, and the security scan).

## Scenarios

Each scenario exercises a different part of the pipeline, including edge cases and an out-of-scope
request the kit is supposed to **refuse**.

| # | Scenario | Exercises | Real evidence | Outcome |
|---|----------|-----------|---------------|---------|
| [01](scenarios/01-standard-feature.md) | Standard feature | spec → story → **code-review** → **build-green** → **test-coverage** → **acceptance** | `evidence/01-lint.txt`, `evidence/01-pytest-green.txt` | ✅ all gates pass; acceptance **ACCEPT** |
| [02](scenarios/02-devils-advocate-catch.md) | **Devil's Advocate catches what review missed** | blind review → **`devils-advocate`** → defect loop → fix + regression tests | `evidence/02-bugs-before.txt`, `02-fix.diff`, `02-pytest-after.txt` | 🛠️ 2 Criticals found & fixed; 12 → 14 green |
| [03](scenarios/03-breaking-change.md) | Backward-incompatible API change | **`contract-clear`** gate | `evidence/03-breaking.diff`, `03-pytest-red.txt` | 🚫 gate blocks; migration + version bump required |
| [04](scenarios/04-security-block.md) | Planted secret + unauth admin action | **`secret-scanner`** / **Security Clear** (auto-Critical) | `evidence/04-security-fail.txt`, `04-security-pass.txt` | 🚫 blocked, then cleared after fix |
| [05](scenarios/05-test-coverage-gate.md) | Test-coverage gate catches a real defect | **build-green** + **test-coverage** + defect loop | `evidence/05-pytest-red.txt`, `05-pytest-green.txt` | 🔴→🟢 3 failed → 12 passed; gate blocks until green |
| [06](scenarios/06-out-of-scope-refusal.md) | Out-of-scope / restricted request | **`risk-classifier`** + agent-guardrails | (verdict in the doc) | 🛑 classified **RESTRICTED**, refused |

## What's genuine vs. authored

To keep the demonstration honest about its own provenance:

- **Real agents, real code.** The artifacts in scenarios 01–06 from `risk-classifier`,
  `sdlc-code-reviewer`, `devils-advocate`, `security-reviewer`, and `acceptance-reviewer` were
  produced by spawning those actual claude-kit agents (read-only) against this sample. Their findings
  cite real `file:line`.
- **Real tool output.** Every PASS/FAIL that depends on a check (pytest, ruff, the secret scan, the
  breaking-change diff) is backed by a command that was actually run; the captured output is in
  `evidence/`. The orchestration (sequencing, gate decisions) was driven in a single session.
- **Not included:** an asciinema/screencast of a live `/sdlc` session — that's a terminal recording,
  best captured interactively with [`scripts/capture-sdlc-run.sh`](../../scripts/capture-sdlc-run.sh).

Environment of record: Python 3.14.6, pytest 9.0.3, ruff 0.15.x.
