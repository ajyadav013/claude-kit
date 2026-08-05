"""Join each scenario's workspace verdict with how its session ended, and re-score the run.

`spec_task.py` answers "is the end state correct". `transcript_stop.py` answers "was the session
allowed to produce one". Neither is sufficient alone, and the second only matters when the first
says no -- a session that did the work correctly needs no excuse, so its transcript is not consulted
for the verdict.

The combined score is deliberately three-valued:

  PASS          the workspace oracle passed. The transcript changes nothing.
  FAIL          the workspace oracle failed and the session was free to succeed.
  NOT_MEASURED  the workspace oracle failed, but the session was structurally prevented from
                proceeding -- it explored, planned, asked for the approval the kit's own rules
                require, and the headless harness refused because there is no human. Excluded from
                the denominator, counted in neither column.

NOT_MEASURED IS NOT A PASS, and the distinction is the whole point. Scoring a blocked run as success
would make this a checker that cannot fail; scoring it as failure is what F-081 found the harness
already doing. The honest report is that the instrument could not run the experiment.

`PROCEEDED_PAST_PLAN_GATE` goes the other way: the workspace may have passed, but the session got
there through a refused plan gate. That is surfaced as a separate flag rather than folded into the
score, because it is a finding about the session's conduct, not about the end state.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
RUNS = REPO / ".claude/state/full-self-evaluation/raw/task-runs"

sys.path.insert(0, str(REPO / "tests/evals/e2e/oracles"))
from transcript_stop import classify  # noqa: E402

# Transcript outcomes that justify withdrawing a workspace FAIL. Kept as an explicit set so adding
# one is a visible decision rather than a widened condition buried in an `if`.
EXCUSING = {"BLOCKED_BY_HARNESS"}
VOIDING = {"VOID_TRANSPORT"}


def score(run: Path) -> dict:
    verdict_file = run / "oracle-verdict.json"
    workspace_pass = None
    if verdict_file.is_file():
        try:
            workspace_pass = bool(json.loads(verdict_file.read_text())["pass"])
        except (json.JSONDecodeError, KeyError):
            workspace_pass = None

    t = classify(run)
    outcome = t["outcome"]

    if workspace_pass is None:
        combined = "NOT_MEASURED"
        why = "no workspace verdict recorded; nothing to score"
    elif workspace_pass:
        combined = "PASS"
        why = "workspace oracle passed"
    elif outcome in VOIDING:
        combined = "NOT_MEASURED"
        why = f"run did not complete on its own terms: {t['why']}"
    elif outcome in EXCUSING:
        combined = "NOT_MEASURED"
        why = f"workspace failed, but the session was blocked: {t['why']}"
    else:
        combined = "FAIL"
        why = f"workspace oracle failed and the session was free to proceed ({outcome})"

    return {
        "scenario": run.parent.name,
        "run": run.name,
        "workspace_pass": workspace_pass,
        "transcript_outcome": outcome,
        "combined": combined,
        "why": why,
        "conduct_flag": outcome if outcome == "PROCEEDED_PAST_PLAN_GATE" else None,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="")
    ap.add_argument("--prefix", default="baseline-")
    a = ap.parse_args()

    rows = []
    for scenario in sorted(RUNS.iterdir()) if RUNS.is_dir() else []:
        if not scenario.is_dir() or not scenario.name.startswith("SC-"):
            continue
        for run in sorted(scenario.glob(f"{a.prefix}*")):
            rows.append(score(run))

    counts: dict[str, int] = {}
    for r in rows:
        counts[r["combined"]] = counts.get(r["combined"], 0) + 1

    print(f"{'scenario':9s} {'workspace':>10s} {'transcript':>26s}  combined")
    print("-" * 76)
    for r in rows:
        print(
            f"{r['scenario']:9s} {str(r['workspace_pass']):>10s} "
            f"{r['transcript_outcome']:>26s}  {r['combined']}"
        )
    print("-" * 76)
    print("  ".join(f"{k}={v}" for k, v in sorted(counts.items())))

    measured = counts.get("PASS", 0) + counts.get("FAIL", 0)
    if measured:
        print(
            f"measured {measured} of {len(rows)} runs; "
            f"pass rate over MEASURED runs = {counts.get('PASS', 0)}/{measured}"
        )
    flags = [r for r in rows if r["conduct_flag"]]
    if flags:
        print(f"\nconduct flags ({len(flags)}):")
        for r in flags:
            print(f"  {r['scenario']}: {r['conduct_flag']}")

    if a.out:
        Path(a.out).write_text(
            json.dumps({"counts": counts, "rows": rows}, indent=2) + "\n",
            encoding="utf-8",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
