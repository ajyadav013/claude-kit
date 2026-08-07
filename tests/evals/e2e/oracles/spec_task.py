"""Deterministic oracle driven by a per-scenario spec, for the task-bank scenarios.

Thirty-four task-bank rows are runnable and each needs a deterministic oracle. Hand-writing
thirty-four is not the bar being lowered here -- the bar is that every check stays a file
comparison, a regex, or a real interpreter exit code, with no LLM judging anything. What this file
adds is that the *checks* live in data (`tests/evals/e2e/task-specs.json`) instead of in code, so
the same audited runner executes all of them.

The obvious way for this to go wrong is a spec written loose enough that anything passes, which is
the "checker that cannot fail" failure mode wearing a config file. Three things guard it:

  * the spec is LOCKED before any run -- its sha256 goes into task-bank-lock.json, and this runner
    refuses to grade against a spec whose hash has moved. Tuning a spec after seeing output is not
    prevented by good intentions; it is prevented by the run refusing.
  * `behaviours` are SEALED HOLDOUTS. They are executed against the workspace's code but never
    written into the workspace, so a session cannot satisfy them by editing the thing that checks
    it -- the SC-02 design, generalised.
  * the visible suite is re-run from a PRISTINE copy of the fixture's tests. Editing the
    workspace's own tests to agree with broken behaviour changes nothing the oracle looks at.

A spec that declares no `behaviours` is rejected outright rather than passing vacuously: a scenario
with nothing to falsify has not been specified.

Usage: spec_task.py <workdir> --scenario <id>   (exit 0 = PASS, 1 = FAIL; prints a JSON verdict)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

# run-scenario.sh copies the oracle to <workspace>/.scenario/oracle.py before running it in
# Docker, where parents[4] is above / and raises. Prefer siblings of the script -- which is where
# the harness stages the spec and the lock -- and fall back to the repo layout when running in
# place. Staging happens only AFTER the session ends, so the specs are still sealed from the run.
_HERE = Path(__file__).resolve().parent
_PARENTS = Path(__file__).resolve().parents
REPO = _PARENTS[4] if len(_PARENTS) > 4 else _HERE


def _staged(name: str, repo_rel: str) -> Path:
    local = _HERE / name
    return local if local.is_file() else REPO / repo_rel


SPECS = _staged("task-specs.json", "tests/evals/e2e/task-specs.json")
LOCK = _staged(
    "task-bank-lock.json", ".claude/state/full-self-evaluation/task-bank-lock.json"
)


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def run_py(
    work: Path, code: str, timeout: int = 120
) -> subprocess.CompletedProcess[str]:
    env = dict(
        os.environ,
        PYTHONPATH=str(work / "src"),
        PYTHONDONTWRITEBYTECODE="1",
    )
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=work,
        env=env,
        capture_output=True,
        text=True,
        errors="replace",
        timeout=timeout,
    )


def pytest_on(
    work: Path, target: Path, deselect: list[str] | None = None
) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ, PYTHONPATH=str(work / "src"), PYTHONDONTWRITEBYTECODE="1")
    # Address the target relative to cwd: pytest matches --deselect against collected node ids,
    # which are rootdir-relative, so an absolute path silently deselects nothing.
    rel = target.relative_to(work) if target.is_relative_to(work) else target
    args = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", str(rel)]
    for node in deselect or []:
        args += ["--deselect", f"{rel}/{node}"]
    return subprocess.run(
        args,
        cwd=work,
        env=env,
        capture_output=True,
        text=True,
        errors="replace",
        timeout=600,
    )


def count_tests(root: Path) -> int:
    n = 0
    for f in root.rglob("test_*.py"):
        n += len(re.findall(r"^def (test_\w+)", f.read_text(errors="replace"), re.M))
    for f in root.rglob("*.test.js"):
        n += len(re.findall(r"\btest\s*\(", f.read_text(errors="replace")))
    return n


def check_spec(work: Path, spec: dict, checks: list[dict]) -> None:
    # The baseline is the pristine fixture. run-scenario.sh stages it beside the oracle; in-repo
    # runs read it from the fixtures tree. Getting this path wrong is NOT harmless: `unchanged:`
    # compares against it, and a missing baseline made `a.is_file()` false, which rendered as
    # "MODIFIED or missing" -- five scenarios were reported as having tampered with a file that
    # was byte-identical. min_new_tests reads it too, and silently counted a 0 baseline. So an
    # absent baseline is now a loud failed check rather than a comparison against nothing.
    staged = _HERE / "pristine"
    fixture = (
        staged
        if staged.is_dir()
        else REPO / "tests/evals/e2e/fixtures" / spec["fixture"]
    )
    if not fixture.is_dir():
        checks.append(
            {
                "check": "fixture_baseline_present",
                "pass": False,
                "detail": f"no pristine baseline at {fixture}; unchanged/min_new_tests cannot be judged",
            }
        )
        return

    # 1. Sealed holdouts. Executed against the workspace, never written into it.
    for b in spec["behaviours"]:
        r = run_py(work, b["code"])
        checks.append(
            {
                "check": f"behaviour:{b['name']}",
                "pass": r.returncode == 0,
                "detail": (r.stdout + r.stderr).strip()[-300:] or "exit 0",
            }
        )

    # 2. The visible suite, re-run from a PRISTINE copy so workspace test edits cannot help.
    #
    #    A fixture test can pin the very defect a scenario asks the session to remove -- dbservice's
    #    totals test asserts one statement per customer, which IS the N+1 that SC-14 must fix. Such a
    #    test cannot simply be rewritten, because the same fixture serves scenarios whose correct
    #    answers contradict each other (SC-22 removes customer ids from the SQL; SC-14 requires them
    #    covered). So a spec may deselect a named test, but must say why, and spec_discrimination.py
    #    refuses any exclusion that is not load-bearing -- an exclusion whose test would have passed
    #    anyway is an unjustified hole, not a documented one.
    excludes = spec.get("pristine_suite_excludes", [])
    if (fixture / "tests").is_dir():
        pristine = work / ".__pristine_tests"
        if pristine.exists():
            shutil.rmtree(pristine)
        shutil.copytree(fixture / "tests", pristine)
        r = pytest_on(work, pristine, [e["test"] for e in excludes])
        detail = (r.stdout or "")[-300:]
        if excludes:
            detail += " | deselected: " + "; ".join(
                f"{e['test']} ({e['reason']})" for e in excludes
            )
        # pytest exits 5 when it collects nothing. A scenario that rewrites every public signature
        # (SC-13) legitimately deselects the whole fixture suite, and failing the solution for that
        # would be failing it for the wrong reason -- but silently passing would hide that this
        # check contributed no regression signal at all. So: not a failure, and never silent.
        #
        # `pass: None` rather than True (F-080). A check that has just printed "this check proved
        # nothing" must not contribute a PASS to an all-checks-pass verdict exactly as if it had
        # proved something. None is a third state the aggregator excludes from the tally, so the
        # verdict is decided only by checks that actually ran.
        vacuous = r.returncode == 5 and bool(excludes)
        checks.append(
            {
                "check": "pristine_suite_passes",
                "pass": None if vacuous else r.returncode == 0,
                "vacuous": vacuous,
                "detail": (
                    "VACUOUS -- every pristine test deselected; this check proved nothing. "
                    + detail
                )
                if vacuous
                else detail,
            }
        )
        shutil.rmtree(pristine, ignore_errors=True)

    # 3. Content requirements, positive and negative.
    for req in spec.get("must_contain", []):
        f = work / req["file"]
        ok = f.is_file() and re.search(
            req["pattern"], f.read_text(errors="replace"), re.M | re.I
        )
        checks.append(
            {
                "check": f"contains:{req['file']}:{req['pattern'][:40]}",
                "pass": bool(ok),
                "detail": "found" if ok else "absent (or file missing)",
            }
        )
    for req in spec.get("must_not_contain", []):
        f = work / req["file"]
        hit = f.is_file() and re.search(
            req["pattern"], f.read_text(errors="replace"), re.M | re.I
        )
        checks.append(
            {
                "check": f"absent:{req['file']}:{req['pattern'][:40]}",
                "pass": not hit,
                "detail": "still present" if hit else "gone",
            }
        )

    # 4. New tests, counted against the pristine fixture rather than an absolute number: a fixture
    #    that already ships tests must not let a session claim credit for them.
    if spec.get("min_new_tests"):
        before, after = count_tests(fixture), count_tests(work)
        checks.append(
            {
                "check": f"min_new_tests>={spec['min_new_tests']}",
                "pass": (after - before) >= spec["min_new_tests"],
                "detail": f"{before} -> {after}",
            }
        )

    # 5. Files the session must not have touched.
    for rel in spec.get("must_not_change", []):
        a, b = fixture / rel, work / rel
        same = a.is_file() and b.is_file() and sha(a) == sha(b)
        checks.append(
            {
                "check": f"unchanged:{rel}",
                "pass": same,
                "detail": "identical" if same else "MODIFIED or missing",
            }
        )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("workdir")
    ap.add_argument("--scenario", required=True)
    a = ap.parse_args()

    if not Path("/.dockerenv").exists():
        print("refusing to run project code outside Docker", file=sys.stderr)
        return 2

    # The lock is the whole anti-tuning story: grading against a spec file that has moved since it
    # was sealed would let a failing run be argued away by editing its own success criteria.
    specs = json.loads(SPECS.read_text())
    if LOCK.is_file():
        locked = json.loads(LOCK.read_text()).get("task_specs_sha256")
        if locked and locked != sha(SPECS):
            print(
                json.dumps(
                    {
                        "oracle": "spec_task",
                        "pass": False,
                        "scenario": a.scenario,
                        "checks": [
                            {
                                "check": "spec_lock",
                                "pass": False,
                                "detail": f"task-specs.json sha256 {sha(SPECS)[:16]} != locked {locked[:16]}",
                            }
                        ],
                    },
                    indent=2,
                )
            )
            return 1

    spec = specs.get(a.scenario)
    if not spec:
        print(f"no spec for scenario {a.scenario}", file=sys.stderr)
        return 2
    if not spec.get("behaviours"):
        print(
            f"spec {a.scenario} declares no behaviours; nothing to falsify",
            file=sys.stderr,
        )
        return 2

    checks: list[dict] = []
    check_spec(Path(a.workdir), spec, checks)
    # A check with pass=None reported that it proved nothing (F-080). It is excluded from the
    # tally rather than counted either way -- but a verdict resting on NO effective check is not
    # a pass, or "every check was vacuous" would read identically to "every check passed".
    effective = [c for c in checks if c["pass"] is not None]
    ok = bool(effective) and all(c["pass"] for c in effective)
    vacuous = [c["check"] for c in checks if c["pass"] is None]
    print(
        json.dumps(
            {
                "oracle": "spec_task",
                "scenario": a.scenario,
                "pass": ok,
                "effective_checks": len(effective),
                "vacuous_checks": vacuous,
                "checks": checks,
            },
            indent=2,
        )
    )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
