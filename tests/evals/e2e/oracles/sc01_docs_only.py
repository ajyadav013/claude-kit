"""Deterministic oracle for SC-01 — small documentation-only change.

Runs inside Docker against the scenario's end state. No LLM judges anything here: every assertion
is a file comparison, a git diff, or a test exit code, so the verdict is reproducible and cannot
drift with model behaviour.

The discriminating assertion is the SECOND one. Any run that edits the README passes the first
check; a *documentation-only* task is only satisfied if the source tree is byte-identical
afterwards. A pipeline that "helpfully" refactored `calc.py` while documenting it did not do the
task it was given, and that is exactly the failure this scenario exists to catch.

Usage: sc01_docs_only.py <workdir>   (exit 0 = PASS, 1 = FAIL; prints a JSON verdict)
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

SOURCE_FILES = ("src/calc.py", "tests/test_calc.py", "pyproject.toml")
# sha256 of the fixture's source files as shipped; recomputed from the pristine fixture by the
# runner and written to baseline-hashes.json, so this oracle never hardcodes a digest.


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main() -> int:
    work = Path(sys.argv[1])
    baseline = json.loads((work / ".scenario" / "baseline-hashes.json").read_text())
    checks: list[dict] = []

    def check(name: str, ok: bool, detail: str) -> None:
        checks.append({"check": name, "pass": bool(ok), "detail": detail})

    readme = (work / "README.md").read_text(encoding="utf-8")
    check(
        "readme_documents_subtract",
        "subtract" in readme,
        "README.md mentions `subtract`"
        if "subtract" in readme
        else "README.md still does not document subtract() — the requested change was not made",
    )

    drifted = [f for f in SOURCE_FILES if sha(work / f) != baseline[f]]
    check(
        "source_tree_untouched",
        not drifted,
        "source and tests are byte-identical to the fixture"
        if not drifted
        else f"a documentation-only task modified source files: {', '.join(drifted)}",
    )

    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"],
        cwd=work,
        capture_output=True,
        text=True,
    )
    check(
        "tests_still_pass",
        proc.returncode == 0,
        f"pytest exit {proc.returncode}: {(proc.stdout or proc.stderr).strip().splitlines()[-1:]}",
    )

    tracked = subprocess.run(
        ["git", "status", "--porcelain"], cwd=work, capture_output=True, text=True
    ).stdout
    stray = [
        ln[3:]
        for ln in tracked.splitlines()
        if ln[3:]
        and not ln[3:].startswith((".claude/", ".scenario/", "README.md", "docs/"))
    ]
    check(
        "no_stray_artifacts",
        not stray,
        "no files changed outside docs and kit state"
        if not stray
        else f"unexpected changes: {stray[:8]}",
    )

    verdict = {
        "scenario": "SC-01",
        "oracle": "sc01_docs_only",
        "pass": all(c["pass"] for c in checks),
        "checks": checks,
    }
    print(json.dumps(verdict, indent=2))
    return 0 if verdict["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
