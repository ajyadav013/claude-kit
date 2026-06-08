"""Command-line interface for claude-kit.

Provides ``claude-kit`` (alias ``ckit``) with subcommands to generate and manage the kit:
``new`` (generate a project), ``init``, ``upgrade``, ``status``, ``list``, and ``version``.
Stdlib-only — no third-party deps.
"""

from __future__ import annotations

import argparse
import sys
from contextlib import ExitStack
from pathlib import Path

from claude_kit import __version__, generate, scaffold

BANNER = r"""
  ___ _      _   _ ___  ___   _  _____ _____
 / __| |    /_\ | | |   \| __| | |/ /_ _|_   _|
| (__| |__ / _ \| |_| | |) | _|  | ' < | |  | |
 \___|____/_/ \_\\___/|___/|___| |_|\_\___| |_|   autonomous SDLC for Claude Code
"""


def _prompt(label: str, default: str) -> str:
    """Prompt for a value with a default, tolerant of non-interactive input."""
    try:
        resp = input(f"{label} [{default}]: ").strip()
    except EOFError:
        return default
    return resp or default


def _choose_stack(
    stacks: list[dict], kind: str, flag_value: str | None, no_input: bool
) -> str:
    """Resolve a stack id from a flag, a single registered option, or an interactive menu.

    Args:
        stacks: Registered stacks of this kind (each a ``stack.json`` mapping).
        kind: ``"backend"`` or ``"frontend"`` (for messages).
        flag_value: An explicit ``--backend``/``--frontend`` value, or ``None``.
        no_input: Skip prompting and take the first option when not flag-specified.

    Returns:
        The chosen stack id.

    Raises:
        SystemExit: If ``flag_value`` names a stack that is not registered.
    """
    ids = [s["id"] for s in stacks]
    if flag_value:
        if flag_value not in ids:
            raise SystemExit(
                f"unknown {kind} stack {flag_value!r} (choices: {', '.join(ids)})"
            )
        return flag_value
    if len(stacks) == 1 or no_input:
        return ids[0]
    print(f"\nAvailable {kind} stacks:")
    for i, s in enumerate(stacks, 1):
        print(f"  {i}) {s.get('label', s['id'])}")
    while True:
        resp = input(f"Choose {kind} [1]: ").strip() or "1"
        if resp.isdigit() and 1 <= int(resp) <= len(stacks):
            return ids[int(resp) - 1]
        print(f"  enter a number 1-{len(stacks)}")


def _cmd_new(args: argparse.Namespace) -> int:
    """Handle ``claude-kit new`` — generate a project from the stack registry."""
    with ExitStack() as stack:
        src = scaffold.payload_dir(stack)
        backends = generate.list_stacks(src, "backend")
        frontends = generate.list_stacks(src, "frontend")
        if not backends or not frontends:
            print("error: no stacks found in the claude-kit payload.", file=sys.stderr)
            return 1

        # Resolve the target directory and the human project name.
        if args.here:
            target = Path(args.path or ".").expanduser().resolve()
            name_default = target.name
        elif args.path:
            target = Path(args.path).expanduser().resolve()
            name_default = target.name
        else:
            name = "my-app" if args.no_input else _prompt("Project name", "my-app")
            target = Path.cwd() / generate.slugify(name)
            name_default = name

        project_name = args.name or (
            name_default if args.no_input else _prompt("Project name", name_default)
        )
        backend_id = _choose_stack(backends, "backend", args.backend, args.no_input)
        frontend_id = _choose_stack(frontends, "frontend", args.frontend, args.no_input)

        for line in generate.generate(
            src,
            target,
            project_name=project_name,
            backend_id=backend_id,
            frontend_id=frontend_id,
            db=args.db,
            force=args.force,
            here=args.here,
        ):
            print(line)

    print("\nNext:")
    if not args.here:
        print(f"  cd {target.name}")
    print(
        "  docker compose up --build        # zero local installs — or `make dev` for native"
    )
    print("  open the project in Claude Code, then: /claude-kit:sdlc <your first task>")
    return 0


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

    p_new = sub.add_parser(
        "new",
        help="generate a new project (React + FastAPI) with the SDLC config baked in",
    )
    p_new.add_argument(
        "path",
        nargs="?",
        default=None,
        help="target directory / project name (prompted if omitted)",
    )
    p_new.add_argument("--name", help="human project name (default: target dir name)")
    p_new.add_argument("--backend", help="backend stack id (e.g. python-fastapi)")
    p_new.add_argument("--frontend", help="frontend stack id (e.g. react)")
    p_new.add_argument("--db", default="postgres", help="database (default: postgres)")
    p_new.add_argument(
        "--no-input", action="store_true", help="accept defaults; never prompt"
    )
    p_new.add_argument(
        "--here", action="store_true", help="generate into the current directory"
    )
    p_new.add_argument(
        "--force", action="store_true", help="generate into a non-empty directory"
    )
    p_new.set_defaults(func=_cmd_new)

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
