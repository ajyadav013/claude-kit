"""Prove each checker can fail, then record the proof.

The named failure mode of this whole run is "a checker that cannot fail reports CLEAN on a broken
payload". Nineteen recorded instances say the risk is not theoretical. `meta_check.py` refuses to
open the batch gate unless every checker carries a control taken at the current commit; this script
is what earns those entries.

A control is TWO-SIDED. One direction alone is worthless:

  detects   given a payload with a planted defect, the checker reports it. A checker that always
            says CLEAN passes no control.
  clean     given the real, unmutated payload, the checker does NOT report that defect. A checker
            that always says BROKEN is equally useless, and it is the easier failure to miss
            because a noisy checker still looks vigilant.

What these controls DO cover, stated so it is not overclaimed:

  static_eval.py   precise. A specific violation is planted in a copy of the payload and the
                   specific finding must appear -- and must be absent without the plant.
  the oracles      COARSE. It proves the oracle DISCRIMINATES: an empty workspace fails, a real
                   completed workspace passes at least one check. It does NOT prove every
                   individual check inside the oracle is wired up. E-034 was exactly a
                   per-check false negative inside an oracle that discriminated fine overall,
                   so this control would NOT have caught it. Recorded as a limitation, not
                   resolved. Per-check controls are the next increment.

Usage: mutation_controls.py --out <registry.json> [--sha SHA] [--workspaces DIR]
"""

from __future__ import annotations

import argparse
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parents[2]

# oracle -> a scenario workspace prefix that reached a real completed end state
ORACLE_WORKSPACES = {
    "tests/evals/e2e/oracles/rd_rules.py": "RD-RULES-shipped-config",
    "tests/evals/e2e/oracles/ra_rules.py": "RA-RULES-shipped-config",
    "tests/evals/e2e/oracles/rb_rules.py": "RB-RULES-shipped-config",
    "tests/evals/e2e/oracles/rc_rules.py": "RC-RULES-shipped-config",
    "tests/evals/e2e/oracles/sc01_docs_only.py": "SC-01",
    "tests/evals/e2e/oracles/sc02_bug_fix.py": "SC-02-sdlcfull",
}


def run(cmd: list[str], cwd: pathlib.Path | None = None) -> tuple[int, str]:
    p = subprocess.run(
        cmd, cwd=cwd, capture_output=True, text=True, errors="replace", timeout=300
    )
    return p.returncode, p.stdout


def oracle_checks(oracle: pathlib.Path, work: pathlib.Path) -> dict | None:
    """Run an oracle against a workspace and return its parsed verdict, or None if unparseable."""
    _, out = run([sys.executable, str(oracle), str(work)])
    start = out.find("{")
    if start < 0:
        return None
    try:
        return json.loads(out[start:])
    except json.JSONDecodeError:
        return None


def control_oracle(rel: str, prefix: str, ws_root: pathlib.Path) -> dict:
    """Coarse discrimination control: empty workspace must fail, real workspace must pass a check."""
    oracle = REPO / rel
    entry: dict = {"checker": rel, "kind": "discrimination", "detected": False}
    matches = sorted(ws_root.glob(f"{prefix}*"))
    if not matches:
        entry["error"] = (
            f"no preserved workspace matching {prefix}*; control could not run"
        )
        return entry
    real = matches[-1]
    entry["workspace"] = real.name

    with tempfile.TemporaryDirectory() as td:
        empty = pathlib.Path(td) / "empty"
        empty.mkdir()
        broken = oracle_checks(oracle, empty)
    good = oracle_checks(oracle, real)

    if broken is None or good is None:
        entry["error"] = (
            "oracle produced no parseable verdict on one side of the control"
        )
        return entry

    # A crash-to-nothing is not a FAIL. The oracle must have produced real check records.
    broken_fails = [c["check"] for c in broken.get("checks", []) if not c["pass"]]
    good_passes = [c["check"] for c in good.get("checks", []) if c["pass"]]
    entry["fails_on_empty"] = broken_fails
    entry["passes_on_real"] = good_passes
    entry["detected"] = bool(broken_fails) and bool(good_passes)
    if not entry["detected"]:
        entry["error"] = (
            "oracle does not discriminate: "
            f"{len(broken_fails)} failures on an empty workspace, "
            f"{len(good_passes)} passes on a completed one"
        )
    return entry


def control_static_eval() -> dict:
    """Precise control: plant a fan-out violation in a payload copy; the finding must appear.

    The target must be a NON-coordinating tier. The first version planted `Agent` on
    `agents/developer.md`, which is `tier: stage-lead` -- a coordinating tier that is ALLOWED to
    hold it. The control therefore planted a defect that is not a defect and reported that the
    checker was blind. Choosing the plant site wrongly is as fatal as parsing the result wrongly.
    """
    rel = "scripts/evals/static_eval.py"
    TARGET_ID = "agent:tester"  # tier: specialist -- verified NOT a coordinating tier
    entry: dict = {"checker": rel, "kind": "planted-defect", "detected": False}
    manifest = REPO / ".claude/state/full-self-evaluation/component-manifest.json"
    if not manifest.is_file():
        entry["error"] = "no component manifest; control could not run"
        return entry

    with tempfile.TemporaryDirectory() as td:
        tmp = pathlib.Path(td)
        payload = tmp / "payload"
        shutil.copytree(
            REPO,
            payload,
            symlinks=True,
            ignore=shutil.ignore_patterns(
                ".git", ".venv", "node_modules", "__pycache__", "dist", ".claude"
            ),
        )
        target = payload / "agents/tester.md"
        if not target.is_file():
            entry["error"] = "agents/tester.md absent; control could not run"
            return entry

        def findings(where: pathlib.Path, tag: str) -> list[dict]:
            out = tmp / f"{tag}.json"
            run(
                [
                    sys.executable,
                    str(REPO / rel),
                    "--manifest",
                    str(manifest),
                    "--payload",
                    str(where),
                    "--out",
                    str(out),
                    "--ids",
                    TARGET_ID,
                ]
            )
            # `--ids` is required. Omitting it made argparse exit(2) before writing anything, and
            # this function returned [] for BOTH sides -- so "no new finding" meant "the checker
            # never ran". A control that cannot tell those apart is the bug it exists to detect.
            if not out.is_file():
                raise RuntimeError(
                    f"static_eval wrote no output for the {tag} side; the control did not run"
                )
            doc = json.loads(out.read_text(encoding="utf-8"))
            # static_eval writes {"records": [{"id":..., "findings":[...]}, ...]}. The first
            # version of this control looked for a top-level "findings" key, found nothing on
            # BOTH sides, and concluded "no new finding" -- a control that could not fail.
            flat = []
            for rec in doc.get("records", []):
                for f in rec.get("findings", []):
                    flat.append({**f, "component": rec.get("id")})
            return flat

        clean = findings(payload, "clean")
        text = target.read_text(encoding="utf-8")
        if "\ntools:" in text:
            planted = text.replace(
                "\ntools:", "\ntools: Read, Write, Edit, Bash, Agent\nold_tools:", 1
            )
        else:
            planted = text.replace("\n---", "\ntools: Read, Agent\n---", 1)
        target.write_text(planted, encoding="utf-8")
        dirty = findings(payload, "dirty")

    def fanout(fs: list[dict]) -> set[str]:
        return {
            str(f.get("component") or f.get("id") or "?")
            for f in fs
            if isinstance(f, dict) and f.get("check") == "fanout_authority"
        }

    before, after = fanout(clean), fanout(dirty)
    entry["fanout_before"] = sorted(before)
    entry["fanout_after"] = sorted(after)
    entry["detected"] = bool(after - before)
    if not entry["detected"]:
        entry["error"] = (
            "planting the `Agent` tool on a specialist agent produced no new fanout_authority "
            "finding; the check cannot see the violation it exists to catch"
        )
    return entry


def control_meta_check() -> dict:
    rel = "scripts/evals/meta_check.py"
    rc, out = run([sys.executable, str(REPO / rel), "--self-test"])
    return {
        "checker": rel,
        "kind": "planted-defect",
        "detected": rc == 0,
        "detail": out.strip().splitlines()[-1] if out.strip() else "no output",
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--sha", default="")
    ap.add_argument("--workspaces", default="")
    args = ap.parse_args()

    sha = args.sha or run(["git", "rev-parse", "--short", "HEAD"], REPO)[1].strip()
    ws_root = (
        pathlib.Path(args.workspaces)
        if args.workspaces
        else pathlib.Path(tempfile.gettempdir()) / "ck-eval-scenarios"
    )

    def guarded(fn, name):
        try:
            return fn()
        except Exception as exc:  # a control that errors is NOT a control that passed
            return {
                "checker": name,
                "kind": "planted-defect",
                "detected": False,
                "error": f"control raised: {exc}",
            }

    controls = [
        guarded(control_static_eval, "scripts/evals/static_eval.py"),
        guarded(control_meta_check, "scripts/evals/meta_check.py"),
    ]
    for rel, prefix in ORACLE_WORKSPACES.items():
        controls.append(control_oracle(rel, prefix, ws_root))
    for c in controls:
        c["sha"] = sha

    ok = sum(1 for c in controls if c["detected"])
    print(f"mutation controls at {sha}\n")
    for c in controls:
        mark = "PASS" if c["detected"] else "FAIL"
        print(f"  [{mark}] {c['checker']:<45} {c['kind']}")
        if c.get("error"):
            print(f"         {c['error']}")
    print(f"\n{ok}/{len(controls)} checkers proved they can fail")

    pathlib.Path(args.out).write_text(
        json.dumps({"sha": sha, "controls": controls}, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {args.out}")
    return 0 if ok == len(controls) else 1


if __name__ == "__main__":
    sys.exit(main())
