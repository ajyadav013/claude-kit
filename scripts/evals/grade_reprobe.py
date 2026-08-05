"""Grade the description-rewrite re-probe wave against its own preserved baseline.

Ten skills had their frontmatter descriptions rewritten because a baseline probe wave showed the
picker was not selecting them. This asks whether that actually changed anything, holding everything
else fixed: the SAME prompt files the baseline used, the same probe script, the same profile, the
same withheld rules. Change the instrument and an improvement could be the instrument.

THE VOID RULE IS THE POINT OF THIS FILE. A `claude -p` child that dies on "API Error: the socket
connection was closed unexpectedly" invoked no skill, and a naive grader reads that empty
`skills_invoked` as a miss. On the first wave that turned three transport failures into one reported
REGRESSION and one extra miss -- an accusation manufactured from an absence, which is the exact bug
this programme keeps finding in other people's code. A run that did not complete is VOID: it is
re-run, never graded.

One baseline PASS (`load-testing`) is deliberately in the set as the no-regression control. A
rewrite that lifts the misses while breaking the one that already worked has not improved anything.
"""

from __future__ import annotations

import argparse
import glob
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
STATE = REPO / ".claude/state/full-self-evaluation"
OUT = STATE / "raw/tier-b/reprobe-desc"
# Label prefixes tried for each cell, in order. Later entries are re-runs of cells the earlier ones
# voided, so the FIRST attempt that completed on its own terms is the one graded.
PREFIXES = ["reprobe", "reprobe2"]


def _void_reason(run: Path) -> str | None:
    """Return why this run cannot be graded, or None if it completed on its own terms."""
    probe = run / "probe.json"
    if not probe.is_file():
        return "no probe.json: the probe did not finish writing a result"
    doc = json.loads(probe.read_text(encoding="utf-8"))
    if doc.get("session_rc") not in (0, None):
        detail = ""
        session = run / "session.jsonl"
        if session.is_file():
            for raw in session.read_text(errors="replace").splitlines():
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    ev = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if ev.get("type") == "result" and ev.get("is_error"):
                    detail = str(ev.get("result") or "")[:160]
        return (
            f"session_rc={doc['session_rc']}: {detail or 'no result detail recorded'}"
        )
    return None


def _runs(skill: str, rep: int) -> list[Path]:
    """Every attempt at this cell, newest last. `reprobe2-` are serial re-runs of voided cells."""
    found: list[Path] = []
    for pref in PREFIXES:
        found += [
            Path(x) for x in sorted(glob.glob(str(OUT / f"{pref}-{skill}-r{rep}-*")))
        ]
    return found


def grade(skill: str, rep: int) -> dict:
    attempts = _runs(skill, rep)
    if not attempts:
        return {"graded": False, "why": "no run recorded for this cell"}
    voids = []
    for run in attempts:
        reason = _void_reason(run)
        if reason:
            voids.append({"run": run.name, "why": reason})
            continue
        doc = json.loads((run / "probe.json").read_text(encoding="utf-8"))
        invoked = doc.get("skills_invoked") or []
        return {
            "graded": True,
            "run": run.name,
            "hit": skill in invoked,
            "skills_invoked": invoked,
            "voided_attempts": voids,
        }
    return {"graded": False, "why": "every attempt was void", "voided_attempts": voids}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--baseline", default=str(REPO / ".claude/tmp/reprobe-baseline.json")
    )
    ap.add_argument(
        "--dir", default="", help="probe output dir (default: the first wave's)"
    )
    ap.add_argument(
        "--prefixes",
        default="",
        help="comma-separated label prefixes, first-completed wins",
    )
    ap.add_argument("--out", default="")
    a = ap.parse_args()

    global OUT, PREFIXES
    if a.dir:
        OUT = Path(a.dir)
    if a.prefixes:
        PREFIXES = [x.strip() for x in a.prefixes.split(",") if x.strip()]

    base = json.loads(Path(a.baseline).read_text(encoding="utf-8"))
    rows = {}
    for skill in sorted(base):
        cells = [grade(skill, r) for r in (1, 2)]
        graded = [c for c in cells if c["graded"]]
        before = bool(base[skill]["baseline_hit"])
        if not graded:
            verdict = "NOT_MEASURED"
        else:
            after = any(c["hit"] for c in graded)
            if before and not after:
                verdict = "REGRESSION"
            elif after and not before:
                verdict = "IMPROVED"
            elif after and before:
                verdict = "HELD"
            else:
                verdict = "STILL_MISSING"
        rows[skill] = {
            "baseline_hit": before,
            "after_hits": [c.get("hit") for c in graded],
            "verdict": verdict,
            "cells": cells,
        }

    counts: dict[str, int] = {}
    for r in rows.values():
        counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1

    print(f"{'skill':32s} {'base':>5s} {'after':>16s}  verdict")
    print("-" * 76)
    for skill, r in rows.items():
        print(
            f"{skill:32s} {str(r['baseline_hit']):>5s} {str(r['after_hits']):>16s}  {r['verdict']}"
        )
    print("-" * 76)
    print("  ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    voided = [
        (s, c["run"], c["why"])
        for s, r in rows.items()
        for cell in r["cells"]
        for c in cell.get("voided_attempts", [])
    ]
    if voided:
        print(f"\nvoided runs (re-run, NOT graded as misses): {len(voided)}")
        for s, run, why in voided:
            print(f"  {s}: {run} -- {why}")

    doc = {"counts": counts, "rows": rows}
    if a.out:
        Path(a.out).write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    # A wave with an ungradeable cell has not answered the question it was run to answer.
    return 1 if counts.get("NOT_MEASURED") or counts.get("REGRESSION") else 0


if __name__ == "__main__":
    raise SystemExit(main())
