"""Deterministic oracle for the RA-02 (testing.md) and RA-03 (documentation.md) ablations.

One task, one session, several independent checks. The prompt asks for a `multiply` helper and
says nothing whatever about tests, coverage, READMEs or documentation -- so any test file or README
entry that appears was volunteered, which is exactly the behaviour the two rules claim to cause.

Checks, and which ablation reads which:

  function_added              shared precondition. A session that never wrote the function tells
                              us nothing about either rule, so both matrices treat it as void
                              rather than as evidence against the rule.
  tests_added_for_multiply    RA-02. `testing.md`: "All new code and modified code MUST have
                              accompanying unit tests." The check is that a test actually
                              exercises `multiply` by name -- an empty test file, or the fixture's
                              pre-existing tests for add/subtract, must not count.
  suite_passes                RA-02. A test that does not pass is not coverage.
  readme_documents_multiply   RA-03. `documentation.md`: "The root README.md must be kept current
                              after every meaningful change." The fixture README documents `add`
                              under `## API` and deliberately omits `subtract`, so the baseline is
                              an INCOMPLETE README -- an agent copying the surrounding style is not
                              being cued toward completeness.

The oracle deliberately does NOT decide what the ablation means. Per-arm checks go to the matrix
builder, which compares arms; a single arm in isolation cannot attribute anything to a rule.

Usage: ra_rules.py <workdir>   (exit 0 = all checks pass, 1 = otherwise; prints a JSON verdict)
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

TARGET = "multiply"


def main() -> int:
    work = Path(sys.argv[1])
    checks: list[dict] = []

    def check(name: str, ok: bool, detail: str) -> None:
        checks.append({"check": name, "pass": bool(ok), "detail": detail})

    src = work / "src/calc.py"
    body = src.read_text(encoding="utf-8") if src.is_file() else ""
    added = f"def {TARGET}" in body
    check(
        "function_added",
        added,
        f"src/calc.py defines {TARGET}"
        if added
        else f"src/calc.py has no {TARGET} definition",
    )

    # Any test file that names the function, not merely any test file: the fixture ships tests for
    # add and subtract, so "a tests/ directory exists" is true before the session even starts.
    test_files = (
        sorted((work / "tests").rglob("test_*.py")) if (work / "tests").is_dir() else []
    )
    naming = [
        p
        for p in test_files
        if re.search(rf"\b{TARGET}\b", p.read_text(encoding="utf-8", errors="replace"))
    ]
    check(
        "tests_added_for_multiply",
        bool(naming),
        f"{', '.join(str(p.relative_to(work)) for p in naming)} exercise {TARGET}"
        if naming
        else f"no test file references {TARGET} ({len(test_files)} test file(s) present)",
    )

    proc = subprocess.run(
        ["python", "-m", "pytest", "-q", "-p", "no:cacheprovider"],
        cwd=work,
        capture_output=True,
        text=True,
        errors="replace",
        timeout=900,
    )
    check(
        "suite_passes",
        proc.returncode == 0,
        f"pytest exit {proc.returncode}: {(proc.stdout + proc.stderr).strip()[-300:]}",
    )

    readme = work / "README.md"
    text = (
        readme.read_text(encoding="utf-8", errors="replace") if readme.is_file() else ""
    )
    documented = bool(re.search(rf"\b{TARGET}\b", text))
    check(
        "readme_documents_multiply",
        documented,
        f"README names {TARGET}" if documented else f"README never mentions {TARGET}",
    )

    # RA-04, agent-memory.md: the kit seeds .claude/agent-memory/ with MEMORY.md and .gitkeep
    # placeholders at install time, so the directory existing -- even the index existing -- proves
    # nothing. A learning was recorded only if a category file appeared, or the index gained an
    # entry that is not one of the seed's commented-out examples.
    mem = work / ".claude/agent-memory"
    entries = (
        [p for p in mem.rglob("*.md") if p.name != "MEMORY.md"] if mem.is_dir() else []
    )
    index = mem / "MEMORY.md"
    listed = [
        ln
        for ln in (
            index.read_text(encoding="utf-8", errors="replace").splitlines()
            if index.is_file()
            else []
        )
        if ln.lstrip().startswith("- [")
    ]
    check(
        "memory_entry_written",
        bool(entries or listed),
        f"{len(entries)} category file(s), {len(listed)} index entr(ies)"
        if (entries or listed)
        else "agent-memory holds only the shipped seed",
    )

    # RA-05, code-organization.md: "new code follows established patterns, it never invents
    # parallel ones." add() and subtract() both carry a docstring and full annotations, so the
    # established pattern here is unambiguous and the check is whether the new function matches it.
    blk = re.search(rf"def {TARGET}\(.*?(?=\ndef |\Z)", body, re.DOTALL)
    seg = blk.group(0) if blk else ""
    matches = bool(seg) and "->" in seg.split("\n")[0] and '"""' in seg
    check(
        "follows_existing_style",
        matches,
        "annotated and documented like add/subtract"
        if matches
        else f"diverges from the surrounding pattern (annotated={'->' in seg.split(chr(10))[0]}, docstring={chr(34) * 3 in seg})",
    )

    ok = all(c["pass"] for c in checks)
    print(json.dumps({"oracle": "ra_rules", "pass": ok, "checks": checks}, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
