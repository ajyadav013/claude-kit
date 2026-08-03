"""Mutation control for the bi-directional discrimination gate.

The gate exists to catch specs that cannot distinguish solved from untouched. If the gate itself
silently passed everything, the whole task bank would be unverified and look fine -- so this control
feeds it three known-bad behaviours and fails unless it flags each one:

  M1  a discriminator that already passes on the pristine fixture (measures nothing)
  M2  a discriminator that can never pass, the over-escaped-regex shape that started this
  M3  a guard that does not hold on the pristine fixture

It also feeds the real bank through unchanged and fails if that does NOT come back clean, so the
control cannot pass merely by rejecting everything.
"""

from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import tempfile

GATE = pathlib.Path(__file__).with_name("spec_discrimination.py")
REAL = pathlib.Path("/repo/tests/evals/e2e/task-specs.json")

MUTANTS = {
    "M1_discriminator_passes_on_baseline": {
        "SC-04": {
            "label": "mutant",
            "fixture": "pyservice",
            "task": "n/a",
            "behaviours": [
                {
                    "name": "already_true_on_baseline",
                    "kind": "discriminator",
                    "code": "from calc import add\nassert add(1, 1) == 2",
                }
            ],
        }
    },
    "M2_discriminator_can_never_pass": {
        "SC-10": {
            "label": "mutant",
            "fixture": "dbservice",
            "task": "n/a",
            "behaviours": [
                {
                    "name": "over_escaped_regex",
                    "kind": "discriminator",
                    # \\s matches a literal backslash then 's' -- never present in real SQL.
                    "code": (
                        "import pathlib, re\n"
                        "sql = '\\n'.join(p.read_text() for p in pathlib.Path('migrations').glob('*.sql'))\n"
                        "assert re.search(r'CREATE\\\\s+INDEX', sql, re.I)"
                    ),
                }
            ],
        }
    },
    "M3_guard_does_not_hold": {
        "SC-04": {
            "label": "mutant",
            "fixture": "pyservice",
            "task": "n/a",
            "behaviours": [
                {
                    "name": "guard_that_is_false",
                    "kind": "guard",
                    "code": "from calc import add\nassert add(1, 1) == 99",
                }
            ],
        }
    },
}


def run(spec_path: pathlib.Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(GATE), "--specs", str(spec_path)],
        capture_output=True,
        text=True,
        timeout=900,
    )


def main() -> int:
    if not pathlib.Path("/.dockerenv").exists():
        print("refusing to run fixture code outside Docker", file=sys.stderr)
        return 2

    failures: list[str] = []
    tmp = pathlib.Path(tempfile.mkdtemp())

    for name, bank in MUTANTS.items():
        p = tmp / f"{name}.json"
        p.write_text(json.dumps(bank))
        r = run(p)
        caught = r.returncode == 1 and "NON-DISCRIMINATING" in r.stdout
        print(f"{name:38} -> exit {r.returncode} {'CAUGHT' if caught else 'ESCAPED (control failure)'}")
        if not caught:
            failures.append(name)
            print(r.stdout[-400:])

    r = run(REAL)
    clean = r.returncode == 0
    print(f"{'real bank (must stay clean)':38} -> exit {r.returncode} {'clean' if clean else 'REGRESSED'}")
    if not clean:
        failures.append("real bank no longer clean")
        print(r.stdout[-600:])

    print()
    if failures:
        print("CONTROL FAILED:", failures)
        return 1
    print("Control passed: the gate catches all three defect shapes and still clears the real bank.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
