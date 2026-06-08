"""Command-line interface for claude-kit.

Provides ``claude-kit`` (alias ``ckit``) with subcommands to scaffold and inspect the kit:
``init``, ``upgrade``, ``status``, ``list``, and ``version``. Stdlib-only — no third-party deps.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from claude_kit import __version__, scaffold

BANNER = r"""
  ___ _      _   _ ___  ___   _  _____ _____
 / __| |    /_\ | | |   \| __| | |/ /_ _|_   _|
| (__| |__ / _ \| |_| | |) | _|  | ' < | |  | |
 \___|____/_/ \_\\___/|___/|___| |_|\_\___| |_|   autonomous SDLC for Claude Code
"""


def _cmd_init(args: argparse.Namespace) -> int:
    """Handle ``claude-kit init``."""
    for line in scaffold.init(
        args.path, force=args.force, minimal=args.minimal, no_hooks=args.no_hooks
    ):
        print(line)
    print(
        "\nNext: open the project in Claude Code, then try `/claude-kit:sdlc <your task>`."
    )
    return 0


def _cmd_upgrade(args: argparse.Namespace) -> int:
    """Handle ``claude-kit upgrade``."""
    for line in scaffold.upgrade(args.path):
        print(line)
    return 0


def _cmd_list(_: argparse.Namespace) -> int:
    """Handle ``claude-kit list``."""
    inv = scaffold.inventory()
    for key in ("agents", "rules", "skills"):
        items = inv[key]
        print(f"\n{key} ({len(items)}):")
        for name in items:
            print(f"  - {name}")
    return 0


def _cmd_status(args: argparse.Namespace) -> int:
    """Handle ``claude-kit status``."""
    target = Path(args.path).expanduser().resolve()
    dest = target / ".claude"
    print(f"claude-kit status for {target}")
    if not dest.is_dir():
        print("  not installed — run `claude-kit init` here.")
        return 0
    for name in ("rules", "agents", "skills", "hooks"):
        d = dest / name
        if d.is_dir():
            n = sum(1 for p in d.iterdir() if p.name != ".gitkeep")
            print(f"  • {name}/: {n}")
        else:
            print(f"  • {name}/: (missing)")
    continuity = dest / "CONTINUITY.md"
    if continuity.is_file():
        print("\n  working memory (.claude/CONTINUITY.md):")
        text = continuity.read_text(encoding="utf-8", errors="replace")
        for line in text.splitlines()[:40]:
            print(f"    {line}")
    else:
        print("\n  no CONTINUITY.md yet (no pipeline run recorded).")
    return 0


def _cmd_version(_: argparse.Namespace) -> int:
    """Handle ``claude-kit version``."""
    print(f"claude-kit {__version__}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Construct the argument parser with all subcommands.

    Returns:
        The configured ``ArgumentParser``.
    """
    parser = argparse.ArgumentParser(
        prog="claude-kit",
        description="Scaffold and manage the claude-kit autonomous SDLC for Claude Code.",
    )
    parser.add_argument(
        "-V", "--version", action="version", version=f"claude-kit {__version__}"
    )
    sub = parser.add_subparsers(dest="command", metavar="<command>")

    p_init = sub.add_parser("init", help="scaffold claude-kit into a project")
    p_init.add_argument(
        "path", nargs="?", default=".", help="target project dir (default: .)"
    )
    p_init.add_argument(
        "--force",
        action="store_true",
        help="overwrite existing CLAUDE.md / settings.json",
    )
    p_init.add_argument(
        "--minimal", action="store_true", help="only CLAUDE.md + rules/"
    )
    p_init.add_argument(
        "--no-hooks", action="store_true", help="skip hook scripts and settings.json"
    )
    p_init.set_defaults(func=_cmd_init)

    p_up = sub.add_parser(
        "upgrade",
        help="refresh rules/agents/skills/hooks (keeps your CLAUDE.md & settings)",
    )
    p_up.add_argument(
        "path", nargs="?", default=".", help="target project dir (default: .)"
    )
    p_up.set_defaults(func=_cmd_upgrade)

    p_status = sub.add_parser(
        "status", help="show what's installed and the working memory"
    )
    p_status.add_argument(
        "path", nargs="?", default=".", help="target project dir (default: .)"
    )
    p_status.set_defaults(func=_cmd_status)

    p_list = sub.add_parser("list", help="list bundled agents, rules, and skills")
    p_list.set_defaults(func=_cmd_list)

    p_ver = sub.add_parser("version", help="print the version")
    p_ver.set_defaults(func=_cmd_version)

    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entry point.

    Args:
        argv: Optional argument list (defaults to ``sys.argv[1:]``).

    Returns:
        Process exit code.
    """
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        print(BANNER)
        parser.print_help()
        return 0
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
