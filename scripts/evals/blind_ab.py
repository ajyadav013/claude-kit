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
from fnmatch import fnmatch
from typing import Any

# Each accepted change names the payload files whose two revisions form the arms, the metric that
# scores them, and which tally must improve vs merely hold. Adding a change here is a data edit.
#
# Every metric swaps the arm's files into the CURRENT tree and runs the CURRENT yardstick. Vary
# the code, hold the test. Checking out each arm's whole tree would let the candidate be graded by
# its own new tests, which is how an A/B flatters itself.
CHANGES: dict[str, dict] = {
    "9711e14": {
        "files": ["hooks/scripts/guard-secrets.sh"],
        "metric": "hook_scenarios",
        "scenario_prefix": "guard-secrets/",
        "claim": "adds catches for URI credentials and AWS secret keys without adding noise",
        "gain_on": "fire",
        "no_regression_on": "nofire",
    },
    "da4590c": {
        "files": ["hooks/scripts/guard-push-main.sh"],
        "metric": "file_mode",
        "claim": "the last non-755 hook script becomes directly executable, nothing else moves",
        "gain_on": "target_executable",
        "no_regression_on": "others_executable",
    },
    "5801277": {
        # cli.py is deliberately NOT an arm for 6c6155e below, and this is the same discipline:
        # only files whose current behaviour the change still owns can be two-armed honestly.
        "files": "rules/*.md",
        "metric": "rule_scoping",
        "claim": "18 of 25 rules become path-scoped; the 7 covenant rules keep loading always",
        "gain_on": "scoped",
        "no_regression_on": "covenant",
    },
    "6c6155e": {
        # src/claude_kit/cli.py is excluded on purpose. F-087 later rewrote the same error path,
        # so an arm holding this change's cli.py graded against today's tests would measure the
        # LATER fix, not this one. Its init claim is covered by the F-087 tests instead.
        "files": ["agents/auditor.md", "src/claude_kit/telemetry.py"],
        "metric": "pytest_selection",
        "gain_tests": ["tests/test_telemetry.py", "tests/test_agent_frontmatter.py"],
        "hold_tests": ["tests/test_scaffold.py", "tests/test_plugin.py"],
        "claim": "auditor loses Write/Edit/Agent; telemetry survives a non-mapping message",
        "gain_on": "targeted",
        "no_regression_on": "held",
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


def _tracked(repo: str, rev: str, pattern: str) -> list[str]:
    """Tracked paths at `rev` matching a glob.

    The glob is applied in Python, not handed to git as a pathspec: `git ls-tree -- 'rules/*.md'`
    silently matches NOTHING, and a file list that comes back empty for a syntax reason looks
    exactly like a change that touched no files.
    """
    proc = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", rev],
        capture_output=True,
        text=True,
        cwd=repo,
    )
    return [
        ln for ln in proc.stdout.splitlines() if ln.strip() and fnmatch(ln, pattern)
    ]


def _modes(repo: str, rev: str, paths: list[str]) -> dict[str, str]:
    """Mode bits per path at a revision. `git show` gives content and drops the mode entirely."""
    proc = subprocess.run(
        ["git", "ls-tree", "-r", rev, "--", *paths],
        capture_output=True,
        text=True,
        cwd=repo,
    )
    out = {}
    for line in proc.stdout.splitlines():
        meta, _, path = line.partition("\t")
        parts = meta.split()
        if path and parts:
            out[path] = parts[0]
    return out


def _resolve_files(spec: dict, repo: str, change: str) -> list[str]:
    """A change may name files literally or by glob; a glob resolves against the CANDIDATE tree."""
    files = spec["files"]
    return (
        sorted(_tracked(repo, change, files)) if isinstance(files, str) else list(files)
    )


def cmd_extract(args: argparse.Namespace) -> int:
    spec = CHANGES.get(args.change)
    if spec is None:
        return _die(f"unknown change {args.change!r}; known: {sorted(CHANGES)}")
    files = _resolve_files(spec, args.repo, args.change)
    if not files:
        return _die(f"no files matched {spec['files']!r} at {args.change}")
    root = pathlib.Path(args.out) / args.change
    if root.exists():
        shutil.rmtree(root)
    baseline_arm, candidate_arm = _sealed_order(args.change)
    revs = {baseline_arm: f"{args.change}^", candidate_arm: args.change}
    for arm, rev in revs.items():
        for rel in files:
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
        _write_json(str(root / arm / "modes.json"), _modes(args.repo, rev, files))

    same_content = _arms_identical(root, files)
    same_modes = (root / baseline_arm / "modes.json").read_text() == (
        root / candidate_arm / "modes.json"
    ).read_text()
    _write_json(
        str(root / "sealed.json"),
        {
            "change": args.change,
            "baseline_arm": baseline_arm,
            "candidate_arm": candidate_arm,
            "note": "do not read this during grading",
        },
    )
    _write_json(
        str(root / "manifest.json"),
        {
            "change": args.change,
            "arms": list(ARMS),
            "files": files,
            "metric": spec["metric"],
            "scenario_prefix": spec.get("scenario_prefix"),
            "gain_tests": spec.get("gain_tests"),
            "hold_tests": spec.get("hold_tests"),
            "arms_differ": not (same_content and same_modes),
        },
    )
    if same_content and same_modes:
        return _die(
            f"REFUSING: arms of {args.change} match in both content and mode -- "
            "an A/B whose arms are the same thing measures nothing"
        )
    what = "content" if not same_content else "mode only"
    print(
        f"extracted {args.change}: {len(files)} file(s) x 2 arms, differ by {what} -> {root}"
    )
    return 0


def _arms_identical(root: pathlib.Path, files: list[str]) -> bool:
    return all(
        (root / ARMS[0] / rel).read_bytes() == (root / ARMS[1] / rel).read_bytes()
        for rel in files
    )


def _score(per: dict[str, bool], kinds: dict[str, str]) -> dict[str, Any]:
    """Fold a per-item pass map into the tally shape every metric shares.

    ``kinds`` maps an item-id prefix to the tally bucket it counts toward, so each metric decides
    what "gain" and "hold" mean without the adjudicator needing to know which metric ran.
    """
    by: dict[str, dict[str, int]] = {
        k: {"total": 0, "ok": 0} for k in set(kinds.values())
    }
    for item, ok in per.items():
        for prefix, bucket in kinds.items():
            if item.startswith(prefix):
                by[bucket]["total"] += 1
                by[bucket]["ok"] += 1 if ok else 0
                break
    return {
        "scenarios": len(per),
        "by_kind": by,
        "per_scenario": dict(sorted(per.items())),
    }


def _metric_hook_scenarios(tree: pathlib.Path, manifest: dict) -> dict[str, Any]:
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
        return {
            "error": "runner emitted no parseable JSON",
            "stderr_tail": proc.stderr[-800:],
        }
    prefix = manifest["scenario_prefix"]
    rows = [r for r in parsed["results"] if r["id"].startswith(prefix)]
    per = {r["id"]: bool(r["ok"]) for r in rows}
    kinds = {r["id"]: r["kind"] for r in rows}
    return _score(per, kinds)


def _metric_file_mode(tree: pathlib.Path, manifest: dict) -> dict[str, Any]:
    """Is the change's own script directly executable, and did every other script stay so?

    The gain here is small and the change's own ledger says nothing broke without it -- both hook
    channels invoke `bash <path>`. That is precisely why it needs measuring rather than asserting:
    a change whose benefit is real but tiny still has to show the benefit is real.
    """
    targets = set(manifest["files"])
    per = {}
    for script in sorted((tree / "hooks/scripts").glob("*.sh")):
        rel = f"hooks/scripts/{script.name}"
        bucket = "target_executable" if rel in targets else "others_executable"
        per[f"{bucket}:{rel}"] = os.access(script, os.X_OK)
    buckets = {
        "target_executable": "target_executable",
        "others_executable": "others_executable",
    }
    return _score(per, buckets)


def _metric_rule_scoping(tree: pathlib.Path, manifest: dict) -> dict[str, Any]:
    """Which rules carry `paths:` frontmatter, and is the always-loaded covenant still intact?

    Scoping is the whole claim: standing context falls only because scoped rules stop loading on
    every turn. Counting frontmatter is a deterministic stand-in for a token measurement that
    would need live sessions, and it cannot drift from the thing it stands for -- the loader keys
    on exactly this frontmatter.
    """
    covenant = {
        "autonomy-levels",
        "continuity",
        "human-in-the-loop",
        "mandatory-workflow",
        "quality-gates",
        "rarv-cycle",
        "risk-classification",
    }
    per = {}
    for rule in sorted((tree / "rules").glob("*.md")):
        text = rule.read_text(encoding="utf-8", errors="replace")
        front = text.split("\n---", 1)[0] if text.startswith("---") else ""
        has_paths = any(ln.startswith("paths:") for ln in front.splitlines())
        if rule.stem in covenant:
            per[f"covenant:{rule.name}"] = not has_paths
        else:
            per[f"scoped:{rule.name}"] = has_paths
    return _score(per, {"scoped": "scoped", "covenant": "covenant"})


def _metric_pytest_selection(tree: pathlib.Path, manifest: dict) -> dict[str, Any]:
    per = {}
    for bucket, files in (
        ("targeted", manifest["gain_tests"]),
        ("held", manifest["hold_tests"]),
    ):
        # One item per test file, not per test: a file that fails at collection reports no
        # per-test results at all, and treating that as "zero failures" is the absent-is-not-false
        # trap. Exit code 0 is the only evidence the file's tests actually all passed.
        for f in files:
            single = subprocess.run(
                [sys.executable, "-m", "pytest", "-q", "--no-header", f],
                capture_output=True,
                text=True,
                cwd=str(tree),
                env={**os.environ, "PYTHONPATH": str(tree / "src")},
                timeout=1800,
            )
            per[f"{bucket}:{f}"] = single.returncode == 0
    return _score(per, {"targeted": "targeted", "held": "held"})


METRICS = {
    "hook_scenarios": _metric_hook_scenarios,
    "file_mode": _metric_file_mode,
    "rule_scoping": _metric_rule_scoping,
    "pytest_selection": _metric_pytest_selection,
}


def cmd_run(args: argparse.Namespace) -> int:
    if not pathlib.Path("/.dockerenv").is_file():
        print("refusing to run outside Docker (no /.dockerenv)", file=sys.stderr)
        return 3
    root = pathlib.Path(args.arms) / args.change
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    metric = METRICS[manifest["metric"]]

    out: dict[str, Any] = {
        "change": args.change,
        "dockerenv_verified": True,
        "metric": manifest["metric"],
        "arms": {},
    }
    for arm in ARMS:
        tree = pathlib.Path(args.work) / arm
        if tree.exists():
            shutil.rmtree(tree)
        shutil.copytree(args.repo, tree, symlinks=True)
        modes = json.loads((root / arm / "modes.json").read_text(encoding="utf-8"))
        for rel in manifest["files"]:
            dest = tree / rel
            dest.write_bytes((root / arm / rel).read_bytes())
            # Restore the arm's RECORDED mode. Forcing 0755 here would have quietly erased the
            # entire difference between the two arms of a mode-only change.
            dest.chmod(0o755 if modes.get(rel, "").endswith("755") else 0o644)
        out["arms"][arm] = metric(tree, manifest)

    _write_json(args.out, out)
    for arm, res in out["arms"].items():
        print(arm, json.dumps(res.get("by_kind", res)))
    return 0


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
