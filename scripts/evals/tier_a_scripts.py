"""Exercise every repo-validation script two-sidedly: it must pass clean AND catch a real defect.

A validation script that cannot fail is the exact failure this program is named after, and six of
these nine gate CI. So each gets a clean arm at HEAD and a planted arm carrying a defect the script
exists to detect. Passing clean is not evidence; passing clean *and* catching the plant is.

Two scripts are warn-only by design and are asserted as such: they must REPORT the plant while
still exiting 0 (`check_cross_references.py`), or fail only under `--strict`
(`check_skill_descriptions.py`). Asserting the reported text rather than the exit code keeps them
honest without pretending they gate.

`backfill-releases.sh` gets no work arm. It creates git tags and GitHub Releases, which this run is
forbidden to do; only its missing-tool guard is exercised. Recorded as a limitation, not a pass.

Usage: tier_a_scripts.py --out <path> [--only a,b]
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
# NOT the string "python": it exists in the eval image but not on the host, and the mutation
# control runs on the host. Three rule oracles already shipped with that exact bug.
PY = sys.executable
TRACEBACK = "Traceback (most recent call last)"

# name -> (clean cmd, plant fn or None, plant expectation)
#   plant expectation: {"rc": 1} or {"reports": "<substring>", "rc": 0} for warn-only
SPECS: dict[str, dict] = {
    "check_cross_references.py": {
        "clean": [PY, "scripts/check_cross_references.py"],
        "plant": (
            "write",
            "rules/zzz-plant.md",
            "see .claude/rules/definitely-not-here.md\n",
        ),
        "expect": {"rc": 0, "reports": "definitely-not-here.md"},  # warn-only by design
    },
    "check_docs_consistency.py": {
        "clean": [PY, "scripts/check_docs_consistency.py"],
        "plant": ("sed", "pyproject.toml", ('^version = ".*"', 'version = "99.99.99"')),
        "expect": {"rc": 1, "reports": "version drift"},
    },
    "check_rule_sizes.py": {
        "clean": [PY, "scripts/check_rule_sizes.py"],
        "plant": ("write", "rules/zzz-huge.md", "x" * 45000),
        "expect": {"rc": 1, "reports": "zzz-huge.md"},
    },
    "check_mcp_pins.py": {
        "clean": [PY, "scripts/check_mcp_pins.py"],
        "plant": ("unpin", "catalog/mcp.yaml", None),
        "expect": {"rc": 1, "reports": "exact version"},
    },
    "gen_hooks.py": {
        "clean": [PY, "scripts/gen_hooks.py", "--check"],
        "plant": ("drop-hook", "hooks/hooks.json", None),
        "expect": {"rc": 1, "reports": "hooks.json"},
    },
    "check_skill_descriptions.py": {
        "clean": [PY, "scripts/check_skill_descriptions.py"],
        "plant": ("strict-flag", None, None),  # the script's own opt-in gate
        "expect": {"rc": 1, "reports": "SKILL.md"},
    },
    "init.sh": {
        "clean": ["bash", "scripts/init.sh", "@TMP@"],
        "plant": None,
        "expect": None,
        "clean_expect": {"files": ["@TMP@/.claude/rules", "@TMP@/CLAUDE.md"]},
    },
    "capture-sdlc-run.sh": {
        "clean": ["bash", str(REPO / "scripts/capture-sdlc-run.sh")],
        "plant": None,
        "expect": None,
        "clean_cwd_tmp": True,
        "clean_expect": {"rc": 0, "reports": "REDACTION-CHECKLIST.md"},
    },
    "backfill-releases.sh": {
        "clean": None,  # creates git tags and GitHub Releases -- forbidden for this run
        "plant": ("guard", None, None),
        "expect": {"rc": 1, "reports": "required tool not found"},
        "note": "work arm NOT RUN: creates tags/releases; only the missing-tool guard is exercised",
    },
}


def sh(cmd: list[str], cwd: pathlib.Path) -> tuple[int, str]:
    p = subprocess.run(
        cmd, cwd=cwd, capture_output=True, text=True, errors="replace", timeout=900
    )
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def worktree(tmp: pathlib.Path) -> pathlib.Path:
    """A writable copy of the payload, without .git or this run's state."""
    d = pathlib.Path(tempfile.mkdtemp(dir=tmp))
    shutil.copytree(
        REPO,
        d / "repo",
        ignore=shutil.ignore_patterns(".git", "state", "__pycache__", "*.pyc"),
        symlinks=True,
    )
    return d / "repo"


def apply_plant(kind: str, target: str | None, arg, root: pathlib.Path) -> None:
    if kind == "write":
        (root / target).write_text(arg, encoding="utf-8")
    elif kind == "sed":
        import re

        p = root / target
        pat, rep = arg
        p.write_text(
            re.sub(pat, rep, p.read_text(), count=1, flags=re.M), encoding="utf-8"
        )
    elif kind == "unpin":
        import re

        p = root / target
        p.write_text(
            re.sub(r"@\d[\d.]*", "@latest", p.read_text(), count=1), encoding="utf-8"
        )
    elif kind == "drop-hook":
        p = root / target
        d = json.loads(p.read_text())
        d["hooks"].pop(next(iter(d["hooks"])))
        p.write_text(json.dumps(d), encoding="utf-8")
    elif kind in ("strict-flag", "guard"):
        pass  # handled by the caller's command
    else:
        raise SystemExit(f"unknown plant kind {kind!r}")


def judge(rc: int, out: str, expect: dict) -> tuple[bool, str]:
    problems = []
    if "rc" in expect and rc != expect["rc"]:
        problems.append(f"rc={rc} (want {expect['rc']})")
    if expect.get("reports") and expect["reports"] not in out:
        problems.append(f"output never mentions {expect['reports']!r}")
    if TRACEBACK in out:
        problems.append("crashed with a traceback")
    return (not problems), ("; ".join(problems) or "behaved as specified")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--only", default="")
    # Control: skip applying the plant but still judge the plant arm. Every planted arm must then
    # FAIL, which is what proves the arm is detecting the defect rather than passing regardless.
    ap.add_argument("--no-plant", action="store_true")
    a = ap.parse_args()
    only = {x.strip() for x in a.only.split(",") if x.strip()}

    rows = []
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="ck-tas-"))
    try:
        for name, spec in SPECS.items():
            if only and name not in only:
                continue
            row: dict = {"script": name, "arms": {}}
            if spec.get("note"):
                row["note"] = spec["note"]

            if spec["clean"]:
                root = worktree(tmp)
                scratch = pathlib.Path(tempfile.mkdtemp(dir=tmp))
                cmd = [c.replace("@TMP@", str(scratch)) for c in spec["clean"]]
                cwd = scratch if spec.get("clean_cwd_tmp") else root
                rc, out = sh(cmd, cwd)
                ce = dict(spec.get("clean_expect") or {"rc": 0})
                files = [f.replace("@TMP@", str(scratch)) for f in ce.pop("files", [])]
                ok, why = judge(rc, out, ce)
                for f in files:
                    if not pathlib.Path(f).exists():
                        ok, why = False, f"did not create {pathlib.Path(f).name}"
                row["arms"]["clean"] = {"ok": ok, "why": why, "rc": rc}
            else:
                row["arms"]["clean"] = {"ok": None, "why": "not run by policy"}

            if spec["plant"]:
                kind, target, arg = spec["plant"]
                root = worktree(tmp)
                if not a.no_plant:
                    apply_plant(kind, target, arg, root)
                cmd = list(spec["clean"] or ["bash", "scripts/backfill-releases.sh"])
                if kind == "strict-flag":
                    cmd = cmd + ["--strict"]
                rc, out = sh(cmd, root)
                ok, why = judge(rc, out, spec["expect"])
                row["arms"]["plant"] = {"ok": ok, "why": why, "rc": rc}
            else:
                row["arms"]["plant"] = {"ok": None, "why": "no planted arm defined"}

            oks = [v["ok"] for v in row["arms"].values() if v["ok"] is not None]
            row["exercised"] = bool(oks) and all(oks)
            rows.append(row)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    pathlib.Path(a.out).write_text(
        json.dumps({"rows": rows}, indent=2) + "\n", encoding="utf-8"
    )
    good = [r for r in rows if r["exercised"]]
    print(f"tier A scripts: {len(good)}/{len(rows)} exercised two-sidedly")
    for r in rows:
        if not r["exercised"]:
            for arm, v in r["arms"].items():
                if v["ok"] is False:
                    print(f"  [FAIL] {r['script']:<30} {arm}: {v['why']}")
    return 0 if len(good) == len(rows) else 1


if __name__ == "__main__":
    sys.exit(main())
