"""Bi-directional discrimination gate for the task-bank specs.

A spec behaviour is only worth running if it can distinguish a solved workspace from an untouched
one. The obvious gate -- "every behaviour must fail on the pristine fixture" -- is not enough, and
believing it was cost this program a whole spec bank: a check that can *never* match also fails on
the pristine fixture, so it scores as a healthy discriminator while being incapable of ever passing.
Over-escaped regexes (``CREATE\\\\s+INDEX``, matching a literal backslash) failed exactly that way.

So each behaviour declares a `kind` and is verified in BOTH directions:

  * `discriminator` -- MUST fail on the pristine fixture and MUST pass on the solved reference.
    Failing the first means it measures nothing; failing the second means it can never be satisfied,
    and would report every correct solution as broken.
  * `guard` -- a regression check. MUST pass on both. Its falsifier is a *bad* candidate, not the
    baseline, so demanding it fail on the baseline is the wrong test.

The solved references live in tests/evals/e2e/solutions/<scenario>/ and are overlaid onto a copy of
the fixture. They are reference *answers*, never shown to a task performer.

Exit 0 = every behaviour discriminates. Exit 1 = at least one does not.
"""

from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

REPO = pathlib.Path("/repo")
SPECS = REPO / "tests/evals/e2e/task-specs.json"
FIXTURES = REPO / "tests/evals/e2e/fixtures"
SOLUTIONS = REPO / "tests/evals/e2e/solutions"


def materialise(fixture: str, solution: str | None) -> str:
    """Copy the fixture into a temp dir, optionally overlaying the solved reference."""
    tmp = tempfile.mkdtemp()
    work = os.path.join(tmp, "w")
    shutil.copytree(FIXTURES / fixture, work)
    if solution:
        src = SOLUTIONS / solution
        if not src.is_dir():
            raise FileNotFoundError(f"no solved reference at {src}")
        shutil.copytree(src, work, dirs_exist_ok=True)
    return work


def behaves(work: str, code: str) -> bool:
    env = dict(os.environ, PYTHONPATH=os.path.join(work, "src"), PYTHONDONTWRITEBYTECODE="1")
    r = subprocess.run(
        [sys.executable, "-c", code], cwd=work, env=env, capture_output=True, text=True, timeout=120
    )
    return r.returncode == 0


def main() -> int:
    if not pathlib.Path("/.dockerenv").exists():
        print("refusing to run fixture code outside Docker", file=sys.stderr)
        return 2

    # --specs exists so the mutation control can point the gate at a deliberately broken bank and
    # confirm it still fails. A gate never aimed at a known-bad input is an untested gate.
    spec_path = SPECS
    if "--specs" in sys.argv:
        spec_path = pathlib.Path(sys.argv[sys.argv.index("--specs") + 1])

    specs = json.loads(spec_path.read_text())
    violations: list[str] = []

    print(f"{'scenario':8} {'behaviour':34} {'kind':14} {'baseline':9} {'solved':7} verdict")
    print("-" * 92)

    for sid, spec in specs.items():
        if sid.startswith("_"):
            continue
        base = materialise(spec["fixture"], None)
        solved = materialise(spec["fixture"], sid)

        for b in spec["behaviours"]:
            kind = b.get("kind")
            if kind not in ("discriminator", "guard"):
                violations.append(f"{sid}:{b['name']} declares no valid kind")
                continue

            on_base = behaves(base, b["code"])
            on_solved = behaves(solved, b["code"])

            if kind == "discriminator":
                ok = (not on_base) and on_solved
                why = (
                    "OK"
                    if ok
                    else ("passes on baseline -- measures nothing" if on_base else "cannot pass even when solved")
                )
            else:
                ok = on_base and on_solved
                why = "OK" if ok else "guard does not hold -- broken check or broken fixture"

            if not ok:
                violations.append(f"{sid}:{b['name']} ({why})")

            print(
                f"{sid:8} {b['name']:34} {kind:14} "
                f"{'pass' if on_base else 'FAIL':9} {'pass' if on_solved else 'FAIL':7} "
                f"{'ok' if ok else 'VIOLATION: ' + why}"
            )

    print()
    if violations:
        print(f"NON-DISCRIMINATING ({len(violations)}):")
        for v in violations:
            print(f"  - {v}")
        return 1
    print("All behaviours discriminate in both directions.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
