"""Command-line interface for claude-kit (``claude-kit`` · aliases ``ckit`` / ``claude-sdlc``).

A Cookiecutter-style scaffolder for a Claude Code **configuration** (no application code, no Docker):
``init`` asks ordered questions and lays down ``CLAUDE.md`` + ``.claude/`` (rules, the profile's
agents/skills, hooks, artifact templates, config) + an optional ``.mcp.json`` and a README. Lifecycle
commands — ``validate``, ``doctor``, ``diff``, ``upgrade``, ``list-options``, ``status`` — manage it.
"""

from __future__ import annotations

from contextlib import ExitStack
from pathlib import Path
from typing import Optional

import typer

from claude_kit import __version__, catalog, prompts, scaffold, upgrader, validator

BANNER = r"""
  ___ _      _   _ ___  ___   _  _____ _____
 / __| |    /_\ | | |   \| __| | |/ /_ _|_   _|
| (__| |__ / _ \| |_| | |) | _|  | ' < | |  | |
 \___|____/_/ \_\\___/|___/|___| |_|\_\___| |_|   autonomous SDLC config for Claude Code
"""

app = typer.Typer(
    add_completion=False,
    no_args_is_help=False,
    help="Scaffold and manage a Claude Code autonomous-SDLC configuration.",
)
research_app = typer.Typer(
    no_args_is_help=True, help="Research helpers (license-respecting)."
)
app.add_typer(research_app, name="research")


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"claude-kit {__version__}")
        raise typer.Exit()


@app.callback(invoke_without_command=True)
def _root(
    ctx: typer.Context,
    version: bool = typer.Option(
        False,
        "-V",
        "--version",
        callback=_version_callback,
        is_eager=True,
        help="print the version",
    ),
) -> None:
    """Show the banner + help when invoked with no subcommand."""
    if ctx.invoked_subcommand is None:
        typer.echo(BANNER)
        typer.echo(ctx.get_help())


def _print_report(ok: bool, messages: list[str]) -> None:
    """Print a check report and exit non-zero on failure."""
    for line in messages:
        typer.echo(line)
    if not ok:
        raise typer.Exit(1)


@app.command()
def init(
    path: Optional[str] = typer.Argument(
        None, help="target project dir (prompted if omitted; default: current dir)"
    ),
    defaults: bool = typer.Option(
        False, "--defaults", help="non-interactive; use catalog defaults"
    ),
    config: Optional[str] = typer.Option(
        None, "--config", help="non-interactive; read the selection from a YAML file"
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="overwrite existing CLAUDE.md / settings.json / .mcp.json",
    ),
) -> None:
    """Scaffold a Claude Code SDLC configuration into a project."""
    non_interactive = defaults or config is not None
    with ExitStack() as stack:
        src = scaffold.payload_dir(stack)

        # 1) Target path.
        if path is None:
            raw = "." if non_interactive else input("Target path [.]: ").strip() or "."
        else:
            raw = path
        target = Path(raw).expanduser().resolve()
        if not target.exists():
            if not non_interactive and not typer.confirm(
                f"Create {target}?", default=True
            ):
                typer.echo("aborted.")
                raise typer.Exit(0)
            target.mkdir(parents=True, exist_ok=True)

        # 2) Existing .claude handling: merge / overwrite / backup / abort.
        overwrite = force
        if (target / ".claude").exists():
            if force:
                mode = "overwrite"
            elif non_interactive:
                mode = "merge"
            else:
                mode = (
                    typer.prompt(
                        ".claude already exists — [merge/overwrite/backup/abort]",
                        default="merge",
                    )
                    .strip()
                    .lower()
                )
            if mode == "abort":
                typer.echo("aborted — nothing changed.")
                raise typer.Exit(0)
            if mode == "overwrite":
                overwrite = True
            if mode == "backup":
                n = 1
                while (target / f".claude.bak-{n}").exists():
                    n += 1
                (target / ".claude").rename(target / f".claude.bak-{n}")
                typer.echo(f"  • backed up existing .claude/ -> .claude.bak-{n}")

        # 3) Resolve the selection.
        try:
            if config is not None:
                selection = prompts.from_config(config, src)
            elif defaults:
                selection = catalog.defaults(src)
            else:
                selection = prompts.interactive(src)
            plan = catalog.resolve(src, selection)
        except (ValueError, FileNotFoundError) as exc:
            typer.echo(f"error: {exc}", err=True)
            raise typer.Exit(2) from exc

        # 4) Install.
        typer.echo(f"\nclaude-kit: installing into {target}")
        for line in scaffold.install_sdlc(src, target, plan, force=overwrite):
            typer.echo(line)

    typer.echo(
        "\nDone. Open the project in Claude Code and run `/sdlc <your task>` to start the pipeline."
    )


@app.command()
def validate(
    path: str = typer.Argument(".", help="target project dir (default: .)"),
) -> None:
    """Structurally validate a scaffolded .claude/ configuration."""
    _print_report(*validator.validate(path))


@app.command()
def doctor(
    path: str = typer.Argument(".", help="target project dir (default: .)"),
) -> None:
    """Run validation plus environment/health checks with fix hints."""
    _print_report(*validator.doctor(path))


@app.command()
def diff(
    path: str = typer.Argument(".", help="target project dir (default: .)"),
) -> None:
    """Preview what an upgrade would change (no writes)."""
    _print_report(*upgrader.diff(path))


@app.command()
def upgrade(
    path: str = typer.Argument(".", help="target project dir (default: .)"),
    force: bool = typer.Option(
        False, "--force", help="overwrite user-modified kit files"
    ),
) -> None:
    """Refresh kit-owned files, backing up user-modified ones."""
    _print_report(*upgrader.upgrade(path, force=force))


@app.command("list-options")
def list_options() -> None:
    """List the available frontend/backend/database/profile/MCP options from the catalog."""
    with ExitStack() as stack:
        src = scaffold.payload_dir(stack)
        opts = catalog.list_options(src)

    def _badge(entry: dict) -> str:
        return "" if entry.get("status", "live") == "live" else "  (coming soon)"

    typer.echo("\nFrontend frameworks:")
    for fe in opts["frontend"]:
        langs = ", ".join(fe.get("languages", [])) or "—"
        typer.echo(f"  • {fe['id']}: {fe['label']}{_badge(fe)}  [languages: {langs}]")
    typer.echo("\nBackend languages & frameworks:")
    for be in opts["backend"]:
        typer.echo(f"  • {be['id']}: {be['label']}{_badge(be)}")
        for fw in be["frameworks"]:
            typer.echo(f"      - {fw['id']}: {fw['label']}{_badge(fw)}")
    typer.echo("\nDatabases:")
    for db in opts["database"]:
        typer.echo(f"  • {db['id']}: {db['label']}")
    typer.echo("\nSDLC profiles:")
    for pr in opts["profiles"]:
        typer.echo(f"  • {pr['id']}: {pr['label']}")
    typer.echo("\nMCP integrations (optional):")
    for mc in opts["mcp"]:
        typer.echo(f"  • {mc['id']}: {mc['label']}")


@app.command()
def status(
    path: str = typer.Argument(".", help="target project dir (default: .)"),
) -> None:
    """Show what's installed and the current working memory."""
    target = Path(path).expanduser().resolve()
    dest = target / ".claude"
    typer.echo(f"claude-kit status for {target}")
    if not dest.is_dir():
        typer.echo("  not installed — run `claude-kit init` here.")
        return
    for name in ("rules", "agents", "skills", "hooks"):
        d = dest / name
        if d.is_dir():
            n = sum(1 for p in d.iterdir() if p.name != ".gitkeep")
            typer.echo(f"  • {name}/: {n}")
        else:
            typer.echo(f"  • {name}/: (missing)")
    options = dest / "config" / "init-options.json"
    if options.is_file():
        import json

        data = json.loads(options.read_text(encoding="utf-8"))
        sel = data.get("selection", {})
        typer.echo(
            f"  • selection: {sel.get('frontend_framework')} + "
            f"{sel.get('backend_language')}/{sel.get('backend_framework')} + "
            f"{sel.get('database')} · profile={sel.get('profile')} · mcp={sel.get('mcp') or 'none'}"
        )
    continuity = dest / "CONTINUITY.md"
    if continuity.is_file():
        typer.echo("\n  working memory (.claude/CONTINUITY.md):")
        for line in continuity.read_text(
            encoding="utf-8", errors="replace"
        ).splitlines()[:30]:
            typer.echo(f"    {line}")
    else:
        typer.echo("\n  no CONTINUITY.md yet (no pipeline run recorded).")


@app.command()
def version() -> None:
    """Print the version."""
    typer.echo(f"claude-kit {__version__}")


@research_app.command("import-sources")
def research_import_sources(
    sources: str = typer.Argument(
        ..., help="YAML file of explicit, license-cleared sources"
    ),
) -> None:
    """(Planned) Summarise explicit, license-cleared sources into original skill/agent proposals."""
    typer.echo(
        "research import-sources is planned but not yet implemented.\n"
        "When available it will: read explicit source URLs/files from the given YAML, record each "
        "source's name/URL/license/author/date, summarise ideas into ORIGINAL skill/agent proposals "
        "(never copying proprietary text), and require human approval before adding anything.\n"
        f"(given: {sources})"
    )


def main() -> None:
    """Console-script entry point."""
    app()


if __name__ == "__main__":
    main()
