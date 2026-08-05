"""Baseline-versus-candidate evaluation for an accepted change (terminal gate item 17).

For each accepted change, run the SAME deterministic scenario set against two arms -- the payload
at ``<sha>^`` and at ``<sha>`` -- and require that the candidate gains where the change claimed a
gain and regresses nowhere. A change that scores identically to its own baseline bought nothing,
and that is a finding rather than a pass.

**On the word "blind".** The arms are handed to the runner under opaque names and the mapping is
sealed until after grading. That is worth doing, but it is worth being precise about what it buys:
the grader here is a deterministic oracle, and a deterministic oracle cannot be biased by knowing
which arm it is looking at. What the blind actually prevents is an ARM-SPECIFIC CODE PATH -- an
adjudicator that reaches for ``results["candidate"]`` can grow a special case; one that only ever
sees ``arm-A``/``arm-B`` cannot. Blinding becomes load-bearing the moment any arm is graded by a
judgement rather than an oracle, and this harness must not be extended in that direction without
the seal becoming real.

Three phases, because git cannot run inside a Docker copy of a worktree (the worktree's ``.git``
is a pointer file into the parent repo, so ``git show`` exits 128 there):

  extract     host   -- git show both revisions into arm dirs; write the sealed mapping
  run         Docker -- execute the scenario set once per arm, arm-keyed results only
  adjudicate  host   -- unseal, compare, emit the verdict

The run phase refuses to start outside Docker, and the adjudicate phase refuses to grade a run
whose evidence does not record that it ran inside Docker.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import sys
from typing import Any

# Each accepted change names the payload files whose two revisions form the arms, and the
# scenario subset that exercises them. Adding a change here is a data edit.
CHANGES: dict[str, dict] = {
    "9711e14": {
        "files": ["hooks/scripts/guard-secrets.sh"],
        "scenario_prefix": "guard-secrets/",
        "claim": "adds catches for URI credentials and AWS secret keys without adding noise",
        "gain_on": "fire",
        "no_regression_on": "nofire",
    },
}

ARMS = ("arm-A", "arm-B")


def _die(msg: str) -> int:
    print(msg, file=sys.stderr)
    return 2


def _write_json(path: str, doc: dict) -> None:
    pathlib.Path(path).write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")


def _sealed_order(sha: str) -> tuple[str, str]:
    """Which arm is baseline, derived from the sha so the run is reproducible.

    Deterministic rather than random: a run that cannot be reproduced cannot be audited, and the
    point of the seal is that the ADJUDICATOR does not read it early, not that a human could never
    work it out.
    """
    flip = int(hashlib.sha256(sha.encode()).hexdigest(), 16) % 2
    return (ARMS[flip], ARMS[1 - flip])


def cmd_extract(args: argparse.Namespace) -> int:
    spec = CHANGES.get(args.change)
    if spec is None:
        return _die(f"unknown change {args.change!r}; known: {sorted(CHANGES)}")
    root = pathlib.Path(args.out) / args.change
    if root.exists():
        shutil.rmtree(root)
    baseline_arm, candidate_arm = _sealed_order(args.change)
    for arm, rev in ((baseline_arm, f"{args.change}^"), (candidate_arm, args.change)):
        for rel in spec["files"]:
            dest = root / arm / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            proc = subprocess.run(
                ["git", "show", f"{rev}:{rel}"],
                capture_output=True,
                text=True,
                cwd=args.repo,
            )
            if proc.returncode != 0:
                return _die(f"git show {rev}:{rel} failed: {proc.stderr.strip()}")
            dest.write_text(proc.stdout, encoding="utf-8")

    identical = _arms_identical(root, spec["files"])
    (root / "sealed.json").write_text(
        json.dumps(
            {
                "change": args.change,
                "baseline_arm": baseline_arm,
                "candidate_arm": candidate_arm,
                "note": "do not read this during grading",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "change": args.change,
                "arms": list(ARMS),
                "files": spec["files"],
                "scenario_prefix": spec["scenario_prefix"],
                "arms_differ": not identical,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    if identical:
        return _die(
            f"REFUSING: arms of {args.change} are byte-identical -- "
            "an A/B whose arms are the same file measures nothing"
        )
    print(f"extracted {args.change}: {len(spec['files'])} file(s) x 2 arms -> {root}")
    return 0


def _by_id(row: dict) -> str:
    return str(row["id"])


def _arms_identical(root: pathlib.Path, files: list[str]) -> bool:
    return all(
        (root / ARMS[0] / rel).read_bytes() == (root / ARMS[1] / rel).read_bytes()
        for rel in files
    )


def cmd_run(args: argparse.Namespace) -> int:
    if not pathlib.Path("/.dockerenv").is_file():
        print("refusing to run outside Docker (no /.dockerenv)", file=sys.stderr)
        return 3
    root = pathlib.Path(args.arms) / args.change
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    prefix = manifest["scenario_prefix"]

    out: dict[str, Any] = {
        "change": args.change,
        "dockerenv_verified": True,
        "scenario_prefix": prefix,
        "arms": {},
    }
    for arm in ARMS:
        tree = pathlib.Path(args.work) / arm
        if tree.exists():
            shutil.rmtree(tree)
        shutil.copytree(args.repo, tree, symlinks=True)
        for rel in manifest["files"]:
            dest = tree / rel
            dest.write_bytes((root / arm / rel).read_bytes())
            dest.chmod(0o755)
        proc = subprocess.run(
            [sys.executable, str(tree / "tests/evals/hooks/run_hook_scenarios.py")],
            capture_output=True,
            text=True,
            cwd=str(tree),
            env={**os.environ, "HOOK_REPO": str(tree)},
            timeout=900,
        )
        parsed = _parse_runner(proc.stdout)
        if parsed is None:
            out["arms"][arm] = {"error": "runner emitted no parseable JSON"}
            out["arms"][arm]["stderr_tail"] = proc.stderr[-800:]
            continue
        rows = [r for r in parsed["results"] if r["id"].startswith(prefix)]
        out["arms"][arm] = {
            "scenarios": len(rows),
            "by_kind": _tally(rows),
            "per_scenario": {r["id"]: r["ok"] for r in sorted(rows, key=_by_id)},
        }

    _write_json(args.out, out)
    for arm, res in out["arms"].items():
        print(arm, json.dumps(res.get("by_kind", res)))
    return 0


def _tally(rows: list[dict]) -> dict[str, dict[str, int]]:
    tally: dict[str, dict[str, int]] = {}
    for r in rows:
        t = tally.setdefault(r["kind"], {"total": 0, "ok": 0})
        t["total"] += 1
        t["ok"] += 1 if r["ok"] else 0
    return tally


def _parse_runner(stdout: str) -> dict | None:
    """The runner prints a JSON document; tolerate leading human-readable lines."""
    start = stdout.find("{")
    while start != -1:
        try:
            doc = json.loads(stdout[start:])
        except json.JSONDecodeError:
            start = stdout.find("{", start + 1)
            continue
        return doc if isinstance(doc, dict) and "results" in doc else None
    return None


def adjudicate(spec: dict, sealed: dict, results: dict) -> dict:
    """Compare the two arms. Pure, so the self-test can plant an outcome and check the verdict."""
    base = results["arms"][sealed["baseline_arm"]]
    cand = results["arms"][sealed["candidate_arm"]]

    gain, no_reg = spec["gain_on"], spec["no_regression_on"]
    b_gain = base["by_kind"].get(gain, {"ok": 0, "total": 0})
    c_gain = cand["by_kind"].get(gain, {"ok": 0, "total": 0})
    b_reg = base["by_kind"].get(no_reg, {"ok": 0, "total": 0})
    c_reg = cand["by_kind"].get(no_reg, {"ok": 0, "total": 0})

    improved = c_gain["ok"] > b_gain["ok"]
    held = c_reg["ok"] >= b_reg["ok"] and c_reg["ok"] == c_reg["total"]
    newly_caught = sorted(
        sid
        for sid, ok in cand["per_scenario"].items()
        if ok and not base["per_scenario"].get(sid, False)
    )
    newly_broken = sorted(
        sid
        for sid, ok in cand["per_scenario"].items()
        if not ok and base["per_scenario"].get(sid, False)
    )

    verdict = "PASS" if improved and held and not newly_broken else "FAIL"
    reasons = []
    if not improved:
        reasons.append(
            f"candidate did not gain on {gain}: {b_gain['ok']} -> {c_gain['ok']}. "
            "A change that scores no better than its own baseline bought nothing."
        )
    if not held:
        reasons.append(
            f"candidate did not hold {no_reg}: {b_reg['ok']}/{b_reg['total']} -> "
            f"{c_reg['ok']}/{c_reg['total']}"
        )
    if newly_broken:
        reasons.append(f"regressions: {newly_broken}")

    return {
        "claim": spec["claim"],
        "verdict": verdict,
        "blind": {
            "arms_opaque_during_run": True,
            "seal_read_at": "adjudication only",
            "load_bearing": False,
            "why": (
                "the grader is a deterministic oracle and cannot be biased by the label; the "
                "blind prevents an arm-specific code path, not grader bias"
            ),
        },
        "baseline": {"arm": sealed["baseline_arm"], "by_kind": base["by_kind"]},
        "candidate": {"arm": sealed["candidate_arm"], "by_kind": cand["by_kind"]},
        "newly_caught": newly_caught,
        "newly_broken": newly_broken,
        "reasons": reasons,
        "gain_line": f"{gain} {b_gain['ok']}/{b_gain['total']} -> {c_gain['ok']}/{c_gain['total']}",
        "hold_line": f"{no_reg} {b_reg['ok']}/{b_reg['total']} -> {c_reg['ok']}/{c_reg['total']}",
    }


def cmd_adjudicate(args: argparse.Namespace) -> int:
    spec = CHANGES[args.change]
    root = pathlib.Path(args.arms) / args.change
    results = json.loads(pathlib.Path(args.results).read_text(encoding="utf-8"))
    # absent-ok: absence IS the finding, and it is the safe direction. A results file with no
    # dockerenv_verified key was not written by cmd_run, which sets it unconditionally after
    # proving /.dockerenv -- so missing and false both mean "not proven to have run in Docker",
    # and both must refuse. Distinguishing them would only let a hand-written file through.
    if not results.get("dockerenv_verified"):
        return _die("refusing: results do not record a Docker run")

    sealed = json.loads((root / "sealed.json").read_text(encoding="utf-8"))
    for name in ("baseline_arm", "candidate_arm"):
        res = results["arms"][sealed[name]]
        if "error" in res:
            return _die(f"refusing: {name} produced no results: {res['error']}")

    doc = adjudicate(spec, sealed, results)
    doc["change"] = args.change
    doc["evidence"] = args.results
    _write_json(args.out, doc)
    print(f"{args.change}: {doc['verdict']}")
    print("  " + doc["gain_line"])
    print("  " + doc["hold_line"])
    if doc["newly_caught"]:
        print(f"  newly caught: {', '.join(doc['newly_caught'])}")
    for r in doc["reasons"]:
        print(f"  ! {r}")
    return 0 if doc["verdict"] == "PASS" else 1


def _synth(fire_ok: int, nofire_ok: int, broken: str | None = None) -> dict:
    """One arm's results over a fixed 4-fire / 7-nofire synthetic scenario set."""
    fire = {f"g/fire-{i}": i < fire_ok for i in range(4)}
    nofire = {f"g/nofire-{i}": i < nofire_ok for i in range(7)}
    per = {**fire, **nofire}
    if broken:
        per[broken] = False
    return {
        "scenarios": len(per),
        "by_kind": {
            "fire": {"total": len(fire), "ok": sum(per[k] for k in fire)},
            "nofire": {"total": len(nofire), "ok": sum(per[k] for k in nofire)},
        },
        "per_scenario": per,
    }


def cmd_selftest(args: argparse.Namespace) -> int:
    """Plant outcomes and require the verdict to flip. A grader that always PASSes grades nothing.

    The swapped-seal case is the one worth having: without it, an adjudicator that simply assumed
    arm-B was the candidate would score every real run correctly by luck and would be undetectable.
    """
    spec = {"claim": "synthetic", "gain_on": "fire", "no_regression_on": "nofire"}
    seal = {"baseline_arm": "arm-A", "candidate_arm": "arm-B"}
    swapped = {"baseline_arm": "arm-B", "candidate_arm": "arm-A"}

    def run(sealed, a, b):
        return adjudicate(spec, sealed, {"arms": {"arm-A": a, "arm-B": b}})

    real = (_synth(1, 7), _synth(4, 7))
    cases = [
        ("real shape: fire 1/4 -> 4/4, nofire held", "PASS", run(seal, *real)),
        ("no gain: 4/4 -> 4/4", "FAIL", run(seal, _synth(4, 7), _synth(4, 7))),
        ("gain but nofire regresses", "FAIL", run(seal, _synth(1, 7), _synth(4, 6))),
        (
            "counts improve but a passing scenario broke",
            "FAIL",
            run(seal, _synth(1, 7), _synth(4, 7, broken="g/nofire-0")),
        ),
        ("seal swapped: real run read backwards", "FAIL", run(swapped, *real)),
    ]

    bad = []
    for name, want, doc in cases:
        got = doc["verdict"]
        print(f"  [{'ok' if got == want else 'BAD'}] {name}: want {want}, got {got}")
        if got != want:
            bad.append(name)

    no_gain = cases[1][2]
    if not any("bought nothing" in r for r in no_gain["reasons"]):
        bad.append("the no-gain case did not say the change bought nothing")

    if bad:
        print(f"SELF-TEST FAILED: {bad}", file=sys.stderr)
        return 1
    print(f"self-test passed: {len(cases)} planted outcomes, every verdict as required")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="phase", required=True)

    e = sub.add_parser("extract", help="host: git show both revisions into arm dirs")
    e.add_argument("--change", required=True)
    e.add_argument("--repo", default=".")
    e.add_argument("--out", required=True)
    e.set_defaults(fn=cmd_extract)

    r = sub.add_parser("run", help="Docker: run the scenario set once per arm")
    r.add_argument("--change", required=True)
    r.add_argument("--arms", required=True)
    r.add_argument("--repo", required=True)
    r.add_argument("--work", default="/tmp/ab")
    r.add_argument("--out", required=True)
    r.set_defaults(fn=cmd_run)

    a = sub.add_parser("adjudicate", help="host: unseal and compare")
    a.add_argument("--change", required=True)
    a.add_argument("--arms", required=True)
    a.add_argument("--results", required=True)
    a.add_argument("--out", required=True)
    a.set_defaults(fn=cmd_adjudicate)

    s = sub.add_parser("selftest", help="plant outcomes; verdicts must flip")
    s.set_defaults(fn=cmd_selftest)

    args = ap.parse_args()
    return int(args.fn(args))


if __name__ == "__main__":
    raise SystemExit(main())
