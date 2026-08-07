"""Grade the Q2/D-004 covenant sweep: does the always-on rule set still dilute itself?

E-022 and F-073 both concluded that a rule which works alone stops working once the rest of the
payload loads. Both were measured when 25 rules auto-loaded and the shipped prompt ran ~163k
tokens. Scoping (F-042) cut the auto-loaded set to 7 rules / 73,228 B, so the shipped arm is a
different attention regime and the old numbers describe a configuration that no longer exists.
This re-takes the measurement rather than arguing from them.

Two things this file refuses to do, both of which would manufacture a result:

1. **Grade a run that did not complete.** A `claude -p` child that dies on a socket error invoked
   nothing, and a naive reader scores that empty check vector as a miss. On the description
   re-probe wave that turned three transport failures into a reported REGRESSION. A run without an
   oracle verdict is VOID -- reported, never counted.

2. **Read the sweep without its specificity control.** `only:risk-classification` is another
   covenant rule of similar size with no claim over severity ladders. If the isolated
   quality-gates arm scores higher AND the risk arm scores just as high, the finding is "short
   prompts score higher", not anything about quality-gates. The control's score is printed next to
   the result so that reading cannot be skipped.

Fisher's exact (one-sided) is computed by hand rather than pulled from scipy, which is not a
dependency of this repo.
"""

from __future__ import annotations

import argparse
import glob
import json
import math
import pathlib

#: The two checks rd_rules.py attributes to quality-gates.md. `bug_identified` is deliberately NOT
#: here: every arm should find the off-by-one, so it is the task-too-hard canary, not a signal.
QG_CHECKS = ("severity_classified", "blocking_verdict")
CANARY = "bug_identified"


def _fisher_one_sided(a: int, b: int, c: int, d: int) -> float:
    """P(observing this table or more extreme) for a 2x2, one-sided. No scipy in this repo."""

    def hyp(x: int) -> float:
        return math.exp(
            math.lgamma(a + b + 1)
            + math.lgamma(c + d + 1)
            + math.lgamma(a + c + 1)
            + math.lgamma(b + d + 1)
            - math.lgamma(a + b + c + d + 1)
            - math.lgamma(x + 1)
            - math.lgamma(a + b - x + 1)
            - math.lgamma(a + c - x + 1)
            - math.lgamma(d - a + x + 1)
        )

    lo, hi = max(0, a - d), min(a + b, a + c)
    return sum(hyp(x) for x in range(a, hi + 1) if lo <= x <= hi)


def load(run_dir: pathlib.Path) -> dict | None:
    """The check vector for one run, or None when the run cannot be graded at all."""
    v = run_dir / "oracle-verdict.json"
    if not v.is_file():
        return None
    doc = json.loads(v.read_text(encoding="utf-8"))
    # Vacuous checks (pass is None, F-080) are dropped rather than coerced to False: a check that
    # proved nothing must not be scored as a negative result for the arm it ran in.
    checks = {
        c["check"]: bool(c["pass"])
        for c in doc.get("checks", [])
        if c["pass"] is not None
    }
    return checks or None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--dir",
        default=".claude/state/full-self-evaluation/raw/task-runs/RD-COVENANT",
    )
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    root = pathlib.Path(a.dir)

    arms: dict[str, list[dict]] = {"shipped": [], "onlyqg": [], "onlyrisk": []}
    voids: list[str] = []
    for d in sorted(glob.glob(str(root / "*"))):
        p = pathlib.Path(d)
        if not p.is_dir():
            continue
        key = next((k for k in arms if p.name.startswith(k + "-")), None)
        if key is None:
            continue
        checks = load(p)
        if checks is None:
            voids.append(p.name)
            continue
        arms[key].append(checks)

    print(
        f"{'arm':10s} {'n':>3s}  "
        + "  ".join(f"{c:>20s}" for c in (CANARY, *QG_CHECKS))
    )
    print("-" * 78)
    score: dict[str, dict[str, int]] = {}
    for arm, runs in arms.items():
        if not runs:
            print(f"{arm:10s} {0:3d}   (no gradeable runs)")
            continue
        score[arm] = {c: sum(1 for r in runs if r.get(c)) for c in (CANARY, *QG_CHECKS)}
        cells = "  ".join(
            f"{score[arm][c]:>17d}/{len(runs)}" for c in (CANARY, *QG_CHECKS)
        )
        print(f"{arm:10s} {len(runs):3d}  {cells}")

    print()
    # The canary first: if the control cannot do the task, nothing below is a rule effect.
    for arm, s in score.items():
        n = len(arms[arm])
        if s[CANARY] < n:
            print(
                f"WARNING: {arm} found the seeded bug in only {s[CANARY]}/{n} runs -- the task "
                f"may be too hard for this arm, which would confound every check above."
            )

    verdict = {}
    if "shipped" in score and "onlyqg" in score:
        ns, nq = len(arms["shipped"]), len(arms["onlyqg"])
        for c in QG_CHECKS:
            hs, hq = score["shipped"][c], score["onlyqg"][c]
            p = _fisher_one_sided(hq, nq - hq, hs, ns - hs)
            ctl = score.get("onlyrisk", {}).get(c)
            nctl = len(arms.get("onlyrisk", []))
            verdict[c] = {
                "shipped": f"{hs}/{ns}",
                "only_quality_gates": f"{hq}/{nq}",
                "specificity_control_only_risk": (
                    f"{ctl}/{nctl}" if ctl is not None else None
                ),
                "fisher_one_sided_p": round(p, 5),
            }
            print(
                f"{c}: shipped {hs}/{ns} vs only:quality-gates {hq}/{nq}  p={p:.4f}"
                + (
                    f"   [control only:risk-classification {ctl}/{nctl}]"
                    if ctl is not None
                    else ""
                )
            )
            if ctl is not None and nctl and ctl / nctl >= (hq / nq if nq else 0) and hq:
                print(
                    "   ^ the specificity control scores as high as the treatment: this is a "
                    "prompt-length effect, NOT evidence about quality-gates.md"
                )

    if voids:
        print(f"\nVOID (not counted): {len(voids)}")
        for v in voids:
            print(f"  {v}")

    if a.out:
        pathlib.Path(a.out).write_text(
            json.dumps(
                {
                    "counts": {k: len(v) for k, v in arms.items()},
                    "hits": score,
                    "verdict": verdict,
                    "void": voids,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
