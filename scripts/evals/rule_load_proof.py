"""Derive matched-arm rule load proofs from scenario evidence.

An auto-loaded rule lands in the system prompt, and `session.jsonl` never records the system
prompt. Grepping a transcript therefore cannot tell "the rule was withheld" from "the rule was
loaded and ignored" -- the two look identical. The only external channel that distinguishes them is
the FIRST assistant message's `cache_creation_input_tokens`: the tokens the API had to write to
cache for a prefix it had not seen before.

Three things this script exists to get right, each of which has already gone wrong once:

1. `metrics.json` stores the SESSION TOTAL from the final result event, which runs 1.07x-4.34x the
   first-message value because mid-session turns keep writing cache. Reading it as the load proof
   silently measures conversation length instead of prompt size. The first-message value is
   re-derived here from session.jsonl every time.

2. Arms must be cache-MATCHED. Observed first-message values are strongly bimodal -- a "warm" mode
   near 20k and a "cold" mode near 52k for the same configuration -- so a warm rule arm compared
   against a cold control produces a delta that is mostly cache state (E-021). Arms are grouped
   into modes here and a cross-mode comparison is refused, not silently reported.

3. The delta must be attributable to the rule and not to noise. Dividing the rule's byte size by
   the token delta must land in the established 2.60-2.82 bytes/token band. Outside the band the
   proof FAILS -- it is not rounded in.

Small rules are near the resolution floor: a 3KB rule buys ~1.1k tokens of delta, so a mode
misassignment of even a few hundred tokens moves it out of band. That is a real limit of the
method and is reported rather than smoothed over.

Usage:
    rule_load_proof.py <scenario-dir> [<scenario-dir> ...] [--band LO HI] [--json <out>]

Each <scenario-dir> is a raw/task-runs/<SCENARIO> directory. Arms named `control-*` supply the
baseline; arms named `only-<rule>` and `shipped-config` are the measured cells.
"""

from __future__ import annotations

import argparse
import calendar
import datetime
import json
import pathlib
import re
import sys

# Two first-message values belong to the same cache mode when they are within this fraction of
# each other. The observed modes are ~20k and ~52k -- more than 2x apart -- so a 35% window
# separates them cleanly without needing a hand-picked threshold per batch.
MODE_TOLERANCE = 0.35

#: Two arms belong to the same wave when their launch stamps are this close. A wave is one shell
#: fan-out, so its arms start within a second or two; separate waves are minutes apart at least.
WAVE_TOLERANCE_S = 180


def first_message_cache_creation(session_jsonl: pathlib.Path) -> int | None:
    """The cache_creation_input_tokens of the FIRST assistant message, or None."""
    if not session_jsonl.is_file():
        return None
    with session_jsonl.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("type") != "assistant":
                continue
            usage = (event.get("message") or {}).get("usage") or {}
            if "cache_creation_input_tokens" in usage:
                return int(usage["cache_creation_input_tokens"])
    return None


def rule_bytes(repo_root: pathlib.Path, rule: str) -> int | None:
    path = repo_root / "rules" / f"{rule}.md"
    return path.stat().st_size if path.is_file() else None


def payload_bytes(repo_root: pathlib.Path) -> int:
    return sum(p.stat().st_size for p in (repo_root / "rules").glob("*.md"))


def same_mode(a: int, b: int) -> bool:
    hi = max(a, b)
    return hi > 0 and abs(a - b) / hi <= MODE_TOLERANCE


def launch_stamp(arm_dir_name: str) -> int | None:
    """Seconds-since-epoch of the `-YYYYmmddTHHMMSSZ` suffix an arm directory carries."""
    m = re.search(r"-(\d{8}T\d{6}Z)$", arm_dir_name)
    if not m:
        return None
    return int(
        calendar.timegm(
            datetime.datetime.strptime(m.group(1), "%Y%m%dT%H%M%SZ").timetuple()
        )
    )


def same_wave(a: int | None, b: int | None) -> bool:
    """True when two arms were launched together.

    Arms in one wave are started by a single shell fan-out, so their stamps land within a second or
    two of each other; the tolerance is generous enough to absorb a slow start and far tighter than
    the gap between two deliberate waves.
    """
    return a is not None and b is not None and abs(a - b) <= WAVE_TOLERANCE_S


def collect(scenario_dir: pathlib.Path) -> list[dict]:
    arms = []
    for arm_dir in sorted(scenario_dir.iterdir()):
        if not arm_dir.is_dir():
            continue
        tokens = first_message_cache_creation(arm_dir / "session.jsonl")
        if tokens is None:
            continue
        run = arm_dir / "run.json"
        rules_mode = ""
        if run.is_file():
            try:
                rules_mode = json.loads(run.read_text(encoding="utf-8")).get(
                    "rules_mode", ""
                )
            except json.JSONDecodeError:
                pass
        arms.append(
            {
                "scenario": scenario_dir.name,
                "arm": arm_dir.name.rsplit("-2026", 1)[0],
                "dir": str(arm_dir),
                "rules_mode": rules_mode,
                "first_msg_tokens": tokens,
                "launched_at": launch_stamp(arm_dir.name),
            }
        )
    return arms


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("scenarios", nargs="+")
    ap.add_argument("--band", nargs=2, type=float, default=[2.60, 2.82])
    ap.add_argument("--json", default="")
    ap.add_argument(
        "--allow-cross-wave",
        action="store_true",
        help="grade arms against controls from other waves (the pre-E-055 behaviour; unsound)",
    )
    args = ap.parse_args()
    lo, hi = args.band
    allow_cross_wave = args.allow_cross_wave

    repo_root = pathlib.Path(__file__).resolve().parents[2]

    arms: list[dict] = []
    for s in args.scenarios:
        arms.extend(collect(pathlib.Path(s)))
    if not arms:
        print("no arms with a parseable session.jsonl", file=sys.stderr)
        return 2

    controls = [a for a in arms if a["rules_mode"] == "none"]
    if not controls:
        print(
            "no control arm (rules_mode=none); cannot form a matched baseline",
            file=sys.stderr,
        )
        return 2

    # Control noise, derived here rather than eyeballed. The proposed signal-vs-noise criterion in
    # small-rule-load-proof.md is admissible only if sigma < 50 tokens from >=3 same-mode control
    # replicates, a bound fixed before this measurement was taken. Reporting it in the same pass
    # that reports the verdicts is the P3 rule: a scalar quoted from memory is a scalar that can
    # drift from the data it claims to describe.
    clusters: list[list[dict]] = []
    for c in sorted(controls, key=lambda c: c["first_msg_tokens"]):
        if clusters and same_mode(
            clusters[-1][-1]["first_msg_tokens"], c["first_msg_tokens"]
        ):
            clusters[-1].append(c)
        else:
            clusters.append([c])
    print(
        "control noise by cache mode (pre-registered guard: sigma < 50 tokens, n >= 3)"
    )
    admissible = False
    for cl in clusters:
        vals = [c["first_msg_tokens"] for c in cl]
        n = len(vals)
        mean = sum(vals) / n
        sigma = (
            (sum((v - mean) ** 2 for v in vals) / (n - 1)) ** 0.5
            if n > 1
            else float("nan")
        )
        ok = n >= 3 and sigma < 50
        admissible = admissible or ok
        verdict = (
            "ADMISSIBLE" if ok else ("n<3" if n < 3 else "sigma>=50 -> criterion VOID")
        )
        print(
            f"  mode~{mean:>9.0f}  n={n}  sigma={sigma:>8.1f}  values={vals}  {verdict}"
        )
    print(
        f"  -> signal criterion {'ADMISSIBLE' if admissible else 'NOT admissible'}; "
        f"small-rule verdicts {'may be re-adjudicated' if admissible else 'stay UNPROVEN'}\n"
    )

    results = []
    for arm in arms:
        mode = arm["rules_mode"]
        if mode == "none":
            continue
        if mode.startswith("only:"):
            rule = mode.split(":", 1)[1]
            size = rule_bytes(repo_root, rule)
        elif mode == "full":
            rule, size = "<shipped payload>", payload_bytes(repo_root)
        else:
            continue
        if not size:
            continue

        # Only controls in the SAME cache mode may serve as the baseline. Picking the closest one
        # rather than an average keeps the comparison to a single real measurement.
        #
        # Same MODE is necessary but not sufficient (E-055). A control launched in another wave
        # carries a different cached prefix even when its total lands inside the 35% window, and the
        # resulting delta is wrong by far more than the band is wide: `agent-memory` graded 3.73
        # against a foreign-wave control and 2.70 against its own. Measured within one wave the
        # method reproduces to 0.03%, so the wave requirement is what makes the band meaningful.
        pool = (
            controls
            if allow_cross_wave
            else [
                c for c in controls if same_wave(c["launched_at"], arm["launched_at"])
            ]
        )
        if not pool:
            results.append(
                {
                    **arm,
                    "rule": rule,
                    "rule_bytes": size,
                    "verdict": "UNPAIRED",
                    "detail": (
                        "no control launched in this arm's wave. Grading it against a foreign-wave "
                        "control would report a number the data cannot support, and FAILED would "
                        "assert the rule did not load -- which is not what an absent baseline means."
                    ),
                }
            )
            continue
        matched = [
            c for c in pool if same_mode(c["first_msg_tokens"], arm["first_msg_tokens"])
        ]
        if not matched:
            # A proportional mode test cannot separate "ran at a different cache warmth" from
            # "legitimately has a much larger prefix": the shipped-config arm carries 296KB of
            # rules and therefore sits ~6x above every control by construction, so no tolerance
            # that admits it would still reject a genuine cold/warm mismatch. Loosening the
            # threshold until the verdict agrees with a number already computed by hand is fitting
            # to the answer. Report the arm against EVERY control mode instead and mark it
            # ambiguous -- if the candidates disagree, the reader sees the disagreement.
            candidates = []
            for c in pool:
                d = arm["first_msg_tokens"] - c["first_msg_tokens"]
                b = (size / d) if d > 0 else 0.0
                candidates.append(
                    {
                        "baseline_arm": c["arm"],
                        "baseline_tokens": c["first_msg_tokens"],
                        "delta_tokens": d,
                        "bytes_per_token": round(b, 2),
                        "in_band": bool(d > 0 and lo <= b <= hi),
                    }
                )
            in_band = [c for c in candidates if c["in_band"]]
            results.append(
                {
                    **arm,
                    "rule": rule,
                    "rule_bytes": size,
                    "verdict": "AMBIGUOUS",
                    "detail": (
                        f"no control within {MODE_TOLERANCE:.0%}; prefix size and cache warmth are "
                        f"not separable here. {len(in_band)}/{len(candidates)} control modes put "
                        "it in band."
                    ),
                    "candidates": candidates,
                }
            )
            continue
        base = min(
            matched, key=lambda c: abs(c["first_msg_tokens"] - arm["first_msg_tokens"])
        )
        delta = arm["first_msg_tokens"] - base["first_msg_tokens"]
        bpt = (size / delta) if delta > 0 else 0.0
        verdict = "PROVEN" if delta > 0 and lo <= bpt <= hi else "FAILED"
        results.append(
            {
                **arm,
                "rule": rule,
                "baseline_arm": base["arm"],
                "baseline_tokens": base["first_msg_tokens"],
                "delta_tokens": delta,
                "rule_bytes": size,
                "bytes_per_token": round(bpt, 2),
                "band": [lo, hi],
                "verdict": verdict,
            }
        )

    width = max(len(r["arm"]) for r in results) + 2
    print(
        f"{'arm':<{width}}{'tokens':>9}{'base':>9}{'delta':>9}{'bytes':>10}{'B/tok':>8}  verdict"
    )
    for r in sorted(results, key=lambda r: r["arm"]):
        if r["verdict"] == "UNPAIRED":
            print(
                f"{r['arm']:<{width}}{r['first_msg_tokens']:>9}{'-':>9}{'-':>9}"
                f"{r['rule_bytes']:>10}{'-':>8}  UNPAIRED  {r['detail']}"
            )
            continue
        if r["verdict"] == "AMBIGUOUS":
            print(
                f"{r['arm']:<{width}}{r['first_msg_tokens']:>9}{'?':>9}{'?':>9}"
                f"{r['rule_bytes']:>10}{'?':>8}  AMBIGUOUS  {r['detail']}"
            )
            for c in r["candidates"]:
                mark = "in band" if c["in_band"] else "out"
                print(
                    f"{'    vs ' + c['baseline_arm']:<{width}}{'':>9}{c['baseline_tokens']:>9}"
                    f"{c['delta_tokens']:>9}{'':>10}{c['bytes_per_token']:>8}  ({mark})"
                )
            continue
        print(
            f"{r['arm']:<{width}}{r['first_msg_tokens']:>9}{r['baseline_tokens']:>9}"
            f"{r['delta_tokens']:>9}{r['rule_bytes']:>10}{r['bytes_per_token']:>8}  {r['verdict']}"
        )

    proven = sorted({r["rule"] for r in results if r["verdict"] == "PROVEN"})
    print(f"\nPROVEN: {len(proven)} -> {proven}")
    failed = sorted({r["rule"] for r in results if r["verdict"] != "PROVEN"})
    if failed:
        print(f"NOT PROVEN: {failed}")

    if args.json:
        pathlib.Path(args.json).write_text(
            json.dumps(results, indent=2) + "\n", encoding="utf-8"
        )
        print(f"wrote {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
