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
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import uuid

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


def _arm(root: pathlib.Path, name: str, mode: str, tokens: int) -> None:
    d = root / f"{name}-20260101T000000Z"
    d.mkdir(parents=True)
    (d / "run.json").write_text(json.dumps({"rules_mode": mode}), encoding="utf-8")
    (d / "session.jsonl").write_text(
        json.dumps(
            {
                "type": "assistant",
                "message": {"usage": {"cache_creation_input_tokens": tokens}},
            }
        )
        + "\n",
        encoding="utf-8",
    )


def control_rule_load_proof() -> dict:
    """Synthetic arms with KNOWN deltas: an in-band one must prove, an out-of-band one must not.

    The load proof is the only instrument in this run that produced findings unobtainable by
    reading the repo, and it is the one whose verdicts have already been wrong in both directions
    (E-036: the band rejected six arms that were all loaded). A control that only fed it a loadable
    arm would confirm it says PROVEN and learn nothing.
    """
    rel = "scripts/evals/rule_load_proof.py"
    entry: dict = {"checker": rel, "kind": "planted-defect", "detected": False}
    rules = sorted((REPO / "rules").glob("*.md"))
    if len(rules) < 2:
        entry["error"] = "need two real rules to size the synthetic arms"
        return entry
    good, bad = rules[0], rules[1]
    base = 20_000

    with tempfile.TemporaryDirectory() as td:
        scen = pathlib.Path(td) / "SYNTH"
        scen.mkdir()
        _arm(scen, "control-norules", "none", base)
        # in band: bytes / 2.71 lands inside the 2.60-2.82 payload band
        _arm(
            scen,
            f"only-{good.stem}",
            f"only:{good.stem}",
            base + round(good.stat().st_size / 2.71),
        )
        # far out of band: a delta implying ~1.5 bytes/token cannot be this rule loading
        _arm(
            scen,
            f"only-{bad.stem}",
            f"only:{bad.stem}",
            base + round(bad.stat().st_size / 1.5),
        )
        out = pathlib.Path(td) / "proofs.json"
        rc, _ = run([sys.executable, str(REPO / rel), str(scen), "--json", str(out)])
        if not out.is_file():
            raise RuntimeError(
                f"rule_load_proof wrote no output (rc={rc}); the control did not run"
            )
        results = json.loads(out.read_text(encoding="utf-8"))

    verdicts = {r["rule"]: r["verdict"] for r in results if "rule" in r}
    entry["verdicts"] = verdicts
    proved_good = verdicts.get(good.stem) == "PROVEN"
    rejected_bad = verdicts.get(bad.stem) not in (None, "PROVEN")
    entry["detected"] = proved_good and rejected_bad
    if not entry["detected"]:
        entry["error"] = (
            f"expected {good.stem} PROVEN and {bad.stem} rejected; got "
            f"{verdicts.get(good.stem)} and {verdicts.get(bad.stem)}"
        )
    return entry


def control_stamp_provenance() -> dict:
    """Three-way control of the provenance chain: stamp, refuse to re-label, refuse to consume.

    The first version of this control tried to stamp an already-stamped report at a different sha
    and treated the resulting rc=3 as a broken stamper. It was the opposite: refusing to re-label a
    stale report as fresh is the tool's whole anti-laundering guard, and the control was asking it
    to commit the exact fraud it exists to prevent. Controlling the CORRECT contract instead:

      writes    an UNSTAMPED report gains the sha it was given
      refuses   an already-stamped report is NOT re-labelled to a different commit (rc=3)
      enforced  the consumer accepts the stamp at its own sha and ABORTS at any other

    E-029 was a stale report read as current, so the third leg is the one that matters most; the
    first two are what make it trustworthy.
    """
    rel = "scripts/evals/stamp-coverage-provenance.py"
    entry: dict = {"checker": rel, "kind": "planted-defect", "detected": False}
    src = REPO / ".claude/state/full-self-evaluation/latest-coverage.json"
    manifest = REPO / ".claude/state/full-self-evaluation/component-manifest.json"
    if not src.is_file() or not manifest.is_file():
        entry["error"] = (
            "no coverage report or manifest available; control could not run"
        )
        return entry

    planted = "0bad51a"
    with tempfile.TemporaryDirectory() as td:
        tmp = pathlib.Path(td)
        doc = json.loads(src.read_text(encoding="utf-8"))
        doc.pop("ck_provenance", None)
        bare = tmp / "unstamped.json"
        bare.write_text(json.dumps(doc), encoding="utf-8")

        stamped = tmp / "stamped.json"
        rc_write, _ = run(
            [sys.executable, str(REPO / rel), str(bare), planted, "--out", str(stamped)]
        )
        if not stamped.is_file():
            raise RuntimeError(
                f"stamper wrote no output for an UNSTAMPED report (rc={rc_write})"
            )
        got = (
            json.loads(stamped.read_text(encoding="utf-8")).get("ck_provenance") or {}
        ).get("sha")

        # Laundering attempt: same file, different commit. Must refuse.
        relabel = tmp / "relabelled.json"
        rc_relabel, _ = run(
            [
                sys.executable,
                str(REPO / rel),
                str(stamped),
                "feedfac",
                "--out",
                str(relabel),
            ]
        )

        def grade(coverage_sha: str) -> int:
            out = tmp / f"g-{coverage_sha}.json"
            code, _ = run(
                [
                    sys.executable,
                    str(REPO / "scripts/evals/static_eval.py"),
                    "--manifest",
                    str(manifest),
                    "--payload",
                    str(REPO),
                    "--ids",
                    "module:upgrader",
                    "--coverage",
                    str(stamped),
                    "--coverage-sha",
                    coverage_sha,
                    "--out",
                    str(out),
                ]
            )
            return code

        honoured = grade(planted)
        refused = grade("feedfac")

    entry.update(
        stamped_sha=got,
        rc_relabel_attempt=rc_relabel,
        relabel_written=relabel.name if relabel.exists() else None,
        rc_matching_sha=honoured,
        rc_mismatched_sha=refused,
    )
    entry["detected"] = (
        got == planted and rc_relabel == 3 and honoured == 0 and refused == 3
    )
    if not entry["detected"]:
        entry["error"] = (
            f"provenance chain not enforced: stamped={got!r} (want {planted!r}), "
            f"rc(relabel)={rc_relabel} (want 3), rc(match)={honoured} (want 0), "
            f"rc(mismatch)={refused} (want 3)"
        )
    return entry


def control_tier_b_reconcile() -> dict:
    """Two-sided: an unsupported mark must be caught, an honest manifest must not be flagged.

    This checker decides the dynamic-coverage number, so the failure that matters is it staying
    quiet about a component marked measured with nothing behind it -- which is precisely the
    state the live manifest was in when it was written (12 rows, one of them genuinely wrong).
    """
    entry = {
        "checker": "scripts/evals/tier_b_reconcile.py",
        "kind": "planted-defect + clean control",
    }
    script = REPO / "scripts/evals/tier_b_reconcile.py"
    with tempfile.TemporaryDirectory(prefix="ck-ctl-reconcile-") as tmp:
        state = pathlib.Path(tmp) / "state"
        (state / "raw/tier-b").mkdir(parents=True)
        live = REPO / ".claude/state/full-self-evaluation"
        shutil.copy2(
            live / "component-manifest.json", state / "component-manifest.json"
        )
        for g in sorted((live / "raw/tier-b").glob("runs*/grades.json")):
            dst = state / "raw/tier-b" / g.parent.name
            dst.mkdir(parents=True, exist_ok=True)
            shutil.copy2(g, dst / "grades.json")

        clean_rc = run([sys.executable, str(script), "--state", str(state)], REPO)[0]

        doc = json.loads(
            (state / "component-manifest.json").read_text(encoding="utf-8")
        )
        # Append a synthetic row rather than borrowing a real one: once every Tier B component
        # has been probed there is no unprobed row left to borrow, and a control that stops
        # working the moment the run succeeds is not a control.
        planted = f"skill:{uuid.uuid4().hex[:12]}-ghost"
        doc["components"].append(
            {
                "id": planted,
                "type": "skill",
                "tier": "B",
                "path": "skills/does-not-exist/SKILL.md",
                "dynamic_done": True,
                "dynamic_evidence": None,
            }
        )
        (state / "component-manifest.json").write_text(
            json.dumps(doc, indent=1) + "\n", encoding="utf-8"
        )
        rc, out = run([sys.executable, str(script), "--state", str(state)], REPO)

    entry["detected"] = clean_rc == 0 and rc == 1 and planted in out
    if not entry["detected"]:
        entry["error"] = (
            f"clean rc={clean_rc} (want 0); planted rc={rc} (want 1); "
            f"{planted} named in output: {planted in out}"
        )
    return entry


def control_tier_b_grader() -> dict:
    """Pins E-049/E-050: a dead session must not be scored, a live one must be.

    Both directions have already failed here. Scoring a session that never started produced 40
    fabricated skill defects; the fix then discarded four correct passes because it keyed on tool
    calls instead of on whether an answer came back. A control that only checked one direction
    would have certified each bug in turn.
    """
    entry = {
        "checker": "scripts/evals/tier_b_batches.py",
        "kind": "synthetic sessions, 3 arms",
    }
    script = REPO / "scripts/evals/tier_b_batches.py"

    def arm(tmp: pathlib.Path, label: str, rc: int, result: str, invoked: list) -> None:
        spec = tmp / "spec"
        spec.mkdir(parents=True, exist_ok=True)
        (spec / f"{label}.txt").write_text("1. do the thing\n", encoding="utf-8")
        d = tmp / "runs" / f"{label}-x"
        d.mkdir(parents=True, exist_ok=True)
        (d / "probe.json").write_text(
            json.dumps(
                {
                    "label": label,
                    "session_rc": rc,
                    "skills_invoked": invoked,
                    "tool_calls": ["Skill"] if invoked else [],
                }
            ),
            encoding="utf-8",
        )
        (d / "session.jsonl").write_text(
            json.dumps({"type": "result", "result": result}) + "\n", encoding="utf-8"
        )

    with tempfile.TemporaryDirectory(prefix="ck-ctl-grader-") as t:
        tmp = pathlib.Path(t)
        arm(tmp, "a1", 0, "done", ["alpha"])  # fired            -> INVOKED
        arm(tmp, "a2", 1, "", [])  # dead session     -> UNRUN, never MISSED
        arm(
            tmp, "a3", 0, "That's the `gamma` skill; underspecified.", []
        )  # prose -> NAMED
        spec = {
            "batches": [
                {
                    "label": "a1",
                    "targets": [{"id": "skill:alpha", "skill": "alpha"}],
                    "prompt_file": "a1.txt",
                },
                {
                    "label": "a2",
                    "targets": [{"id": "skill:beta", "skill": "beta"}],
                    "prompt_file": "a2.txt",
                },
                {
                    "label": "a3",
                    "targets": [{"id": "skill:gamma", "skill": "gamma"}],
                    "prompt_file": "a3.txt",
                },
            ],
            "decoys": [],
        }
        (tmp / "spec" / "batches.json").write_text(json.dumps(spec), encoding="utf-8")
        rc, out = run(
            [
                sys.executable,
                str(script),
                "grade",
                "--probe-dir",
                str(tmp / "runs"),
                "--spec",
                str(tmp / "spec" / "batches.json"),
            ],
            REPO,
        )
        graded = {}
        gp = tmp / "runs" / "grades.json"
        if gp.is_file():
            doc = json.loads(gp.read_text(encoding="utf-8"))
            graded = {r["skill"]: r.get("outcome") for r in doc["rows"]}
            unrun = doc.get("unrun", [])
        else:
            unrun = []

    want = {"alpha": "INVOKED", "gamma": "NAMED"}
    entry["detected"] = (
        rc == 0
        and graded.get("alpha") == "INVOKED"
        and graded.get("gamma") == "NAMED"
        and "beta" not in graded
        and "skill:beta" in unrun
    )
    if not entry["detected"]:
        entry["error"] = (
            f"rc={rc}; got {graded} (want {want}); beta must be UNRUN, unrun={unrun}"
        )
    return entry


def control_tier_c_reach() -> dict:
    """Plant one ghost per proof method; each must come back UNPROVEN.

    This checker reported 111/111 the first time it ran, which is the number least worth
    believing. Planting ghosts caught four separate ways it could not fail -- including a corpus
    that had absorbed the evaluator's own logs, so a fake doc proved itself against a previous
    run's stdout. One ghost per method, because each method fails independently.
    """
    entry = {
        "checker": "scripts/evals/tier_c_reach.py",
        "kind": "planted ghosts, one per method",
    }
    script = REPO / "scripts/evals/tier_c_reach.py"
    manifest = REPO / ".claude/state/full-self-evaluation/component-manifest.json"
    # Ghost names are generated at runtime. A hardcoded one fails for a stupid reason: this
    # control lives in scripts/, scripts/ is inside the reachability corpus, so the literal
    # "ghost-doc.md" written here became a real reference and the ghost proved itself against
    # the very file testing it.
    tag = uuid.uuid4().hex[:12]
    ghosts = [
        f"template-artifact:{tag}.md",
        f"schema:{tag}-schema.json",
        f"doc:{tag}-doc.md",
        f"profile:{tag}-profile",
        f"live-stack:{tag}-stack",
        f"unknown-type:{tag}",
    ]
    env = dict(os.environ, PYTHONPATH=str(REPO / "src"))
    missed = []
    with tempfile.TemporaryDirectory(prefix="ck-ctl-tierc-") as t:
        out = pathlib.Path(t) / "r.json"
        for g in ghosts:
            proc = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "--manifest",
                    str(manifest),
                    "--out",
                    str(out),
                    "--plant",
                    g,
                ],
                cwd=REPO,
                capture_output=True,
                text=True,
                errors="replace",
                timeout=900,
                env=env,
            )
            if not out.is_file():
                missed.append(f"{g}: no output ({proc.stderr.strip()[:80]})")
                continue
            rows = json.loads(out.read_text(encoding="utf-8"))["rows"]
            row = next((r for r in rows if r["id"] == g), None)
            if row is None:
                missed.append(f"{g}: ghost absent from output")
            elif row["proven"]:
                missed.append(f"{g}: proved itself -- {row.get('why')}")
    entry["detected"] = not missed
    if missed:
        entry["error"] = "; ".join(missed)
    return entry


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
        guarded(control_rule_load_proof, "scripts/evals/rule_load_proof.py"),
        guarded(control_stamp_provenance, "scripts/evals/stamp-coverage-provenance.py"),
        guarded(control_tier_b_reconcile, "scripts/evals/tier_b_reconcile.py"),
        guarded(control_tier_b_grader, "scripts/evals/tier_b_batches.py"),
        guarded(control_tier_c_reach, "scripts/evals/tier_c_reach.py"),
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
