"""The single writer of `dynamic_done`, deriving it per tier from evidence (F-077).

WHY THIS EXISTS. `dynamic_done` had about ten writers with unreconciled definitions, so the
headline coverage number depended on which script ran last. Three mutually inconsistent totals were
live at once (manifest 428, component-coverage top level 69, its own by_type sum 97), and re-running
the tier-blind `derive-dynamic-coverage.py` -- rubric v1, written before the turn-52 re-tiering --
silently collapsed the manifest from 428 done to 69. Nothing primary was lost, because the evidence
pointers survived; what was lost was the derived verdict layer, which had never been captured in a
re-runnable form. This file is that form.

THE RULE PER TIER IS NOT INVENTED HERE. It is read straight off the frozen predicate in
`dynamic-tiering.md`, which was written before assignment specifically so it could not be tuned to
a number:

  Tier A  "answers all 14 criteria and concedes nothing"
          -> done when no required measure is missing AND the trial count is met.
  Tier B  answers 1, 2, 9, 11, 13, 14 and 7-wrt-triggering; concedes the rest
          -> done when a graded probe recorded a sound outcome. Per the turn-72 amendment an
             INVOKED/NAMED is sound but a MISSED is NOT evidence, so a MISSED never marks done.
  Tier C  answers 13, 14, structural integrity and reachability; concedes 1-12
          -> done when the static checks pass AND a reachability proof exists. Tier C is not an
             exemption, so a component with no reach proof stays not-done however static-clean.

Two properties matter more than the arithmetic:

  1. It is DRY-RUN BY DEFAULT. A script whose name reads as a measurement must not mutate the thing
     it measures as a side effect of being run -- that is precisely how the manifest was damaged.
  2. It never marks a component done without naming the evidence that did it. A mark whose
     provenance cannot be printed is the hand-maintained boolean this replaces.
"""

import argparse
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
STATE = HERE.parents[1] / ".claude/state/full-self-evaluation"
sys.path.insert(0, str(HERE))

from tier_b_reconcile import MEASURED, collect  # noqa: E402


def tier_a(c: dict) -> tuple[bool, str]:
    missing = c.get("dynamic_measures_missing")
    if missing is None:
        return False, "no measure record -- evidence never scanned"
    trials = c.get("dynamic_trials") or 0
    need = c.get("dynamic_trials_required") or 1
    if missing:
        return False, f"missing measures {missing}"
    if trials < need:
        return False, f"{trials}/{need} trials"
    return True, f"all required measures satisfied over {trials} trial(s)"


def tier_b(c: dict, graded: dict) -> tuple[bool, str]:
    got = graded.get(c["id"])
    if got is None:
        # tier_b_reconcile.py's own policy: some Tier B components are measured by a full Tier A
        # scenario instead of a batched probe, and that is MORE evidence than this tier asks for,
        # not less. Accepted only when the record says so explicitly and carries a passing verdict
        # -- and any deviation on that run is repeated here rather than quietly dropped.
        ev = c.get("dynamic_evidence")
        passing = [
            e
            for e in (ev if isinstance(ev, list) else [])
            if isinstance(e, dict) and e.get("verdict") == "PASS"
        ]
        if c.get("dynamic_outcome") == "MEASURED_BY_TIER_A_SCENARIO" and passing:
            dev = " (DEVIATING run)" if any(e.get("deviating") for e in passing) else ""
            return True, f"measured by Tier A scenario {passing[0]['run']}{dev}"
        return False, "no graded probe"
    if got["outcome"] not in MEASURED:
        # The turn-72 amendment (E-056): batching suppresses the behaviour being measured, so a
        # MISSED is a referral to a standalone probe, never a criterion-1 defect and never a mark.
        return False, f"outcome {got['outcome']} is a referral, not a measurement"
    return True, f"{got['outcome']} in {got['run']}/{got['batch']}"


def tier_c(c: dict, reach: dict) -> tuple[bool, str]:
    if c.get("static_done") is not True:
        return False, "static checks not passing"
    got = reach.get(c["id"])
    if not got:
        return False, "no reachability proof -- ships but nothing reads it"
    return True, f"static clean + reachable ({got})"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="write; default is a dry run")
    ap.add_argument("--state", default="", help="state dir (default: the live one)")
    a = ap.parse_args()

    state = pathlib.Path(a.state) if a.state else STATE
    path = state / "component-manifest.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    comps = doc["components"]

    graded = collect(state / "raw/tier-b")
    reach_doc = json.loads((state / "tier-c-reach.json").read_text(encoding="utf-8"))
    reach = {
        r["id"]: r.get("method", "proven")
        for r in reach_doc["rows"]
        if r.get("proven") is True
    }

    RULES = {
        "A": tier_a,
        "B": lambda c: tier_b(c, graded),
        "C": lambda c: tier_c(c, reach),
    }
    stats: dict[str, dict[str, int]] = {
        t: {"n": 0, "done": 0, "flipped_on": 0, "flipped_off": 0} for t in RULES
    }
    changes = []
    verdict: dict[str, bool] = {}
    for c in comps:
        t = c["tier"]
        done, why = RULES[t](c)
        verdict[c["id"]] = done
        was = c.get("dynamic_done")
        stats[t]["n"] += 1
        stats[t]["done"] += int(done)
        if was is not done:
            stats[t]["flipped_on" if done else "flipped_off"] += 1
            changes.append((c["id"], t, was, done, why))
        if a.apply:
            c["dynamic_done"] = done
            c["dynamic_done_basis"] = f"tier {t}: {why}"

    for cid, t, was, now, why in changes[:40]:
        print(f"  [{t}] {cid}: {was!r} -> {now!r}  ({why})")
    if len(changes) > 40:
        print(f"  ... and {len(changes) - 40} more")

    print()
    total_done = sum(s["done"] for s in stats.values())
    for t, s in stats.items():
        print(
            f"tier {t}: {s['done']}/{s['n']} done  (+{s['flipped_on']} / -{s['flipped_off']})"
        )
    req = [c for c in comps if c.get("dynamic_required") is True]
    req_done = sum(1 for c in req if verdict[c["id"]])
    print(
        f"\nALL: {total_done}/{len(comps)} = {round(total_done / len(comps) * 100, 1)}%"
        f"   REQUIRED-ONLY: {req_done}/{len(req)} = {round(req_done / len(req) * 100, 1)}%"
    )

    if not a.apply:
        print("\ndry run; pass --apply to write")
        return 0

    doc["dynamic_reconciled_by"] = "reconcile_dynamic.py"
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
    tmp.replace(path)
    print("\nwritten.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
