#!/usr/bin/env python3
"""Generate root host instructions from one canonical contributor template."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from jinja2 import Environment, StrictUndefined

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "canonical" / "contributor-guide.md.tmpl"
TARGETS = {
    "CLAUDE.md": {"instruction_filename": "CLAUDE.md", "host_name": "Claude Code"},
    "AGENTS.md": {"instruction_filename": "AGENTS.md", "host_name": "Codex"},
}


def generated_guides(root: Path = ROOT) -> dict[Path, str]:
    """Return every deterministic contributor guide keyed by destination."""

    source = root / SOURCE.relative_to(ROOT)
    template = Environment(
        autoescape=False,
        keep_trailing_newline=True,
        undefined=StrictUndefined,
    ).from_string(source.read_text(encoding="utf-8"))
    return {
        root / relative: template.render(**context)
        for relative, context in TARGETS.items()
    }


def write(root: Path = ROOT) -> None:
    """Write both generated guides."""

    for destination, content in generated_guides(root).items():
        destination.write_text(content, encoding="utf-8")


def check(root: Path = ROOT) -> list[str]:
    """Return drift errors without mutating the checkout."""

    errors: list[str] = []
    for destination, expected in generated_guides(root).items():
        if not destination.is_file():
            errors.append(f"missing generated contributor guide: {destination.name}")
        elif destination.read_text(encoding="utf-8") != expected:
            errors.append(
                f"generated contributor guide drift: {destination.name} "
                "(run scripts/gen_contributor_guides.py)"
            )
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail instead of writing when output drifts",
    )
    args = parser.parse_args()
    if args.check:
        errors = check()
        if errors:
            print("\n".join(errors), file=sys.stderr)
            return 1
        print("contributor guides are current")
        return 0
    write()
    print("generated CLAUDE.md and AGENTS.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
