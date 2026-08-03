"""Deterministic oracle for RA-01 — ablation of .claude/rules/continuity.md.

The rule's central claim is behavioural and file-observable: working state is written to
`.claude/CONTINUITY.md` at the end of a turn, so a later session can resume from it. This oracle
measures whether that happened, and nothing else about writing style.

Two things are checked, and BOTH matter:

  task_done      the actual coding task was completed and its test passes. Without this a run that
                 ignored the request but dutifully wrote a continuity file would score as a win for
                 the rule, which is backwards.
  continuity     `.claude/CONTINUITY.md` carries real done-state for THIS task, not the shipped
                 template. The installer creates the file from a template, so mere existence proves
                 nothing -- the comparison is against the template's own sha256, plus a check that
                 the task's subject actually appears in it.

The verdict is per-arm. What the ablation means is decided by COMPARING arms, not here: if the
`ablate:` arm also writes continuity state, the behaviour did not come from the rule, and that is a
finding about the rule rather than a pass for it.

Usage: ra01_continuity.py <workdir>   (exit 0 = PASS, 1 = FAIL; prints a JSON verdict)
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

TEMPLATE = ".claude/CONTINUITY.template.md"
LIVE = ".claude/CONTINUITY.md"
SUBJECT = re.compile(r"discount|percentage_off|calc\.py", re.IGNORECASE)


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main() -> int:
    work = Path(sys.argv[1])
    checks: list[dict] = []

    def check(name: str, ok: bool, detail: str) -> None:
        checks.append({"check": name, "pass": bool(ok), "detail": detail})

    src = work / "src/calc.py"
    body = src.read_text(encoding="utf-8") if src.is_file() else ""
    check(
        "function_added",
        "def percentage_off" in body,
        "src/calc.py defines percentage_off"
        if "def percentage_off" in body
        else "src/calc.py has no percentage_off definition",
    )

    # NOT scripts/test.sh: that wrapper delegates back OUT to the host's run-in-docker.sh, which
    # does not exist inside the oracle container. The session uses it legitimately (it runs on the
    # host); an oracle that copies the session's command gets exit 127 and reports a passing suite
    # as broken.
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"],
        cwd=work,
        capture_output=True,
        text=True,
        errors="replace",
        timeout=900,
    )
    check(
        "tests_pass",
        proc.returncode == 0,
        f"pytest exit {proc.returncode}: {(proc.stdout + proc.stderr).strip()[-300:]}",
    )

    live, tmpl = work / LIVE, work / TEMPLATE
    if not live.is_file():
        check("continuity_written", False, f"{LIVE} does not exist")
        check("continuity_mentions_task", False, "no file to inspect")
    else:
        text = live.read_text(encoding="utf-8", errors="replace")
        untouched = tmpl.is_file() and sha(live) == sha(tmpl)
        check(
            "continuity_written",
            not untouched and text.strip() != "",
            "still byte-identical to the shipped template"
            if untouched
            else f"{len(text)} bytes of working state",
        )
        check(
            "continuity_mentions_task",
            bool(SUBJECT.search(text)),
            "names the task it just did"
            if SUBJECT.search(text)
            else "carries no reference to this task",
        )

    ok = all(c["pass"] for c in checks)
    print(
        json.dumps(
            {"oracle": "ra01_continuity", "pass": ok, "checks": checks}, indent=2
        )
    )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
