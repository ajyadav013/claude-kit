#!/usr/bin/env python3
"""Warn when a skill/agent ``description`` exceeds the Claude Code ``/skills`` picker preview cap.

The picker truncates each description's preview at ~250 chars, so anything longer hides its trailing
trigger keywords from the listing. This is a *quality* check, not a correctness gate: by default it
prints offenders and exits 0 (warn-only). Pass ``--strict`` to make it fail (exit 1) — intended to be
flipped on in a future release once every description is within the cap.

Separate from the 1024-char *hard* cap (a Claude Code load limit) enforced elsewhere.
"""

from __future__ import annotations

import argparse
import glob
import re
import sys

PICKER_CAP = 250


def _frontmatter(text: str) -> str | None:
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 3)
    return text[3:end] if end != -1 else None


def description_length(path: str) -> int | None:
    """Return the rendered length of a file's frontmatter ``description`` (None if absent)."""
    block = _frontmatter(open(path, encoding="utf-8").read())
    if block is None:
        return None
    m = re.search(r"(?m)^description:[ \t]*(.*)$", block)
    if not m:
        return None
    val = m.group(1).strip()
    if val in (">", "|", ">-", "|-", ">+", "|+"):
        # folded/literal block scalar — gather the indented continuation lines
        buf = []
        for line in block[m.end() :].splitlines():
            if line.strip() == "" or line.startswith((" ", "\t")):
                buf.append(line.strip())
            else:
                break
        val = " ".join(x for x in buf if x)
    else:
        val = val.strip("\"'")
    return len(val)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--max", type=int, default=PICKER_CAP)
    ap.add_argument(
        "--strict",
        action="store_true",
        help="exit 1 if any description exceeds the cap",
    )
    args = ap.parse_args()

    offenders: list[tuple[str, int]] = []
    for pattern in ("skills/*/SKILL.md", "agents/*.md"):
        for path in sorted(glob.glob(pattern)):
            n = description_length(path)
            if n is not None and n > args.max:
                offenders.append((path, n))

    if offenders:
        print(
            f"{len(offenders)} description(s) exceed the {args.max}-char picker preview cap:"
        )
        for path, n in offenders:
            print(f"  - {path}: {n} chars")
    else:
        print(f"all skill/agent descriptions are within the {args.max}-char picker cap")

    return 1 if (offenders and args.strict) else 0


if __name__ == "__main__":
    sys.exit(main())
