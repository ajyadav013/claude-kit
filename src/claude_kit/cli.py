"""Command-line interface for claude-kit (``claude-kit`` · aliases ``ckit`` / ``claude-sdlc``).

A Cookiecutter-style scaffolder for a Claude Code **configuration** (no application code, no Docker):
``init`` asks ordered questions and lays down ``CLAUDE.md`` + ``.claude/`` (rules, the profile's
agents/skills, hooks, artifact templates, config) + an optional ``.mcp.json`` and a README. Lifecycle
commands — ``validate``, ``doctor``, ``diff``, ``upgrade``, ``list-options``, ``status`` — manage it.
"""

from __future__ import annotations

import json
import os
from contextlib import ExitStack
from pathlib import Path
from typing import Optional

import typer

from claude_kit import (
    __version__,
    catalog,
    pipeline,
    prompts,
    report,
    scaffold,
    upgrader,
    validator,
)
from claude_kit.models import ResolvedPlan

# Planned-but-unimplemented commands are hidden from `--help` by default so they
# can't be mistaken for working features. Set CLAUDE_KIT_EXPERIMENTAL=1 to surface
# them (still marked "[planned]" and still exit non-zero). Evaluated at import.
_EXPERIMENTAL = bool(os.environ.get("CLAUDE_KIT_EXPERIMENTAL"))

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
pipeline_app = typer.Typer(
    no_args_is_help=True,
    help="Inspect/mutate the /sdlc pipeline state files (does not run the pipeline).",
)
app.add_typer(pipeline_app, name="pipeline")


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


def _emit_report(ok: bool, messages: list[str], *, as_json: bool) -> None:
    """Print a check report as text (default) or a structured JSON object; exit code unchanged."""
    if as_json:
        typer.echo(report.Report.from_lines(ok, messages).to_json())
        if not ok:
            raise typer.Exit(1)
    else:
        _print_report(ok, messages)


def _resolve_plan(src: Path, *, config: Optional[str], defaults: bool) -> ResolvedPlan:
    """Resolve the user's selection (``--config`` / ``--defaults`` / interactive) into a plan."""
    try:
        if config is not None:
            selection = prompts.from_config(config, src)
        elif defaults:
            selection = catalog.defaults(src)
        else:
            selection = prompts.interactive(src)
        return catalog.resolve(src, selection)
    except (ValueError, FileNotFoundError) as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(2) from exc


def _print_dry_run(src: Path, target: Path, plan: ResolvedPlan) -> None:
    """Print the resolved plan + the exact files a fresh install would write. Touches nothing."""
    sel = plan.selection
    stack_str = (
        f"{sel.frontend_framework}/{sel.frontend_language} + "
        f"{sel.backend_language}/{sel.backend_framework} + {sel.database}"
    )
    _, paths = scaffold.preview_install(src, target, plan)
    typer.echo(f"\nDRY RUN — previewing install into {target} (no files written)\n")
    typer.echo(f"  profile : {sel.profile}    scope: {sel.scope}")
    typer.echo(f"  stack   : {stack_str}")
    typer.echo(f"  MCP     : {', '.join(sorted(plan.mcp_servers)) or 'none'}")
    typer.echo(
        f"  resolves to: {len(plan.agents)} agents · {len(plan.skills)} skills · "
        f"{len(plan.overlay_rules)} overlay rules · {len(plan.hooks)} hooks · "
        f"{len(plan.gates)} gates"
    )
    if plan.gates:
        typer.echo(f"  gates   : {', '.join(plan.gates)}")
    typer.echo(f"\nWould write {len(paths)} file(s):")
    for p in paths:
        typer.echo(f"  + {p}")
    if (target / ".claude").exists():
        typer.echo(
            "\nNote: this project already has .claude/ — a real run would MERGE (preserving your "
            "files) or need --force. Use `claude-kit diff` to preview an upgrade."
        )
    typer.echo("\nDRY RUN — nothing was written.")


def _dry_run_doc(src: Path, target: Path, plan: ResolvedPlan) -> dict:
    """The same plan + would-write file list as :func:`_print_dry_run`, as a JSON-able dict."""
    sel = plan.selection
    _, paths = scaffold.preview_install(src, target, plan)
    return {
        "dry_run": True,
        "target": str(target),
        "profile": sel.profile,
        "scope": sel.scope,
        "stack": {
            "frontend_framework": sel.frontend_framework,
            "frontend_language": sel.frontend_language,
            "backend_language": sel.backend_language,
            "backend_framework": sel.backend_framework,
            "database": sel.database,
        },
        "mcp": sorted(plan.mcp_servers),
        "resolves": {
            "agents": len(plan.agents),
            "skills": len(plan.skills),
            "overlay_rules": len(plan.overlay_rules),
            "hooks": len(plan.hooks),
            "gates": len(plan.gates),
        },
        "gates": list(plan.gates),
        "would_write": [str(p) for p in paths],
        "existing_claude": (target / ".claude").exists(),
    }


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
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="preview the resolved plan and the files that would be written; write nothing",
    ),
    json_out: bool = typer.Option(
        False,
        "--json",
        help="with --dry-run, emit the resolved plan as JSON instead of text",
    ),
    detect_commands: Optional[bool] = typer.Option(
        None,
        "--detect-commands/--no-detect-commands",
        help="inspect the target repo for its real package-manager commands and use them in "
        "CLAUDE.md (default: on; a no-op on an empty target). --no-detect-commands pins the "
        "generic catalog commands.",
    ),
) -> None:
    """Scaffold a Claude Code SDLC configuration into a project."""
    non_interactive = defaults or config is not None
    if json_out and not dry_run:
        typer.echo("error: --json is only supported together with --dry-run", err=True)
        raise typer.Exit(2)
    with ExitStack() as stack:
        src = scaffold.payload_dir(stack)

        # 1) Target path.
        if path is None:
            raw = "." if non_interactive else input("Target path [.]: ").strip() or "."
        else:
            raw = path
        target = Path(raw).expanduser().resolve()

        # --dry-run: resolve + preview only. Never create the target or write anything; skip the
        # existing-.claude handling and the install spine entirely.
        if dry_run:
            plan = _resolve_plan(src, config=config, defaults=defaults)
            if detect_commands is not None:
                plan.selection.detect_commands = detect_commands
            if json_out:
                typer.echo(json.dumps(_dry_run_doc(src, target, plan), indent=2))
            else:
                _print_dry_run(src, target, plan)
            return

        if not target.exists():
            if not non_interactive and not typer.confirm(
                f"Create {target}?", default=True
            ):
                typer.echo("aborted.")
                raise typer.Exit(0)
            target.mkdir(parents=True, exist_ok=True)

        # 2) Existing .claude handling: merge / overwrite / backup / abort.
        mode = "fresh"
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
        plan = _resolve_plan(src, config=config, defaults=defaults)
        if detect_commands is not None:
            plan.selection.detect_commands = detect_commands

        # 4) Install. Merge mode reconciles non-destructively (preserving the user's own files);
        # fresh / overwrite / backup all go through the destructive install spine.
        if mode == "merge":
            typer.echo(
                f"\nclaude-kit: merging into {target} (your files are preserved)"
            )
            ok, messages = upgrader.merge_install(src, target, plan, force=force)
            for line in messages:
                typer.echo(line)
            if not ok:
                raise typer.Exit(1)
        else:
            typer.echo(f"\nclaude-kit: installing into {target}")
            for line in scaffold.install_sdlc(src, target, plan, force=overwrite):
                typer.echo(line)

    typer.echo(
        "\nDone. Open the project in Claude Code and run `/sdlc <your task>` to start the pipeline."
    )


@app.command()
def validate(
    path: str = typer.Argument(".", help="target project dir (default: .)"),
    strict: bool = typer.Option(
        False,
        "--strict",
        help="deep checks: hooks→installed scripts, .mcp.json shape, snapshot + catalog integrity",
    ),
    json_out: bool = typer.Option(
        False, "--json", help="emit a machine-readable JSON report instead of text"
    ),
) -> None:
    """Structurally validate a scaffolded .claude/ configuration."""
    _emit_report(*validator.validate(path, strict=strict), as_json=json_out)


@app.command()
def doctor(
    path: str = typer.Argument(".", help="target project dir (default: .)"),
    mcp: bool = typer.Option(
        False,
        "--mcp",
        help="also check MCP servers: command on PATH, ${ENV} vars set, lockfile in sync",
    ),
    json_out: bool = typer.Option(
        False, "--json", help="emit a machine-readable JSON report instead of text"
    ),
) -> None:
    """Run strict validation plus environment/health checks with fix hints."""
    _emit_report(*validator.doctor(path, mcp=mcp), as_json=json_out)


@app.command()
def diff(
    path: str = typer.Argument(".", help="target project dir (default: .)"),
    json_out: bool = typer.Option(
        False, "--json", help="emit a machine-readable JSON report instead of text"
    ),
) -> None:
    """Preview what an upgrade would change (no writes)."""
    _emit_report(*upgrader.diff(path), as_json=json_out)


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
    json_out: bool = typer.Option(
        False, "--json", help="emit a machine-readable JSON summary instead of text"
    ),
) -> None:
    """Show what's installed and the current working memory."""
    target = Path(path).expanduser().resolve()
    dest = target / ".claude"
    installed = dest.is_dir()

    # Collect the data once, then render as text (byte-identical to before) or JSON.
    components: dict[str, Optional[int]] = {}
    selection: Optional[dict] = None
    continuity = dest / "CONTINUITY.md"
    if installed:
        for name in ("rules", "agents", "skills", "hooks"):
            d = dest / name
            components[name] = (
                sum(1 for p in d.iterdir() if p.name != ".gitkeep")
                if d.is_dir()
                else None
            )
        options = dest / "config" / "init-options.json"
        if options.is_file():
            selection = json.loads(options.read_text(encoding="utf-8")).get(
                "selection", {}
            )

    if json_out:
        typer.echo(
            json.dumps(
                {
                    "target": str(target),
                    "installed": installed,
                    "components": components,
                    "selection": selection,
                    "continuity": continuity.is_file(),
                },
                indent=2,
            )
        )
        return

    typer.echo(f"claude-kit status for {target}")
    if not installed:
        typer.echo("  not installed — run `claude-kit init` here.")
        return
    for name in ("rules", "agents", "skills", "hooks"):
        n = components[name]
        typer.echo(f"  • {name}/: {n}" if n is not None else f"  • {name}/: (missing)")
    if selection is not None:
        sel = selection
        typer.echo(
            f"  • selection: {sel.get('frontend_framework')} + "
            f"{sel.get('backend_language')}/{sel.get('backend_framework')} + "
            f"{sel.get('database')} · profile={sel.get('profile')} · mcp={sel.get('mcp') or 'none'}"
        )
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


@app.command(
    "package-org-pack",
    hidden=not _EXPERIMENTAL,
    # \[ escapes the bracket so Rich renders a literal "[planned]" (not a markup tag).
    help=r"\[planned] Package an org-pack into a reusable, versioned plugin-style directory.",
)
def package_org_pack(
    pack: str = typer.Argument(
        ..., help="org-pack id under .claude/org-packs/ (e.g. engineering-core)"
    ),
    out: Optional[str] = typer.Option(
        None, "--out", help="output directory for the packaged plugin"
    ),
) -> None:
    """(Planned) Package an org-pack into a reusable, versioned plugin-style directory."""
    typer.echo(
        "package-org-pack is planned but not yet implemented.\n"
        "When available it will bundle the selected org-pack (manifest + the skills/agents/hooks it "
        "references + settings + README + CHANGELOG + version + license + compatibility metadata) into "
        "a distributable plugin directory for an internal registry.\n"
        f"(given: pack={pack}, out={out or 'dist/org-packs/'})"
    )
    raise typer.Exit(2)  # not a successful no-op — signal "unimplemented" to scripts/CI


@app.command(
    "install-org-pack",
    hidden=not _EXPERIMENTAL,
    help=r"\[planned] Install an approved org-pack into a repo or user-level Claude config.",
)
def install_org_pack(
    source: str = typer.Argument(
        ..., help="path or registry id of an approved org-pack"
    ),
    user: bool = typer.Option(
        False, "--user", help="install into user-level ~/.claude instead of this repo"
    ),
) -> None:
    """(Planned) Install an approved org-pack into a repo or user-level Claude config."""
    typer.echo(
        "install-org-pack is planned but not yet implemented.\n"
        "When available it will verify a pack's compatibility metadata and merge its components into "
        "the target .claude/ (repo) or ~/.claude (user) config, recording the pack id + version for "
        "safe upgrades.\n"
        f"(given: source={source}, target={'user (~/.claude)' if user else 'repo (.claude)'})"
    )
    raise typer.Exit(2)  # not a successful no-op — signal "unimplemented" to scripts/CI


@research_app.command(
    "import-sources",
    hidden=not _EXPERIMENTAL,
    help=r"\[planned] Summarise explicit, license-cleared sources into original skill/agent proposals.",
)
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
    raise typer.Exit(2)  # not a successful no-op — signal "unimplemented" to scripts/CI


@pipeline_app.command("validate")
def pipeline_validate(
    path: str = typer.Argument(".", help="target project dir (default: .)"),
    json_out: bool = typer.Option(
        False, "--json", help="emit a machine-readable JSON report instead of text"
    ),
) -> None:
    """Check the pipeline snapshot's shape and gate/lane coherence (no writes)."""
    _emit_report(*pipeline.validate(path), as_json=json_out)


@pipeline_app.command("status")
def pipeline_status(
    path: str = typer.Argument(".", help="target project dir (default: .)"),
    json_out: bool = typer.Option(
        False, "--json", help="emit a machine-readable JSON report instead of text"
    ),
) -> None:
    """Print a summary of the current pipeline run (stage, lanes, gate, findings, next)."""
    _emit_report(*pipeline.status(path), as_json=json_out)


@pipeline_app.command("close-gate")
def pipeline_close_gate(
    gate: str = typer.Argument(
        ..., help="gate token to mark passed (e.g. code-review)"
    ),
    evidence: str = typer.Option(
        ..., "--evidence", help="path to the evidence artifact for this gate"
    ),
    path: str = typer.Argument(".", help="target project dir (default: .)"),
    force: bool = typer.Option(
        False,
        "--force",
        help="close the gate despite open critical/high/medium findings (requires --override-reason)",
    ),
    override_reason: Optional[str] = typer.Option(
        None,
        "--override-reason",
        help="justification recorded when --force bypasses open blocking findings",
    ),
) -> None:
    """Record a quality gate as passed, with an evidence file, in the pipeline snapshot.

    Refuses to pass a gate while critical/high/medium findings are open unless --force is given with
    an --override-reason (recorded for human review).
    """
    _print_report(
        *pipeline.close_gate(
            path, gate, evidence, force=force, override_reason=override_reason
        )
    )


@pipeline_app.command("abort")
def pipeline_abort(
    path: str = typer.Argument(".", help="target project dir (default: .)"),
) -> None:
    """Mark the current pipeline run aborted."""
    _print_report(*pipeline.abort(path))


def main() -> None:
    """Console-script entry point."""
    app()


if __name__ == "__main__":
    main()
