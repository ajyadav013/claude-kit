"""Derive Tier B manifest state from the grade files, instead of marking it by hand.

Coverage was being updated from an ad-hoc "these ones passed" list written per batch. That list
and the evidence disagreed: `skill:backlog` was marked measured while its only grade row says
MISSED. A number that can drift from its own evidence is not a measurement, so this recomputes
every Tier B row from `raw/tier-b/runs-*/grades.json` on every run and overwrites the manifest.

Three states, because two cannot hold the distinction that matters:

  measured    INVOKED or NAMED -- criterion 1 satisfied, the strongest and the weaker evidence
  attempted   MISSED or INCONCLUSIVE -- the probe ran and yielded no criterion-1 pass
  unprobed    no grade row exists

`attempted` is NOT `measured`: a skill that never triggered produced no evidence about the other
criteria Tier B claims (2, 9, 11, 13, 14), so counting it as covered would overstate the run.
It is also not `unprobed`: re-probing it identically would just reproduce the same miss. Keeping
them apart is what lets the batch builder skip attempted rows while coverage still refuses to
credit them.

Usage: tier_b_reconcile.py [--apply]   (default is a dry run that prints the delta)
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
STATE = REPO / ".claude/state/full-self-evaluation"
RUNS = STATE / "raw/tier-b"

# strongest first -- a skill probed in several batches is credited with its best outcome
RANK = ["INVOKED", "NAMED", "INCONCLUSIVE", "SUBSTITUTED", "MISSED"]
MEASURED = {"INVOKED", "NAMED"}


def collect(runs: pathlib.Path | None = None) -> dict[str, dict]:
    """Best outcome per component id across every graded batch."""
    runs = runs or RUNS
    best: dict[str, dict] = {}
    # "runs-*" silently skipped the FIRST batch, whose directory is plain `runs` -- 11 skills
    # then looked like marks with no evidence. The glob must match both forms.
    for g in sorted(runs.glob("runs*/grades.json")):
        rows = json.loads(g.read_text(encoding="utf-8"))["rows"]
        for r in rows:
            outcome = r.get("outcome")
            if outcome is None:  # false-trigger rows carry no outcome
                continue
            if outcome not in RANK:
                raise SystemExit(f"unknown outcome {outcome!r} in {g}")
            prev = best.get(r["id"])
            if prev is None or RANK.index(outcome) < RANK.index(prev["outcome"]):
                best[r["id"]] = {
                    "outcome": outcome,
                    "batch": r["batch"],
                    "run": g.parent.name,
                }
    return best


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    # A checker that can only run against the live state directory cannot be mutation-tested,
    # and an untestable checker is the thing this program keeps finding to be wrong.
    ap.add_argument(
        "--state", default="", help="state dir to reconcile (default: the live one)"
    )
    a = ap.parse_args()

    state = pathlib.Path(a.state) if a.state else STATE
    path = state / "component-manifest.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    comps = doc["components"]
    best = collect(state / "raw/tier-b")

    changed: list[tuple] = []
    unsupported: list[str] = []
    counts = {"measured": 0, "attempted": 0, "unprobed": 0}
    for c in comps:
        if c["tier"] != "B":
            continue
        got = best.get(c["id"])
        if got is None:
            # A row marked done with no grade row is a claim with nothing behind it. It may be
            # legitimate -- some Tier B skills get measured by a full Tier A scenario instead --
            # so having OTHER evidence is accepted, and having none at all is an error rather
            # than something to quietly leave in place.
            # The waiver must be a TRAILING comment: the scanner reads the span of the
            # flagged expression, so a note on the line above is invisible to it (E-043).
            if c.get("dynamic_done") is True and not c.get(
                "dynamic_evidence"
            ):  # absent-ok: no key and an empty key both mean nothing backs the mark
                unsupported.append(c["id"])
            counts["unprobed"] += 1
            continue
        measured = got["outcome"] in MEASURED
        counts["measured" if measured else "attempted"] += 1
        was = c.get("dynamic_done")
        if was is not measured or c.get("dynamic_outcome") != got["outcome"]:
            changed.append((c["id"], was, measured, got["outcome"]))
        if a.apply:
            c["dynamic_done"] = measured
            c["dynamic_attempted"] = True
            c["dynamic_outcome"] = got["outcome"]
            c["dynamic_evidence"] = f"{got['run']}/{got['batch']}"

    for cid, was, now, outcome in changed:
        print(f"  {cid}: dynamic_done {was!r} -> {now!r}  ({outcome})")
    print(f"tier B: {counts}")
    if unsupported:
        print(f"UNSUPPORTED marks (done, no evidence of any kind): {unsupported}")
        return 1
    if not a.apply:
        print("dry run; pass --apply to write")
        return 0

    path.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
    total = len(comps)
    done = sum(1 for c in comps if c.get("dynamic_done") is True)
    print(f"written. dynamic coverage {done}/{total} = {round(done / total * 100, 1)}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
