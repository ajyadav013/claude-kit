#!/usr/bin/env python3
"""Warn when prose references a ``.claude/{rules,skills,agents}/...`` path that nothing ships.

The kit's rules/skills/agents cross-link each other by their canonical installed paths (golden
rule #2). A rename or removal can silently strand those references — the prose keeps pointing at a
file that no longer lands in user projects. This gardener extracts every such reference from the
shipped prose (payload + repo docs) and checks a matching file exists in the core payload, a stack
overlay, or the org overlay.

Warn-only by default (exit 0), mirroring ``check_skill_descriptions.py``: a reference can be a
deliberate *example* of a user-created file rather than a kit component, so a human judges the
report. Pass ``--strict`` to exit 1 on offenders once the report is clean.
"""

from __future__ import annotations

import argparse
import glob
import re
import sys
from pathlib import Path

#: Prose surfaces to scan: the payload that lands in user projects, plus repo-level docs.
SCAN_GLOBS = (
    "rules/*.md",
    "agents/*.md",
    "skills/**/*.md",
    "commands/*.md",
    "templates/**/*.md",
    "templates/**/*.md.tmpl",
    "docs/*.md",
    "README.md",
)

#: Reference patterns → the glob sets a match must resolve against (core ∪ stack ∪ org).
REF_KINDS: tuple[tuple[str, re.Pattern[str], tuple[str, ...]], ...] = (
    (
        "rule",
        re.compile(r"\.claude/rules/([a-z0-9_-]+\.md)"),
        # ``**`` because backend stack dirs nest three levels (<kind>/<lang>/<framework>).
        (
            "rules/{name}",
            "templates/stacks/**/rules/{name}",
            "templates/org/rules/{name}",
        ),
    ),
    (
        "skill",
        re.compile(r"\.claude/skills/([a-z0-9_-]+)"),
        # The third target covers ``skills/_references/`` — the shared, non-auto-loaded
        # reference home (loose .md files, deliberately no SKILL.md).
        (
            "skills/{name}/SKILL.md",
            "templates/org/skills/{name}/SKILL.md",
            "skills/{name}/*.md",
        ),
    ),
    (
        "agent",
        re.compile(r"\.claude/agents/([a-z0-9_-]+)\.md"),
        (
            "agents/{name}.md",
            "templates/stacks/**/agents/{name}.md",
            "templates/org/agents/{name}.md",
        ),
    ),
)

#: Known-legitimate references to files the kit deliberately does NOT ship — illustrative examples
#: of *user-created* artifacts. Add here only with a comment saying where and why.
ALLOWLIST = {
    # consolidate-learnings §7 report example: a project-local skill the Promote step would create.
    "skill:deploy-debugging",
}


def find_offenders(root: Path) -> list[tuple[str, str, str]]:
    """Return ``(source-file, kind, reference)`` for every dangling cross-reference."""
    offenders: list[tuple[str, str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for pattern in SCAN_GLOBS:
        for path in sorted(glob.glob(str(root / pattern), recursive=True)):
            text = Path(path).read_text(encoding="utf-8")
            rel = str(Path(path).relative_to(root))
            for kind, rx, targets in REF_KINDS:
                for name in rx.findall(text):
                    key = (rel, kind, name)
                    if key in seen or f"{kind}:{name}" in ALLOWLIST:
                        continue
                    seen.add(key)
                    if not any(
                        glob.glob(str(root / t.format(name=name)), recursive=True)
                        for t in targets
                    ):
                        offenders.append(key)
    return offenders


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--strict",
        action="store_true",
        help="exit 1 if any dangling cross-reference is found",
    )
    args = ap.parse_args()

    root = Path(__file__).resolve().parent.parent
    offenders = find_offenders(root)

    if offenders:
        print(f"{len(offenders)} dangling cross-reference(s) in prose:")
        for rel, kind, name in offenders:
            print(f"  - {rel}: {kind} {name!r} does not exist in core/stack/org")
    else:
        print(
            "all .claude/{rules,skills,agents} references in prose resolve to shipped files"
        )

    return 1 if (offenders and args.strict) else 0


if __name__ == "__main__":
    sys.exit(main())
