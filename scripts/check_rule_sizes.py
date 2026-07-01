#!/usr/bin/env python3
"""Fail if any shipped rule file is close to Claude Code's memory/rule-file size limit.

Claude Code warns (and can load a rule only partially) when a memory/rule file exceeds
**40,000 characters**. Every rule this kit ships is copied verbatim into a user project's
``.claude/rules/`` and loaded on demand, so an over-limit rule silently degrades in every install.

This is an offline, deterministic CI gate. It scans the rule files the kit distributes — the
stack-agnostic core (``rules/``), the per-stack overlays (``templates/stacks/**/rules/``), and the
org overlays (``templates/org/rules/``) — and fails if any is at or above ``THRESHOLD`` characters.
The threshold sits below the hard limit to keep headroom for small edits before a file must be split.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Claude Code's hard limit is 40,000 characters; keep 2k of headroom so a small edit does not
# immediately push a rule over the line before someone notices it needs splitting.
HARD_LIMIT = 40_000
THRESHOLD = 38_000

# Glob patterns (relative to ROOT) for every rule file the kit ships into a user's .claude/rules/.
RULE_GLOBS = (
    "rules/*.md",
    "templates/stacks/**/rules/*.md",
    "templates/org/rules/*.md",
)


def rule_files(root: Path | None = None) -> list[Path]:
    """Return every shipped rule file, de-duplicated and sorted by path."""
    base = root or ROOT
    found: set[Path] = set()
    for pattern in RULE_GLOBS:
        found.update(base.glob(pattern))
    return sorted(found)


def oversized(
    root: Path | None = None, threshold: int = THRESHOLD
) -> list[tuple[Path, int]]:
    """Return ``(path, char_count)`` for each rule file at or above ``threshold`` characters."""
    base = root or ROOT
    out: list[tuple[Path, int]] = []
    for path in rule_files(base):
        count = len(path.read_text(encoding="utf-8"))
        if count >= threshold:
            out.append((path.relative_to(base), count))
    return out


def main() -> int:
    files = rule_files()
    bad = oversized()
    if bad:
        print(
            f"FAIL  rule file(s) at/over {THRESHOLD:,} chars "
            f"(Claude Code's limit is {HARD_LIMIT:,}); split them by concern:"
        )
        for rel, count in bad:
            print(f"  - {rel} -> {count:,} chars")
        return 1
    print(
        f"OK    all {len(files)} shipped rule file(s) are under {THRESHOLD:,} chars "
        f"(limit {HARD_LIMIT:,})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
