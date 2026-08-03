"""Exercise every CLI command for real, twice: once where it should work, once where it cannot.

Tier A means a full scenario. For a CLI command that does not require a model session -- the
command is invoked explicitly, so criterion 1 is not in question -- but it does require that the
command actually do its job and that it fail honestly when it cannot. A `--help` check would be
exactly the bar-lowering dynamic-tiering.md's adversarial rule exists to catch, so nothing here
passes on `--help`.

Two arms per command:

  work     a real invocation with an observable effect asserted -- files created, a named string
           in the output, a non-empty report. Criteria 3, 5, 6.
  missing  the same command with its prerequisite absent. It must exit non-zero AND must not
           print a traceback. A traceback is the failure mode criterion 9 names: the command did
           not handle the missing prerequisite, it crashed into one. Criteria 9, 10.

A command with no specification is NOT_EXERCISED, which is not a pass.

Usage: tier_a_cli.py --out <path> [--only a,b,c] [--break-honesty]
  --break-honesty  mutation control: assert the honesty check can fail, by treating a traceback
                   as acceptable and confirming the arm then flips.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parents[2]
TRACEBACK = "Traceback (most recent call last)"

# setup kinds
EMPTY = "empty"  # a bare directory, nothing installed
SCAFFOLDED = "scaffolded"  # a real `init --defaults` project
PIPELINE = "pipeline"  # scaffolded + a seeded pipeline snapshot

SPEC: dict[str, dict] = {
    "version": {
        "work": (EMPTY, ["version"], {"stdout_matches": r"\d+\.\d+\.\d+"}),
        "missing": None,  # takes no input; there is no prerequisite it can lack
    },
    "list-options": {
        "work": (EMPTY, ["list-options"], {"stdout_contains": ["enterprise"]}),
        "missing": None,
    },
    "init": {
        "work": (
            EMPTY,
            ["init", ".", "--defaults"],
            {"files": ["CLAUDE.md", ".claude/settings.json", ".claude/rules"]},
        ),
        "missing": (EMPTY, ["init", "/nonexistent/deep/path", "--defaults"]),
    },
    "validate": {
        "work": (SCAFFOLDED, ["validate", "."], {"rc": 0}),
        "missing": (EMPTY, ["validate", "."]),
    },
    "doctor": {
        "work": (SCAFFOLDED, ["doctor", "."], {"rc": 0}),
        "missing": (EMPTY, ["doctor", "."]),
    },
    "diff": {
        "work": (SCAFFOLDED, ["diff", "."], {"rc": 0}),
        "missing": (EMPTY, ["diff", "."]),
    },
    "status": {
        "work": (SCAFFOLDED, ["status", "."], {"rc": 0}),
        "missing": (EMPTY, ["status", "."], {"rc0_if_mentions": ["not installed"]}),
    },
    "upgrade": {
        "work": (SCAFFOLDED, ["upgrade", "."], {"rc": 0}),
        "missing": (EMPTY, ["upgrade", "."]),
    },
    "export": {
        "work": (
            SCAFFOLDED,
            ["export", ".", "--target", "agents", "--defaults"],
            {"files": ["AGENTS.md"]},
        ),
        "missing": (
            SCAFFOLDED,
            ["export", ".", "--target", "no-such-target", "--defaults"],
        ),
    },
    "privacy-report": {
        "work": (SCAFFOLDED, ["privacy-report", "."], {"rc": 0}),
        "missing": (
            EMPTY,
            ["privacy-report", "."],
            {"rc0_if_mentions": ["no .claude/settings.json"]},
        ),
    },
    "tickets": {
        "work": (SCAFFOLDED, ["tickets", "--path", ".", "--json"], {"rc": 0}),
        "missing": (
            EMPTY,
            ["tickets", "--path", ".", "--json"],
            {"rc0_if_mentions": ['"store_exists": false']},
        ),
    },
    "pipeline:validate": {
        "work": (PIPELINE, ["pipeline", "validate", "."], {"rc": 0}),
        "missing": (
            SCAFFOLDED,
            ["pipeline", "validate", "."],
            {"rc0_if_mentions": ["no pipeline snapshot"]},
        ),
    },
    "pipeline:status": {
        "work": (PIPELINE, ["pipeline", "status", "."], {"rc": 0}),
        "missing": (
            SCAFFOLDED,
            ["pipeline", "status", "."],
            {"rc0_if_mentions": ["no pipeline run in progress"]},
        ),
    },
    "pipeline:close-gate": {
        "work": None,  # needs an evidence file + gate order; covered by the pipeline test suite
        "missing": (SCAFFOLDED, ["pipeline", "close-gate", "spec-complete", "."]),
    },
    "pipeline:skip-gate": {
        "work": None,
        "missing": (SCAFFOLDED, ["pipeline", "skip-gate", "spec-complete", "."]),
    },
    "pipeline:abort": {
        "work": (PIPELINE, ["pipeline", "abort", "."], {"rc": 0}),
        "missing": (
            SCAFFOLDED,
            ["pipeline", "abort", "."],
            {"rc0_if_mentions": ["nothing to abort"]},
        ),
    },
    "package-org-pack": {
        "work": None,
        "missing": (SCAFFOLDED, ["package-org-pack", "no-such-pack", "."]),
    },
    "install-org-pack": {
        "work": None,
        "missing": (SCAFFOLDED, ["install-org-pack", "/no/such/pack.zip", "."]),
    },
    "research:import-sources": {
        "work": None,  # would need network; the container runs with --network none by design
        "missing": (
            SCAFFOLDED,
            ["research:import-sources", "/no/such/sources.json", "."],
        ),
    },
}


def cli(args: list[str], cwd: pathlib.Path) -> tuple[int, str]:
    env = dict(os.environ, PYTHONPATH=str(REPO / "src"), CLAUDE_KIT_EXPERIMENTAL="1")
    p = subprocess.run(
        [sys.executable, "-m", "claude_kit.cli", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        errors="replace",
        timeout=600,
        env=env,
    )
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def make(kind: str, tmp: pathlib.Path) -> pathlib.Path:
    d = pathlib.Path(tempfile.mkdtemp(dir=tmp))
    if kind == EMPTY:
        return d
    rc, out = cli(["init", ".", "--defaults"], d)
    if rc != 0:
        raise SystemExit(f"fixture setup failed ({kind}): rc={rc} {out[-300:]}")
    if kind == PIPELINE:
        snap = d / ".claude/state/pipeline.json"
        snap.parent.mkdir(parents=True, exist_ok=True)
        snap.write_text(
            json.dumps(
                {
                    "schema": 1,
                    "mode": "A",
                    "task": "eval",
                    "status": "in_progress",
                    "profile": "standard",
                    "gate_history": [],
                }
            ),
            encoding="utf-8",
        )
    return d


def run_arm(
    kind: str,
    args: list[str],
    expect: dict | None,
    tmp: pathlib.Path,
    honesty_broken: bool,
) -> dict:
    d = make(kind, tmp)
    rc, out = cli(args, d)
    row = {"args": args, "rc": rc, "setup": kind}
    if expect is None or "rc0_if_mentions" in expect:
        # The `missing` arm. Default: exit non-zero, without a traceback.
        #
        # Read-only informational commands are the declared exception: `status` printing
        # "not installed -- run `claude-kit init` here" and exiting 0 IS handling a missing
        # prerequisite honestly, and my first spec called four such commands defective for it.
        # The allowance is per-command and must name the phrase, so it cannot become a blanket
        # "rc=0 is fine" that would pass a command which silently did nothing.
        crashed = TRACEBACK in out and not honesty_broken
        allow = (expect or {}).get("rc0_if_mentions") or []
        said_so = any(x.lower() in out.lower() for x in allow)
        row["ok"] = (rc != 0 or said_so) and not crashed
        row["why"] = (
            (
                "reported the missing prerequisite and exited 0"
                if rc == 0
                else "exited non-zero without a traceback"
            )
            if row["ok"]
            else (
                f"crashed with a traceback instead of reporting the missing prerequisite: "
                f"{out.strip().splitlines()[-1][:120] if out.strip() else ''}"
                if crashed
                else f"succeeded (rc=0) with its prerequisite absent -- {out.strip()[:120]}"
            )
        )
        return row
    problems = []
    if rc != expect.get("rc", 0):
        problems.append(f"rc={rc} (want {expect.get('rc', 0)}): {out.strip()[-160:]}")
    for f in expect.get("files", []):
        if not (d / f).exists():
            problems.append(f"missing expected artefact {f}")
    for s in expect.get("stdout_contains", []):
        if s not in out:
            problems.append(f"output never mentions {s!r}")
    pat = expect.get("stdout_matches")
    if pat:
        import re

        if not re.search(pat, out):
            problems.append(f"output does not match /{pat}/")
    row["ok"] = not problems
    row["why"] = (
        "; ".join(problems)
        if problems
        else "performed its job with an observable effect"
    )
    return row


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--only", default="")
    ap.add_argument("--break-honesty", action="store_true")
    a = ap.parse_args()
    only = {x.strip() for x in a.only.split(",") if x.strip()}

    rows = []
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="ck-tiera-"))
    try:
        for name, spec in SPEC.items():
            if only and name not in only:
                continue
            entry = {"command": name, "arms": {}}
            for arm in ("work", "missing"):
                s = spec.get(arm)
                if s is None:
                    entry["arms"][arm] = {"ok": None, "why": "not specified"}
                    continue
                kind, args = s[0], s[1]
                expect = s[2] if len(s) > 2 else None
                entry["arms"][arm] = run_arm(kind, args, expect, tmp, a.break_honesty)
            oks = [v["ok"] for v in entry["arms"].values() if v["ok"] is not None]
            entry["exercised"] = bool(oks) and all(oks)
            rows.append(entry)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    pathlib.Path(a.out).write_text(
        json.dumps({"rows": rows}, indent=2) + "\n", encoding="utf-8"
    )
    good = [r for r in rows if r["exercised"]]
    print(f"tier A CLI: {len(good)}/{len(rows)} exercised")
    for r in rows:
        if r["exercised"]:
            continue
        for arm, v in r["arms"].items():
            if v["ok"] is False:
                print(f"  [FAIL] {r['command']:<26} {arm}: {v['why']}")
            elif v["ok"] is None:
                print(f"  [----] {r['command']:<26} {arm}: {v['why']}")
    return 0 if len(good) == len(rows) else 1


if __name__ == "__main__":
    sys.exit(main())
