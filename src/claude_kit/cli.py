"""Command-line interface for ckit (legacy aliases: ``claude-kit`` / ``claude-sdlc``).

The installer resolves one evidence-gated SDLC plan and projects it into native Claude Code, Codex,
or dual-host configuration. Lifecycle commands manage the shared state and provider surfaces.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
import webbrowser
from contextlib import ExitStack
from pathlib import Path
from typing import Any, Optional

import typer

from claude_kit import (
    __version__,
    board_html,
    catalog,
    hooks,
    pipeline,
    prompts,
    report,
    scaffold,
    telemetry,
    upgrader,
    validator,
)
from claude_kit import export as exporter
from claude_kit import tickets as tickets_mod
from claude_kit.execution_config import (
    ExecutionConfigError,
    configure_execution_policy,
    disable_execution_policy,
    load_execution_policy,
)
from claude_kit.hook_adapter import HookAdapterError, run_registered_hook
from claude_kit.learning_capture import (
    DEFAULT_CHANGED_FILES,
    DEFAULT_CONTEXT_BYTES,
    LearningCaptureError,
    run_codex_learning_capture,
)
from claude_kit.models import (
    ExecutionPolicy,
    InitOptions,
    InstallRequest,
    ModelChoice,
    ModelChoiceKind,
    ResolvedPlan,
    Runtime,
    StateLayout,
    WorkerBinding,
)
from claude_kit.projection import Provider
from claude_kit.runtime_scaffold import (
    RuntimeInstallError,
    install_runtime,
    install_runtime_with_state_migration,
    preview_runtime_install,
)
from claude_kit.secure_fs import ProjectFS
from claude_kit.state import active_state_layout, detect_state_layout
from claude_kit.state_migration import (
    StateMigrationError,
    migrate_legacy_state,
    preview_legacy_state_migration,
)
from claude_kit.worktrees import WorktreeError, WorktreeManager, WorktreeStatus

# Planned-but-unimplemented commands are hidden from `--help` by default so they
# can't be mistaken for working features. Set CLAUDE_KIT_EXPERIMENTAL=1 to surface
# them (still marked "[planned]" and still exit non-zero). Evaluated at import.
_EXPERIMENTAL = bool(
    os.environ.get("CKIT_EXPERIMENTAL") or os.environ.get("CLAUDE_KIT_EXPERIMENTAL")
)

BANNER = r"""
  ___ _      _   _ ___  ___   _  _____ _____
 / __| |    /_\ | | |   \| __| | |/ /_ _|_   _|
| (__| |__ / _ \| |_| | |) | _|  | ' < | |  | |
 \___|____/_/ \_\\___/|___/|___| |_|\_\___| |_|   native SDLC config for Claude Code + Codex
"""

# Shown after init when learning-capture is enabled, and mirrored in SECURITY.md / the project README.
# Keep this wording in sync with those two (the "verbatim" privacy caveat).
CAPTURE_PRIVACY_NOTICE = (
    "Privacy — learning capture is ON: a background selected-host job reads the host transcript\n"
    "when available plus changed files, and records durable learnings under .ckit/agent-memory/\n"
    "(a committed store). It skips secret-bearing files and redacts secret-shaped values, but host\n"
    "context can still be sensitive — review entries before committing. Set\n"
    "CKIT_NO_AUTOCAPTURE=1 to disable and bound it with CKIT_CAPTURE_MAX_LINES/_MAX_BYTES; legacy\n"
    "CLAUDE_KIT_* names remain accepted during the compatibility window."
)

app = typer.Typer(
    add_completion=False,
    no_args_is_help=False,
    help="Scaffold and manage native Claude Code/Codex evidence-gated SDLC configuration.",
)
research_app = typer.Typer(
    no_args_is_help=True, help="Research helpers (license-respecting)."
)
app.add_typer(research_app, name="research", hidden=not _EXPERIMENTAL)
pipeline_app = typer.Typer(
    no_args_is_help=True,
    help="Run, inspect, or mutate the provider-neutral /sdlc pipeline.",
)
app.add_typer(pipeline_app, name="pipeline")
worktree_app = typer.Typer(
    no_args_is_help=True,
    help="Manage provider-neutral, run-owned fallback worktrees.",
)
app.add_typer(worktree_app, name="worktree")
maker_checker_app = typer.Typer(
    no_args_is_help=True,
    help="Configure and inspect the project maker/reviewer model pair.",
)
app.add_typer(maker_checker_app, name="maker-checker")

# Typer's ``Annotated`` declarations are interpreted as positional arguments on
# supported Python 3.9 environments.  Keep these mutable/required option objects
# as distinct module-level singletons so assignment-style declarations remain
# compatible with Python 3.9 without triggering ruff B008.
_HOOK_PROVIDER_OPTION = typer.Option(..., "--provider")
_HOOK_ID_OPTION = typer.Option(..., "--hook-id")
_WORKTREE_STATUS_OPTION = typer.Option(..., "--status")
_PIPELINE_PROVIDER_OPTION = typer.Option(
    ...,
    "--provider",
    help="concrete installed host used for this invocation: claude or codex",
)
_PIPELINE_CONDITION_OPTION = typer.Option(
    None,
    "--condition",
    help="freeze a workflow decision as NAME=true|false; repeat as needed",
)
_PIPELINE_PROGRAM_MANIFEST_OPTION = typer.Option(
    None,
    "--program-manifest",
    help="explicit project-contained frozen manifest required for Mode E",
)


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


@app.command("hook-run", hidden=True)
def hook_run(
    provider: Runtime = _HOOK_PROVIDER_OPTION,
    hook_id: str = _HOOK_ID_OPTION,
    path: str = typer.Option(".", "--path"),
    plugin_root: Optional[str] = typer.Option(None, "--plugin-root"),
    discover_project_root: bool = typer.Option(False, "--discover-project-root"),
) -> None:
    """Internal normalized hook entry point used by generated provider documents."""

    if provider is Runtime.BOTH:
        typer.echo("error: hook provider must be claude or codex", err=True)
        raise typer.Exit(2)
    try:
        result = run_registered_hook(
            provider.value,
            hook_id,
            sys.stdin.buffer.read(),
            project_root=path,
            plugin_root=plugin_root,
            discover_project_root=discover_project_root,
        )
    except (HookAdapterError, OSError, ValueError) as exc:
        typer.echo(f"hook adapter error: {exc}", err=True)
        raise typer.Exit(2) from exc
    if result.stdout:
        typer.echo(result.stdout, nl=False)
    if result.stderr:
        typer.echo(result.stderr, nl=False, err=True)
    if result.exit_code:
        raise typer.Exit(result.exit_code)


@app.command("learning-capture", hidden=True)
def learning_capture(
    path: str = typer.Option(".", "--path"),
    model: Optional[str] = typer.Option(None, "--model"),
    max_files: int = typer.Option(DEFAULT_CHANGED_FILES, "--max-files"),
    max_bytes: int = typer.Option(DEFAULT_CONTEXT_BYTES, "--max-bytes"),
) -> None:
    """Internal trusted writer for the isolated Codex learning-capture hook."""

    try:
        result = run_codex_learning_capture(
            path,
            model=model,
            max_files=max_files,
            max_bytes=max_bytes,
        )
    except (LearningCaptureError, OSError, ValueError) as exc:
        typer.echo(f"learning capture error: {exc}", err=True)
        raise typer.Exit(2) from exc
    typer.echo(result.message)


def _worktree_manager(path: str) -> WorktreeManager:
    try:
        return WorktreeManager(path)
    except (OSError, ValueError, WorktreeError) as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(2) from exc


@worktree_app.command("create")
def worktree_create(
    run_id: str = typer.Argument(...),
    worker_id: str = typer.Argument(...),
    path: str = typer.Option(".", "--path"),
    base_ref: str = typer.Option("HEAD", "--base-ref"),
) -> None:
    """Create one detached, bounded worktree and persist its ownership."""

    try:
        record = _worktree_manager(path).create(run_id, worker_id, base_ref=base_ref)
    except WorktreeError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(2) from exc
    typer.echo(json.dumps(record.to_dict(), sort_keys=True))


@worktree_app.command("list")
def worktree_list(
    path: str = typer.Option(".", "--path"),
    run_id: Optional[str] = typer.Option(None, "--run-id"),
) -> None:
    """List shared-state worktree ownership records as JSON."""

    try:
        records = _worktree_manager(path).records(run_id)
    except WorktreeError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(2) from exc
    typer.echo(json.dumps([record.to_dict() for record in records], sort_keys=True))


@worktree_app.command("mark")
def worktree_mark(
    run_id: str = typer.Argument(...),
    worker_id: str = typer.Argument(...),
    status: WorktreeStatus = _WORKTREE_STATUS_OPTION,
    failure_reason: Optional[str] = typer.Option(None, "--failure-reason"),
    path: str = typer.Option(".", "--path"),
) -> None:
    """Mark a worker succeeded, failed, or aborted without deleting artifacts."""

    try:
        record = _worktree_manager(path).mark(
            run_id, worker_id, status, failure_reason=failure_reason
        )
    except WorktreeError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(2) from exc
    typer.echo(json.dumps(record.to_dict(), sort_keys=True))


@worktree_app.command("cleanup")
def worktree_cleanup(
    run_id: str = typer.Argument(...),
    worker_id: str = typer.Argument(...),
    discard_changes: bool = typer.Option(False, "--discard-changes"),
    discard_failed: bool = typer.Option(False, "--discard-failed"),
    path: str = typer.Option(".", "--path"),
) -> None:
    """Remove one exact owned worktree, requiring explicit artifact-discard flags."""

    try:
        record = _worktree_manager(path).cleanup(
            run_id,
            worker_id,
            discard_changes=discard_changes,
            discard_failed=discard_failed,
        )
    except WorktreeError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(2) from exc
    typer.echo(json.dumps(record.to_dict(), sort_keys=True))


@worktree_app.command("abort-run")
def worktree_abort_run(
    run_id: str = typer.Argument(...),
    path: str = typer.Option(".", "--path"),
) -> None:
    """Mark active workers aborted and preserve every worktree for diagnosis."""

    try:
        records = _worktree_manager(path).abort_run(run_id)
    except WorktreeError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(2) from exc
    typer.echo(json.dumps([record.to_dict() for record in records], sort_keys=True))


@worktree_app.command("resume-run")
def worktree_resume_run(
    run_id: str = typer.Argument(...),
    path: str = typer.Option(".", "--path"),
) -> None:
    """Verify exact ownership for every preserved worktree in a run."""

    try:
        records = _worktree_manager(path).resume_run(run_id)
    except WorktreeError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(2) from exc
    typer.echo(json.dumps([record.to_dict() for record in records], sort_keys=True))


def _maker_checker_failure(exc: ExecutionConfigError) -> None:
    """Render a project configuration failure without leaking a traceback."""

    typer.echo(f"error: {exc}", err=True)
    raise typer.Exit(1) from exc


def _installed_maker_checker_runtime(path: str) -> Runtime:
    """Read the installed providers from the one neutral control-plane manifest."""

    try:
        fs = ProjectFS(Path(path).expanduser())
        manifest = StateLayout.neutral().manifest
        if not fs.is_file(manifest):
            raise ExecutionConfigError(
                "maker-checker configuration requires a runtime-aware install with "
                "neutral .ckit state"
            )
        document = json.loads(fs.read_text(manifest))
        if not isinstance(document, dict):
            raise ValueError("document root must be an object")
        options = InitOptions.from_dict(document)
        if options.state_layout != StateLayout.neutral():
            raise ExecutionConfigError(
                "maker-checker configuration requires a runtime-aware install with "
                "neutral .ckit state"
            )
        return options.runtime
    except ExecutionConfigError:
        raise
    except (json.JSONDecodeError, OSError, TypeError, UnicodeError, ValueError) as exc:
        raise ExecutionConfigError(
            f"cannot read maker-checker configuration: {exc}"
        ) from exc


def _model_choice_label(choice: ModelChoice) -> str:
    """Return the concise CLI representation of a model choice."""

    if choice.kind is ModelChoiceKind.INHERIT:
        return choice.kind.value
    return f"{choice.kind.value}:{choice.value}"


def _model_choice_from_options(
    role: str,
    *,
    tier: Optional[str],
    model_id: Optional[str],
    inherit: bool,
) -> ModelChoice:
    """Require exactly one approved model form for a non-interactive role."""

    selected = sum((tier is not None, model_id is not None, inherit))
    if selected != 1:
        raise ValueError(
            f"{role} requires exactly one of --{role}-model-tier, "
            f"--{role}-model-id, or --{role}-inherit"
        )
    if tier is not None:
        return ModelChoice(ModelChoiceKind.TIER, tier)
    if model_id is not None:
        return ModelChoice(ModelChoiceKind.EXACT, model_id)
    return ModelChoice(ModelChoiceKind.INHERIT)


def _binding_from_options(
    role: str,
    *,
    provider: Optional[str],
    tier: Optional[str],
    model_id: Optional[str],
    inherit: bool,
) -> WorkerBinding:
    """Build one complete, concrete CLI worker binding."""

    if provider is None:
        raise ValueError(f"{role} requires --{role}-provider")
    return WorkerBinding(
        Runtime.parse(provider),
        _model_choice_from_options(
            role,
            tier=tier,
            model_id=model_id,
            inherit=inherit,
        ),
    )


@maker_checker_app.command("show")
def maker_checker_show(
    path: str = typer.Argument(
        ".", help="installed project whose pair should be shown"
    ),
) -> None:
    """Show the configured project maker/reviewer pair."""

    try:
        policy = load_execution_policy(path)
    except ExecutionConfigError as exc:
        _maker_checker_failure(exc)
    if policy is None:
        typer.echo("Maker-checker: disabled")
        return
    typer.echo("Maker-checker: configured")
    typer.echo(
        f"  maker: {policy.maker.provider.value} / "
        f"{_model_choice_label(policy.maker.model)}"
    )
    typer.echo(
        f"  reviewer: {policy.reviewer.provider.value} / "
        f"{_model_choice_label(policy.reviewer.model)}"
    )
    typer.echo(f"  maximum revisions: {policy.max_revisions}")


@maker_checker_app.command("configure")
def maker_checker_configure(
    path: str = typer.Argument(
        ".", help="runtime-aware installed project whose pair should be configured"
    ),
    maker_provider: Optional[str] = typer.Option(None, "--maker-provider"),
    maker_model_tier: Optional[str] = typer.Option(None, "--maker-model-tier"),
    maker_model_id: Optional[str] = typer.Option(None, "--maker-model-id"),
    maker_inherit: bool = typer.Option(False, "--maker-inherit"),
    reviewer_provider: Optional[str] = typer.Option(None, "--reviewer-provider"),
    reviewer_model_tier: Optional[str] = typer.Option(None, "--reviewer-model-tier"),
    reviewer_model_id: Optional[str] = typer.Option(None, "--reviewer-model-id"),
    reviewer_inherit: bool = typer.Option(False, "--reviewer-inherit"),
    max_revisions: Optional[int] = typer.Option(
        None,
        "--max-revisions",
        help="maximum reviewer-requested maker revisions (0-3; default: 2)",
    ),
) -> None:
    """Set the pair interactively, or from one complete set of role options."""

    supplied = any(
        (
            maker_provider is not None,
            maker_model_tier is not None,
            maker_model_id is not None,
            maker_inherit,
            reviewer_provider is not None,
            reviewer_model_tier is not None,
            reviewer_model_id is not None,
            reviewer_inherit,
            max_revisions is not None,
        )
    )
    policy: ExecutionPolicy | None
    if supplied:
        try:
            policy = ExecutionPolicy(
                maker=_binding_from_options(
                    "maker",
                    provider=maker_provider,
                    tier=maker_model_tier,
                    model_id=maker_model_id,
                    inherit=maker_inherit,
                ),
                reviewer=_binding_from_options(
                    "reviewer",
                    provider=reviewer_provider,
                    tier=reviewer_model_tier,
                    model_id=reviewer_model_id,
                    inherit=reviewer_inherit,
                ),
                max_revisions=2 if max_revisions is None else max_revisions,
            )
        except ValueError as exc:
            typer.echo(f"error: {exc}", err=True)
            raise typer.Exit(2) from exc
    else:
        try:
            installed_runtime = _installed_maker_checker_runtime(path)
            policy = prompts.interactive_execution(installed_runtime)
        except ExecutionConfigError as exc:
            _maker_checker_failure(exc)
        except ValueError as exc:
            typer.echo(f"error: {exc}", err=True)
            raise typer.Exit(2) from exc

    if policy is None:
        typer.echo("Maker-checker configuration unchanged.")
        return

    try:
        configure_execution_policy(path, policy)
    except ExecutionConfigError as exc:
        _maker_checker_failure(exc)
    typer.echo("Maker-checker configured.")


@maker_checker_app.command("disable")
def maker_checker_disable(
    path: str = typer.Argument(
        ".", help="installed project whose pair should be disabled"
    ),
) -> None:
    """Disable future maker-checker runs without removing shared state."""

    try:
        changed = disable_execution_policy(path)
    except ExecutionConfigError as exc:
        _maker_checker_failure(exc)
    if changed:
        typer.echo("Maker-checker disabled.")
    else:
        typer.echo("Maker-checker was already disabled.")


def _probe_provider_version(provider: Runtime) -> tuple[bool, str]:
    """Check one configured executable and compatibility floor via ``--version`` only."""

    executable = shutil.which(provider.value)
    if executable is None:
        return False, f"FAIL  {provider.value} executable not found on PATH"
    try:
        result = subprocess.run(
            [executable, "--version"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            check=False,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"FAIL  {provider.value} version probe failed: {exc}"
    if result.returncode != 0:
        return False, (
            f"FAIL  {provider.value} version probe exited {result.returncode}"
        )
    match = re.search(
        r"(?<!\d)(\d+\.\d+\.\d+)(?!\d)",
        f"{result.stdout}\n{result.stderr}",
    )
    if match is None:
        return False, f"FAIL  {provider.value} version is unreadable"
    version = match.group(1)
    compatibility = (
        validator.CLAUDE_CODE_COMPATIBILITY
        if provider is Runtime.CLAUDE
        else validator.CODEX_COMPATIBILITY
    )
    minimum = str(compatibility["minimum"])
    parsed = tuple(int(part) for part in version.split("."))
    required = tuple(int(part) for part in minimum.split("."))
    if parsed < required:
        return False, (
            f"FAIL  {provider.value} {version} is below supported minimum {minimum}"
        )
    return True, f"OK    {provider.value} {version} at {executable}"


@maker_checker_app.command("probe")
def maker_checker_probe(
    path: str = typer.Argument(
        ".", help="installed project whose pair should be checked"
    ),
) -> None:
    """Check configuration and host CLI readiness without sending a model prompt."""

    try:
        policy = load_execution_policy(path)
    except ExecutionConfigError as exc:
        typer.echo(f"FAIL  configuration is unreadable: {exc}")
        typer.echo(
            "INFO  Probe used local configuration only; no inference call was made."
        )
        raise typer.Exit(1) from exc
    if policy is None:
        typer.echo("FAIL  maker-checker configuration is disabled")
        typer.echo(
            "INFO  Probe used local configuration only; no inference call was made."
        )
        raise typer.Exit(1)

    typer.echo("OK    maker-checker configuration is enabled and valid")
    providers: list[Runtime] = []
    for binding in (policy.maker, policy.reviewer):
        if binding.provider not in providers:
            providers.append(binding.provider)
        if binding.model.kind is ModelChoiceKind.EXACT:
            typer.echo(
                f"INFO  {binding.provider.value} exact model {binding.model.value!r} "
                "is syntax-valid; model access was not probed"
            )

    ready = True
    for provider in providers:
        provider_ready, message = _probe_provider_version(provider)
        typer.echo(message)
        ready = ready and provider_ready
    typer.echo(
        "INFO  Probe used executable lookup and --version only; no inference call was made."
    )
    if not ready:
        raise typer.Exit(1)


# ``maker-checker run`` is intentionally registered by the managed coordinator slice.


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
    except (ValueError, OSError) as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(2) from exc


def _resolve_execution_policy(
    runtime: Runtime,
    *,
    config: Optional[str],
    defaults: bool,
) -> ExecutionPolicy | None:
    """Resolve runtime-only maker/reviewer settings exactly once per init invocation."""

    try:
        if config is not None:
            return prompts.execution_from_config(config, runtime)
        if defaults:
            return None
        return prompts.interactive_execution(runtime)
    except (OSError, ValueError) as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(2) from exc


def _print_dry_run(
    src: Path,
    target: Path,
    plan: ResolvedPlan,
    request: InstallRequest | None = None,
    *,
    force: bool = False,
    additional_paths: tuple[str, ...] = (),
) -> None:
    """Print the resolved plan + exact live-target writes. Touches nothing."""
    sel = plan.selection
    stack_str = (
        f"{sel.frontend_framework}/{sel.frontend_language} + "
        f"{sel.backend_language}/{sel.backend_framework} + {sel.database}"
    )
    if request is None:
        _, paths = scaffold.preview_install(src, target, plan)
    else:
        _, paths = preview_runtime_install(src, target, plan, request, force=force)
    paths = sorted(set(paths).union(additional_paths))
    typer.echo(f"\nDRY RUN — previewing install into {target} (no files written)\n")
    typer.echo(f"  profile : {sel.profile}    scope: {sel.scope}")
    typer.echo(f"  runtime : {request.runtime.value if request else 'claude (legacy)'}")
    if request is not None:
        if request.execution_policy is None:
            typer.echo("  execution: disabled")
        else:
            policy = request.execution_policy
            typer.echo(
                "  execution: "
                f"maker {policy.maker.provider.value}/{_model_choice_label(policy.maker.model)} "
                "-> reviewer "
                f"{policy.reviewer.provider.value}/{_model_choice_label(policy.reviewer.model)}; "
                f"maximum revisions {policy.max_revisions}"
            )
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


def _dry_run_doc(
    src: Path,
    target: Path,
    plan: ResolvedPlan,
    request: InstallRequest | None = None,
    *,
    force: bool = False,
    additional_paths: tuple[str, ...] = (),
) -> dict:
    """The same plan + would-write file list as :func:`_print_dry_run`, as a JSON-able dict."""
    sel = plan.selection
    if request is None:
        _, paths = scaffold.preview_install(src, target, plan)
    else:
        _, paths = preview_runtime_install(src, target, plan, request, force=force)
    paths = sorted(set(paths).union(additional_paths))
    document = {
        "dry_run": True,
        "target": str(target),
        "runtime": request.runtime.value if request else "claude",
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
    if request is not None:
        document["execution"] = (
            request.execution_policy.to_dict()
            if request.execution_policy is not None
            else None
        )
    return document


def _fs_failure(what: str, target: Path, exc: OSError) -> typer.Exit:
    """Report a filesystem failure the way every other command does, and stop.

    An OSError that escapes ``init`` reaches the user as a traceback, which reads as a crash rather
    than a refusal. The distinction matters because the two demand different responses: a crash
    invites a bug report, a refusal tells you to fix the path and retry.
    """
    typer.echo(f"error: cannot {what} {target} — {exc.strerror or exc}", err=True)
    return typer.Exit(1)


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
    runtime: Optional[str] = typer.Option(
        None,
        "--runtime",
        help=(
            "native runtime projection: claude, codex, or both. Codex/both are preview "
            "and require CKIT_EXPERIMENTAL=1 (legacy CLAUDE_KIT_EXPERIMENTAL is accepted)."
        ),
    ),
    migrate_state: bool = typer.Option(
        False,
        "--migrate-state",
        help=(
            "explicitly copy a legacy .claude mutable control plane into .ckit before "
            "applying a native runtime transition"
        ),
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help=(
            "overwrite mode: replace CLAUDE.md / settings.json / .mcp.json and rebuild the "
            "kit-owned trees (rules/, skills/, templates/). Your own files in those trees are "
            "moved to .claude-kit.bak-N/, not deleted. Omit --force to merge instead."
        ),
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
    """Scaffold an evidence-gated SDLC configuration into a project."""
    non_interactive = defaults or config is not None
    runtime_choice: Runtime | None
    try:
        if runtime is not None:
            runtime_choice = Runtime.parse(runtime)
        elif config is not None:
            runtime_choice = prompts.runtime_from_config(config)
        else:
            runtime_choice = None
    except (OSError, ValueError) as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(2) from exc
    if runtime_choice is not None:
        experimental = bool(
            os.environ.get("CKIT_EXPERIMENTAL")
            or os.environ.get("CLAUDE_KIT_EXPERIMENTAL")
        )
        if runtime_choice in {Runtime.CODEX, Runtime.BOTH} and not experimental:
            typer.echo(
                "error: Codex and dual-runtime installation are preview features; set "
                "CKIT_EXPERIMENTAL=1 (or legacy CLAUDE_KIT_EXPERIMENTAL=1) and retry",
                err=True,
            )
            raise typer.Exit(2)
    if runtime_choice is None and migrate_state:
        typer.echo(
            "error: --migrate-state requires a runtime in --runtime or --config",
            err=True,
        )
        raise typer.Exit(2)
    if json_out and not dry_run:
        typer.echo("error: --json is only supported together with --dry-run", err=True)
        raise typer.Exit(2)
    with ExitStack() as stack:
        src = scaffold.payload_dir(stack)

        # 1) Target path. Tolerate EOF (non-TTY stdin, e.g. an agent's shell tool) the same way
        # prompts._ask does — fall back to the default instead of aborting.
        if path is None:
            if non_interactive:
                raw = "."
            else:
                try:
                    raw = input("Target path [.]: ").strip() or "."
                except EOFError:
                    raw = "."
        else:
            raw = path
        entered_target = Path(raw).expanduser()
        try:
            project_fs = ProjectFS(entered_target)
        except OSError as exc:
            raise _fs_failure("use", entered_target, exc) from exc
        target = project_fs.root

        # --dry-run: resolve + preview only. Never create the target or write anything; skip the
        # existing-.claude handling and the install spine entirely.
        if dry_run:
            try:
                plan = _resolve_plan(src, config=config, defaults=defaults)
                if detect_commands is not None:
                    plan.selection.detect_commands = detect_commands
                request = (
                    InstallRequest(
                        plan.selection,
                        runtime_choice,
                        _resolve_execution_policy(
                            runtime_choice,
                            config=config,
                            defaults=defaults,
                        ),
                    )
                    if runtime_choice is not None
                    else None
                )
                migration_paths: tuple[str, ...] = ()
                if request is not None:
                    legacy_manifest = StateLayout.legacy_claude().manifest
                    state_layout = active_state_layout(project_fs)
                    needs_migration = state_layout == StateLayout.legacy_claude()
                    if needs_migration and not migrate_state:
                        raise RuntimeInstallError(
                            "legacy mutable state is installed under .claude; rerun with "
                            "--migrate-state to copy it transactionally into .ckit"
                        )
                    if (
                        needs_migration
                        and migrate_state
                        and request.runtime is Runtime.CODEX
                        and project_fs.is_file(legacy_manifest)
                    ):
                        raise RuntimeInstallError(
                            "migrating legacy Claude state directly to Codex would "
                            "remove the installed Claude projection without confirmation "
                            "or a recoverable backup; run `ckit migrate-state <path>` "
                            "first, then `ckit upgrade <path> --runtime codex "
                            "--confirm-runtime-removal`"
                        )
                    # An explicit migration also owns untracked legacy state when
                    # no authoritative layout exists. A neutral marker still wins,
                    # matching the real transaction's layout-precedence rule.
                    if migrate_state and state_layout != StateLayout.neutral():
                        migration_paths = preview_legacy_state_migration(
                            target
                        ).copied_paths
                if json_out:
                    typer.echo(
                        json.dumps(
                            _dry_run_doc(
                                src,
                                target,
                                plan,
                                request,
                                force=force,
                                additional_paths=migration_paths,
                            ),
                            indent=2,
                        )
                    )
                else:
                    _print_dry_run(
                        src,
                        target,
                        plan,
                        request,
                        force=force,
                        additional_paths=migration_paths,
                    )
            except (RuntimeInstallError, StateMigrationError, ValueError) as exc:
                typer.echo(f"error: {exc}", err=True)
                raise typer.Exit(1) from exc
            return

        if not target.exists():
            if not non_interactive and not typer.confirm(
                f"Create {target}?", default=True
            ):
                typer.echo("aborted.")
                raise typer.Exit(0)

        # 2) Existing .claude handling: merge / overwrite / backup / abort.
        mode = "fresh"
        overwrite = force
        try:
            has_claude = project_fs.exists(".claude")
        except OSError as exc:
            raise _fs_failure("inspect", target / ".claude", exc) from exc
        if has_claude and runtime_choice is None:
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
        # 3) Resolve the selection.
        plan = _resolve_plan(src, config=config, defaults=defaults)
        if detect_commands is not None:
            plan.selection.detect_commands = detect_commands

        if runtime_choice is not None:
            request = InstallRequest(
                plan.selection,
                runtime_choice,
                _resolve_execution_policy(
                    runtime_choice,
                    config=config,
                    defaults=defaults,
                ),
            )
            try:
                needs_migration = (
                    active_state_layout(project_fs) == StateLayout.legacy_claude()
                )
                if needs_migration and not migrate_state:
                    raise RuntimeInstallError(
                        "legacy mutable state is installed under .claude; rerun with "
                        "--migrate-state to copy it transactionally into .ckit"
                    )
                typer.echo(
                    f"\nckit: installing native {runtime_choice.value} projection into {target}"
                )
                if migrate_state:
                    lines, migrated = install_runtime_with_state_migration(
                        src,
                        target,
                        plan,
                        request,
                        force=force,
                        require_legacy_source=needs_migration,
                    )
                    if migrated.migrated:
                        typer.echo("  • legacy mutable state migrated to .ckit")
                    elif migrated.already_neutral:
                        typer.echo("  • neutral state already current")
                    else:
                        typer.echo("  • no legacy mutable state required migration")
                else:
                    lines = install_runtime(
                        src,
                        target,
                        plan,
                        request,
                        force=force,
                    )
                for line in lines:
                    typer.echo(line)
            except (RuntimeInstallError, StateMigrationError) as exc:
                typer.echo(f"error: {exc}", err=True)
                raise typer.Exit(1) from exc
            except OSError as exc:
                raise _fs_failure("write into", target, exc) from exc

            if runtime_choice is Runtime.CLAUDE:
                typer.echo(
                    "\nDone. Open the project in Claude Code and run `/sdlc <your task>`."
                )
            elif runtime_choice is Runtime.CODEX:
                typer.echo(
                    "\nDone. Open the trusted project in Codex and invoke the `sdlc` skill."
                )
            else:
                typer.echo(
                    "\nDone. The project now has native Claude Code and Codex discovery "
                    "surfaces backed by one .ckit state ledger."
                )
            if plan.selection.capture_mode != "off":
                typer.echo("\n" + CAPTURE_PRIVACY_NOTICE)
            return

        # 4) Install. Merge mode reconciles non-destructively (preserving the user's own files);
        # fresh / overwrite / backup all go through the destructive install spine.
        # The guard covers the whole install, not just the initial mkdir: an existing target that
        # cannot be written into never reaches that mkdir, and the OSError surfaced from deep
        # inside install_sdlc instead (F-087).
        try:
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
                for line in scaffold.install_sdlc(
                    src,
                    target,
                    plan,
                    force=overwrite,
                    backup_existing=mode == "backup",
                ):
                    typer.echo(line)
        except OSError as exc:
            raise _fs_failure("write into", target, exc) from exc

    typer.echo(
        "\nDone. Open the project in Claude Code and run `/sdlc <your task>` to start the pipeline."
    )
    if plan.selection.capture_mode != "off":
        typer.echo("\n" + CAPTURE_PRIVACY_NOTICE.replace(".ckit/", ".claude/"))
    # The shell guard/notify hooks parse tool input with jq and no-op without it (see SECURITY.md).
    if not shutil.which("jq"):
        typer.echo(
            "\nNote: `jq` is not on PATH — the shell hooks (guards + learning capture) will silently "
            "no-op until you install it. The config, agents, skills, and CLI work regardless."
        )


@app.command("migrate-state", hidden=not _EXPERIMENTAL)
def migrate_state_command(
    path: str = typer.Argument(
        ".", help="installed project whose state should move to .ckit"
    ),
) -> None:
    """Transactionally expand a legacy .claude control plane into neutral .ckit state."""

    try:
        result = migrate_legacy_state(path)
    except (OSError, StateMigrationError) as exc:
        typer.echo(f"error: state migration failed: {exc}", err=True)
        raise typer.Exit(1) from exc
    if result.already_neutral:
        typer.echo("OK    neutral .ckit state is already authoritative")
    elif result.migrated:
        typer.echo(
            f"OK    migrated {len(result.copied_paths)} legacy state file(s) into .ckit; "
            ".claude compatibility bytes were preserved"
        )
    else:
        typer.echo("OK    no legacy mutable state was present; nothing changed")


def _plan_for_export(
    src: Path, target_dir: Path, *, config: Optional[str], defaults: bool
) -> ResolvedPlan:
    """Resolve the plan to export: prefer the project's installed selection, else config/defaults/prompt.

    ``export .`` in an installed project reads ``.claude/config/init-options.json`` so the export
    matches what was scaffolded. ``--config`` / ``--defaults`` force a fresh resolution (useful for a
    standalone export into a project that never ran ``init``); with neither and no install present, it
    falls back to the interactive prompt via :func:`_resolve_plan`.
    """
    fs = ProjectFS(target_dir)
    opts_rel = next(
        (
            candidate
            for candidate in (
                StateLayout.neutral().manifest,
                StateLayout.legacy_claude().manifest,
            )
            if fs.is_file(candidate)
        ),
        None,
    )
    if config is None and not defaults and opts_rel is not None:
        try:
            data = json.loads(fs.read_text(opts_rel))
            options = InitOptions.from_dict(data)
            return catalog.resolve(src, options.selection)
        except (TypeError, ValueError, KeyError, json.JSONDecodeError) as exc:
            typer.echo(f"error: could not read installed selection: {exc}", err=True)
            raise typer.Exit(2) from exc
    return _resolve_plan(src, config=config, defaults=defaults)


# Module-level singleton: a repeatable-list option can't be defined inline (ruff B008 flags a call in
# a mutable-typed argument default), so the Option lives here and the command reads it as its default.
_EXPORT_TARGET_OPTION = typer.Option(
    None,
    "--target",
    "-t",
    help="export target(s), repeatable: cursor | agents | copilot (default: cursor)",
)


@app.command()
def export(
    path: str = typer.Argument(".", help="target project dir (default: .)"),
    target: Optional[list[str]] = _EXPORT_TARGET_OPTION,
    config: Optional[str] = typer.Option(
        None,
        "--config",
        help="resolve the selection from a YAML file instead of the installed one",
    ),
    defaults: bool = typer.Option(
        False,
        "--defaults",
        help="resolve from catalog defaults instead of the installed selection",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="overwrite existing exported files instead of writing .claude-kit sidecars",
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="report the files that would be written; write nothing"
    ),
    json_out: bool = typer.Option(
        False, "--json", help="emit the written-file list as JSON instead of text"
    ),
) -> None:
    """Export the config for Cursor / AGENTS.md / GitHub Copilot (editors that aren't Claude Code).

    Projects the same resolved plan claude-kit installs under .claude/ into the formats a single-agent
    editor reads natively — the full rule set + a project charter + the SDLC workflow as guidance, plus
    MCP servers for Cursor. The enforced gates and reviewer subagents are Claude Code-only.
    """
    targets = list(dict.fromkeys(target or ["cursor"]))
    unknown = [t for t in targets if t not in exporter.VALID_TARGETS]
    if unknown:
        typer.echo(
            f"error: unknown export target(s): {', '.join(unknown)} "
            f"(choices: {', '.join(exporter.VALID_TARGETS)})",
            err=True,
        )
        raise typer.Exit(2)
    with ExitStack() as stack:
        src = scaffold.payload_dir(stack)
        entered_target = Path(path).expanduser()
        try:
            project_fs = ProjectFS(entered_target)
            target_dir = project_fs.root
        except OSError as exc:
            raise _fs_failure("use", entered_target, exc) from exc
        try:
            if dry_run:
                plan = _plan_for_export(
                    src, target_dir, config=config, defaults=defaults
                )
                written, current = exporter.export_targets(
                    src, target_dir, plan, targets, force=force, dry_run=True
                )
            else:
                # Read the installed selection and write its projection under one
                # shared lease. A concurrent lifecycle transaction must finish (or
                # this command refuses cleanly) before either step can proceed.
                with project_fs.mutation_lease():
                    plan = _plan_for_export(
                        src, target_dir, config=config, defaults=defaults
                    )
                    written, current = exporter.export_targets(
                        src, target_dir, plan, targets, force=force, dry_run=False
                    )
        except OSError as exc:
            raise _fs_failure("export into", target_dir, exc) from exc

    if json_out:
        typer.echo(
            json.dumps(
                {
                    "target": str(target_dir),
                    "targets": targets,
                    "dry_run": dry_run,
                    "written": written,
                    "already_current": current,
                },
                indent=2,
            )
        )
        return

    typer.echo(f"\nclaude-kit export → {', '.join(targets)}  ({target_dir})\n")
    for w in written:
        typer.echo(f"  {'+' if dry_run else '•'} {w}")
    for c in current:
        typer.echo(f"  = {c} (already current)")
    tail = "  (dry run — nothing written)" if dry_run else ""
    summary = f"{'Would write' if dry_run else 'Wrote'} {len(written)} file(s)"
    if current:
        summary += f"; {len(current)} already current"
    typer.echo(f"\n{summary}.{tail}")


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
    entered_target = Path(path).expanduser()
    try:
        result = validator.validate(entered_target, strict=strict)
    except OSError as exc:
        raise _fs_failure("inspect", entered_target, exc) from exc
    _emit_report(*result, as_json=json_out)


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
    entered_target = Path(path).expanduser()
    try:
        result = validator.doctor(entered_target, mcp=mcp)
    except OSError as exc:
        raise _fs_failure("inspect", entered_target, exc) from exc
    _emit_report(*result, as_json=json_out)


@app.command()
def diff(
    path: str = typer.Argument(".", help="target project dir (default: .)"),
    json_out: bool = typer.Option(
        False, "--json", help="emit a machine-readable JSON report instead of text"
    ),
) -> None:
    """Preview what an upgrade would change (no writes)."""
    entered_target = Path(path).expanduser()
    try:
        result = upgrader.diff(entered_target)
    except OSError as exc:
        raise _fs_failure("inspect", entered_target, exc) from exc
    _emit_report(*result, as_json=json_out)


@app.command()
def upgrade(
    path: str = typer.Argument(".", help="target project dir (default: .)"),
    force: bool = typer.Option(
        False, "--force", help="overwrite user-modified kit files"
    ),
    runtime: Optional[str] = typer.Option(
        None,
        "--runtime",
        help="explicitly transition a native install to claude, codex, or both",
    ),
    confirm_runtime_removal: bool = typer.Option(
        False,
        "--confirm-runtime-removal",
        help="confirm recoverable backup/removal of a provider projection",
    ),
) -> None:
    """Refresh kit-owned files, backing up user-modified ones."""
    runtime_choice: Runtime | None = None
    if runtime is not None:
        try:
            runtime_choice = Runtime.parse(runtime)
        except ValueError as exc:
            typer.echo(f"error: {exc}", err=True)
            raise typer.Exit(2) from exc
        if runtime_choice in {Runtime.CODEX, Runtime.BOTH} and not bool(
            os.environ.get("CKIT_EXPERIMENTAL")
            or os.environ.get("CLAUDE_KIT_EXPERIMENTAL")
        ):
            typer.echo(
                "error: Codex runtime transitions are preview features; set "
                "CKIT_EXPERIMENTAL=1 and retry",
                err=True,
            )
            raise typer.Exit(2)
    entered_target = Path(path).expanduser()
    try:
        result = upgrader.upgrade(
            entered_target,
            force=force,
            runtime=runtime_choice,
            confirm_runtime_removal=confirm_runtime_removal,
        )
    except OSError as exc:
        raise _fs_failure("upgrade", entered_target, exc) from exc
    _print_report(*result)


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
    entered_target = Path(path).expanduser()
    try:
        project_fs = ProjectFS(entered_target)
        target = project_fs.root
        layout = detect_state_layout(target, fresh_default=StateLayout.legacy_claude())
    except OSError as exc:
        raise _fs_failure("inspect", entered_target, exc) from exc

    # Collect the data once, then render as text or JSON without another filesystem read.
    components: dict[str, Optional[int]] = {}
    provider_components: dict[str, dict[str, Optional[int]]] = {}
    runtimes: list[str] = []
    selection: Optional[dict] = None
    continuity_present = False
    continuity_lines: list[str] = []
    pipeline_snapshot: dict = {}
    try:
        manifest_present = project_fs.is_file(layout.manifest)
        installed = manifest_present or (
            layout == StateLayout.legacy_claude() and project_fs.is_dir(layout.root)
        )
        if installed:
            parsed_options: InitOptions | None = None
            if manifest_present:
                document = json.loads(project_fs.read_text(layout.manifest))
                parsed_options = InitOptions.from_dict(document)
                with ExitStack() as stack:
                    catalog.resolve(
                        scaffold.payload_dir(stack), parsed_options.selection
                    )
                selection = parsed_options.selection.to_dict()

            runtimes = parsed_options.runtimes if parsed_options else ["claude"]
            if "claude" in runtimes:
                component_dirs = {
                    name: target / ".claude" / name
                    for name in ("rules", "agents", "skills", "hooks")
                }
                claude_components: dict[str, Optional[int]] = {}
                for name, directory in component_dirs.items():
                    if not directory.is_dir():
                        claude_components[name] = None
                    elif name == "skills":
                        # A skill is a directory holding SKILL.md; skills/_references/ is shared
                        # support content, not a skill — this matches validate's count.
                        claude_components[name] = sum(
                            1
                            for path in directory.iterdir()
                            if (path / "SKILL.md").is_file()
                        )
                    else:
                        claude_components[name] = sum(
                            1 for path in directory.iterdir() if path.name != ".gitkeep"
                        )
                provider_components["claude"] = claude_components
                components = dict(claude_components)
            if "codex" in runtimes:
                # Codex projects encode the rule set in AGENTS.md rather than a .codex/rules
                # directory. The remaining component counts stay filesystem-backed just like the
                # Claude view and never consult a synthetic .claude tree.
                counted_codex: dict[str, Optional[int]] = {
                    "rules": 1 if (target / "AGENTS.md").is_file() else None
                }
                codex_dirs = {
                    "agents": target / ".codex" / "agents",
                    "skills": target / ".agents" / "skills",
                    "hooks": target / ".codex" / "hooks" / "scripts",
                }
                for name, directory in codex_dirs.items():
                    if not directory.is_dir():
                        counted_codex[name] = None
                    elif name == "skills":
                        counted_codex[name] = sum(
                            1
                            for path in directory.iterdir()
                            if (path / "SKILL.md").is_file()
                        )
                    else:
                        counted_codex[name] = sum(
                            1 for path in directory.iterdir() if path.name != ".gitkeep"
                        )
                provider_components["codex"] = counted_codex
                if "claude" not in runtimes:
                    components = dict(counted_codex)
            continuity_present = project_fs.is_file(layout.continuity)
            if continuity_present:
                continuity_lines = (
                    project_fs.read_bytes(layout.continuity)
                    .decode("utf-8", errors="replace")
                    .splitlines()[:30]
                )
            pipeline_snapshot = tickets_mod.pipeline_stage(target)
    except (TypeError, ValueError, KeyError, json.JSONDecodeError) as exc:
        typer.echo(f"error: could not read installed selection: {exc}", err=True)
        raise typer.Exit(2) from exc
    except OSError as exc:
        raise _fs_failure("inspect", entered_target, exc) from exc

    if json_out:
        typer.echo(
            json.dumps(
                {
                    "target": str(target),
                    "installed": installed,
                    "runtimes": runtimes,
                    "components": components,
                    "provider_components": provider_components,
                    "selection": selection,
                    "continuity": continuity_present,
                    "state_layout": layout.to_dict(),
                    "pipeline": pipeline_snapshot or None,
                },
                indent=2,
            )
        )
        return

    typer.echo(f"claude-kit status for {target}")
    if not installed:
        typer.echo("  not installed — run `claude-kit init` here.")
        return
    typer.echo(f"  • runtimes: {', '.join(runtimes)}")
    for name in ("rules", "agents", "skills", "hooks"):
        n = components[name]
        typer.echo(f"  • {name}/: {n}" if n is not None else f"  • {name}/: (missing)")
    if len(provider_components) > 1:
        typer.echo("  • native projections:")
        for provider in runtimes:
            counts = provider_components.get(provider, {})
            summary = ", ".join(
                f"{name}={counts.get(name) if counts.get(name) is not None else 'missing'}"
                for name in ("rules", "agents", "skills", "hooks")
            )
            typer.echo(f"      - {provider}: {summary}")
    if selection is not None:
        sel = selection
        typer.echo(
            f"  • selection: {sel.get('frontend_framework')} + "
            f"{sel.get('backend_language')}/{sel.get('backend_framework')} + "
            f"{sel.get('database')} · profile={sel.get('profile')} · mcp={sel.get('mcp') or 'none'}"
        )
    if pipeline_snapshot:
        stage = (
            pipeline_snapshot.get("stage")
            or pipeline_snapshot.get("phase")
            or "unknown"
        )
        gate = pipeline_snapshot.get("last_gate_passed")
        suffix = f" · last gate={gate}" if gate else ""
        typer.echo(f"  • pipeline: {stage}{suffix}")
    if continuity_present:
        typer.echo(f"\n  working memory ({layout.continuity}):")
        for line in continuity_lines:
            typer.echo(f"    {line}")
    else:
        typer.echo("\n  no CONTINUITY.md yet (no pipeline run recorded).")


def _load_ticket_view(
    target: Path, transcript_dir: Optional[str]
) -> "tickets_mod.Store":
    """Load the ticket store and join live per-branch telemetry onto it."""
    store = tickets_mod.load_store(target)
    projects_root = Path(transcript_dir).expanduser() if transcript_dir else None
    tickets_mod.attach_telemetry(store, telemetry.collect(target, projects_root))
    return store


def write_board_html(store: "tickets_mod.Store", target: Path, refresh: int) -> Path:
    """Write the HTML board under the project's gitignored state dir; return the path."""
    fs = ProjectFS(target)
    with fs.mutation_lease():
        return fs.write_text(
            board_html.board_rel(target),
            board_html.render_html(
                store,
                refresh=refresh,
                stage=tickets_mod.pipeline_stage(target),
                gates=pipeline.installed_gates(target),
            ),
        )


def _launch_browser(url: str) -> bool:
    """Open ``url`` in the default browser. Never raises — a dashboard is not worth an exit code.

    Headless CI, an SSH session, and a container with no browser all land here, and all three are
    normal ways to run this. ``webbrowser.open`` reports failure by returning ``False`` on some
    platforms and by raising on others, so both are treated as the same soft miss.
    """
    try:
        return webbrowser.open(url)
    except Exception:  # noqa: BLE001 - any browser-launch failure degrades to the printed URL
        return False


def _render_tickets(
    store: "tickets_mod.Store", target: Path, ticket_id: Optional[str], graph: str
) -> list[str]:
    if ticket_id:
        return tickets_mod.render_detail(store, ticket_id, target)
    if graph == "git":
        return tickets_mod.render_git_graph(store, target)
    if graph == "deps":
        return tickets_mod.render_graph(store)
    return tickets_mod.render_board(store)


@app.command()
def tickets(
    ticket_id: Optional[str] = typer.Argument(
        None, help="show one ticket in detail (e.g. PROJ-12); omit for the whole board"
    ),
    path: str = typer.Option(".", "--path", help="target project dir (default: .)"),
    graph: bool = typer.Option(
        False, "--graph", help="render the ticket dependency graph instead of the board"
    ),
    graph_git: bool = typer.Option(
        False,
        "--graph-git",
        help="render the commit graph, annotated with each commit's ticket",
    ),
    watch: Optional[int] = typer.Option(
        None, "--watch", help="re-render every N seconds until interrupted (min 1)"
    ),
    json_out: bool = typer.Option(
        False, "--json", help="emit a machine-readable JSON summary instead of text"
    ),
    html: bool = typer.Option(
        False,
        "--html",
        help=f"write a self-contained Kanban board to {board_html.BOARD_REL} and print its URL",
    ),
    open_browser: bool = typer.Option(
        False,
        "--open",
        help="write the board (implies --html) and open it in the default browser, once",
    ),
    refresh: int = typer.Option(
        10,
        "--refresh",
        help="browser auto-refresh interval in seconds for --html (0 disables)",
    ),
    transcript_dir: Optional[str] = typer.Option(
        None,
        "--transcript-dir",
        help="override the Claude Code projects dir telemetry is read from",
    ),
) -> None:
    """Show the ticket board with live token, model, agent, and timing figures."""
    entered_target = Path(path).expanduser()
    try:
        target = ProjectFS(entered_target).root
    except OSError as exc:
        raise _fs_failure("use", entered_target, exc) from exc
    if graph and graph_git:
        typer.echo("--graph and --graph-git are alternatives; pass only one.")
        raise typer.Exit(2)
    mode = "git" if graph_git else "deps" if graph else ""
    # --open is a way of asking for the board, so it implies --html rather than erroring without it.
    write_html = html or open_browser
    # Under --watch, emit() runs every interval; the browser must be launched by the first pass
    # only, or a board left watching all afternoon opens a window every few seconds.
    opened = False

    def emit() -> int:
        """Render once. Returns a process exit code so an unknown id is detectable by scripts."""
        nonlocal opened
        store = _load_ticket_view(target, transcript_dir)
        if write_html:
            try:
                out = write_board_html(store, target, refresh)
            except OSError as exc:
                raise _fs_failure("write the ticket board into", target, exc) from exc
            url = f"file://{out}"
            typer.echo(f"wrote {out}")
            typer.echo(f"open {url}")
            if open_browser and not opened:
                opened = True
                if not _launch_browser(url):
                    typer.echo("could not open a browser here — use the path above")
            if refresh > 0:
                typer.echo(
                    f"the page reloads every {refresh}s; the Stop hook keeps the file current"
                )
            return 0
        if json_out:
            counts = store.counts()
            typer.echo(
                json.dumps(
                    {
                        "target": str(target),
                        "prefix": store.prefix,
                        "store_exists": store.exists,
                        "counts": counts,
                        "tickets": [
                            dict(
                                t.to_dict(),
                                display_status=store.display_status(t),
                                blockers=store.blockers(t),
                                actionable=store.is_actionable(t),
                            )
                            for t in store.ordered()
                        ],
                    },
                    indent=2,
                )
            )
            return 0
        for line in _render_tickets(store, target, ticket_id, mode):
            typer.echo(line)
        if ticket_id and not (
            ticket_id in store.tickets or ticket_id.upper() in store.tickets
        ):
            return (
                2  # same lookup render_detail uses, so the message and the code agree
            )
        return 0

    if watch is None:
        raise typer.Exit(emit())

    interval = max(1, watch)
    try:
        while True:
            # Home the cursor and clear, so the board updates in place rather than scrolling.
            typer.echo("\033[H\033[2J", nl=False)
            if emit():
                raise typer.Exit(2)
            typer.echo(f"\n(refreshing every {interval}s — Ctrl-C to stop)")
            time.sleep(interval)
    except KeyboardInterrupt:
        typer.echo("")


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


@app.command("privacy-report")
def privacy_report(
    path: str = typer.Argument(".", help="target project dir (default: .)"),
    json_out: bool = typer.Option(
        False, "--json", help="emit a machine-readable JSON report instead of text"
    ),
) -> None:
    """Show what every installed hook reads, writes, or spawns — the informed-consent view.

    Lists each hook in .claude/settings.json with its data access (transcript reads, background
    jobs, LLM calls, local-only guards), flags hook commands that didn't come from this kit, and
    states whether background learning capture is on and how to turn it off.
    """
    _emit_report(*hooks.privacy_report(path), as_json=json_out)


_WORKFLOW_CONDITION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def _workflow_conditions(values: Optional[list[str]]) -> dict[str, bool]:
    """Parse repeatable ``NAME=true|false`` decisions without guessing intent."""

    decisions: dict[str, bool] = {}
    for raw in values or []:
        name, separator, raw_value = raw.partition("=")
        name = name.strip()
        value = raw_value.strip().lower()
        if (
            separator != "="
            or not _WORKFLOW_CONDITION_RE.fullmatch(name)
            or ".." in name
            or value not in {"true", "false"}
        ):
            raise ValueError(
                f"invalid workflow condition {raw!r}; expected NAME=true or NAME=false"
            )
        if name in decisions:
            raise ValueError(f"workflow condition {name!r} was provided more than once")
        decisions[name] = value == "true"
    return decisions


def _workflow_result_document(result: object) -> dict[str, Any]:
    """Return the bounded, provider-neutral public view of an execution result."""

    from claude_kit.dispatch import public_human_stop_text
    from claude_kit.workflow_executor import WorkflowExecutionResult

    if not isinstance(result, WorkflowExecutionResult):
        raise TypeError("workflow executor returned an unsupported result")
    human_stop = None
    if result.human_stop is not None:
        human_stop = {
            "reason": result.human_stop.reason.value,
            "message": public_human_stop_text(
                result.human_stop.message,
                fallback="managed execution requires a human decision",
            ),
            "requested_action": public_human_stop_text(
                result.human_stop.requested_action,
                fallback="inspect the private run artifacts and decide how to proceed",
            ),
        }
    attempts = []
    for attempt in result.attempts:
        artifact = None
        if attempt.artifact is not None:
            artifact = {
                "path": attempt.artifact.path,
                "sha256": attempt.artifact.sha256,
                "truncated": attempt.artifact.truncated,
                "category": attempt.artifact.category,
            }
        attempts.append(
            {
                "stage": attempt.stage,
                "role": attempt.role,
                "dispatch_id": attempt.handle.id,
                "attempt": attempt.handle.attempt,
                "provider": attempt.handle.provider,
                "status": attempt.status.value,
                "evidence": [reference.uri for reference in attempt.evidence],
                "error": attempt.error,
                "artifact": artifact,
            }
        )
    return {
        "status": result.status.value,
        "completed_stages": list(result.completed_stages),
        "skipped_stages": list(result.skipped_stages),
        "pending_gates": list(result.pending_gates),
        "human_stop": human_stop,
        "attempts": attempts,
        "messages": list(result.messages),
    }


def _pending_workflow_stop_document(
    snapshot: dict[str, Any],
) -> Optional[dict[str, Any]]:
    """Return a stable public checkpoint when a persisted human stop is pending."""

    from claude_kit.dispatch import public_human_stop_text

    raw_stops = snapshot.get("human_stops", [])
    if not isinstance(raw_stops, list):
        raise ValueError("active pipeline run has a malformed human-stop ledger")
    pending = [
        stop
        for stop in raw_stops
        if isinstance(stop, dict) and stop.get("status") == "pending"
    ]
    if not pending:
        return None
    if len(pending) != 1:
        raise ValueError("active pipeline run has more than one pending human stop")
    stop = pending[0]
    stop_id = public_human_stop_text(stop.get("stop_id", ""), fallback="unknown-stop")
    reason = public_human_stop_text(
        stop.get("reason", ""), fallback="unsupported-required-capability"
    )
    message = public_human_stop_text(
        stop.get("message", ""), fallback="managed execution requires a human decision"
    )
    requested_action = public_human_stop_text(
        stop.get("requested_action", ""),
        fallback="inspect the private run artifacts and resolve the pending pause",
    )
    stage = snapshot.get("stage")
    pending_gates = [stage] if isinstance(stage, str) and stage.strip() else []
    return {
        "status": "human-stop",
        "completed_stages": [],
        "skipped_stages": [],
        "pending_gates": pending_gates,
        "human_stop": {
            "stop_id": stop_id,
            "reason": reason,
            "message": message,
            "requested_action": requested_action,
        },
        "attempts": [],
        "messages": [
            f"pending human stop {stop_id} must be resolved before managed execution resumes"
        ],
    }


@pipeline_app.command(
    "run",
    hidden=not _EXPERIMENTAL,
    help=r"\[Preview] Execute/resume the frozen workflow through one native host adapter.",
)
def pipeline_run(
    provider: Provider = _PIPELINE_PROVIDER_OPTION,
    path: str = typer.Argument(".", help="target project dir (default: .)"),
    condition: Optional[list[str]] = _PIPELINE_CONDITION_OPTION,
    context: str = typer.Option(
        "",
        "--context",
        help="bounded additional context supplied to each pending stage",
    ),
    program_manifest: Optional[Path] = _PIPELINE_PROGRAM_MANIFEST_OPTION,
    wait_timeout_seconds: float = typer.Option(
        900.0,
        "--wait-timeout-seconds",
        min=1.0,
        help="maximum bounded wait for each native worker attempt",
    ),
    json_out: bool = typer.Option(
        False, "--json", help="emit the structured execution result as JSON"
    ),
) -> None:
    """Execute an active managed run until a gate, human stop, failure, or completion.

    The active ledger supplies the objective and mode.  Conditions are explicit and
    frozen on first execution; provider switches resume the same ``.ckit`` ledger.
    Mode E requires ``--program-manifest`` and remains Preview. Reversible,
    contained units can progress; irreversible units stop at the broker boundary.
    """

    if not bool(
        os.environ.get("CKIT_EXPERIMENTAL") or os.environ.get("CLAUDE_KIT_EXPERIMENTAL")
    ):
        typer.echo(
            "error: structured workflow execution is Preview; set CKIT_EXPERIMENTAL=1 and retry",
            err=True,
        )
        raise typer.Exit(2)
    from claude_kit.process_dispatch import DispatchAdapterError
    from claude_kit.workflow_executor import (
        WorkflowExecutionStatus,
        execute_bound_workflow,
    )
    from claude_kit.workflows import WorkflowValidationError

    try:
        decisions = _workflow_conditions(condition)
        snapshot, snapshot_error = pipeline.snapshot_document(path)
        if snapshot_error is not None or snapshot is None:
            raise ValueError(snapshot_error or "no active pipeline run")
        if snapshot.get("status") != "active":
            raise ValueError(
                "structured workflow execution requires an active pipeline run"
            )
        objective = snapshot.get("task")
        mode = snapshot.get("mode")
        if not isinstance(objective, str) or not objective.strip():
            raise ValueError("active pipeline run has no valid task")
        if not isinstance(mode, str) or not mode.strip():
            raise ValueError("active pipeline run has no valid mode")

        document = _pending_workflow_stop_document(snapshot)
        if document is None:
            result = execute_bound_workflow(
                Path(path),
                provider=provider.value,
                objective=objective,
                mode=mode,
                conditions=decisions,
                context=context,
                program_manifest_path=program_manifest,
                wait_timeout_seconds=wait_timeout_seconds,
            )
            document = _workflow_result_document(result)
    except (
        DispatchAdapterError,
        OSError,
        TypeError,
        ValueError,
        WorkflowValidationError,
        WorktreeError,
    ) as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(2) from exc

    if json_out:
        typer.echo(json.dumps(document, sort_keys=True))
    else:
        typer.echo(f"structured workflow: {document['status']}")
        completed = document["completed_stages"]
        skipped = document["skipped_stages"]
        pending = document["pending_gates"]
        typer.echo(
            f"completed={len(completed)} skipped={len(skipped)} attempts={len(document['attempts'])}"
        )
        if pending:
            typer.echo("pending gates: " + ", ".join(pending))
        human_stop = document["human_stop"]
        if isinstance(human_stop, dict):
            typer.echo(
                "human stop: "
                + str(human_stop["reason"])
                + " — "
                + str(human_stop["message"])
            )
            typer.echo("requested action: " + str(human_stop["requested_action"]))
        for attempt in document["attempts"]:
            artifact = attempt.get("artifact")
            if isinstance(artifact, dict):
                typer.echo(
                    "artifact "
                    + str(attempt["stage"])
                    + "#"
                    + str(attempt["attempt"])
                    + ": "
                    + str(artifact["path"])
                    + " sha256="
                    + str(artifact["sha256"])
                    + " category="
                    + str(artifact["category"])
                    + " truncated="
                    + str(artifact["truncated"]).lower()
                )
        for message in document["messages"]:
            typer.echo(str(message))

    if document["status"] == WorkflowExecutionStatus.HUMAN_STOP.value:
        raise typer.Exit(3)
    if document["status"] == WorkflowExecutionStatus.FAILED.value:
        raise typer.Exit(1)


@pipeline_app.command("validate")
def pipeline_validate(
    path: str = typer.Argument(".", help="target project dir (default: .)"),
    json_out: bool = typer.Option(
        False, "--json", help="emit a machine-readable JSON report instead of text"
    ),
    strict: bool = typer.Option(
        False,
        "--strict",
        help="fail (instead of warn) when the install snapshot is missing/unreadable — for CI",
    ),
) -> None:
    """Check the pipeline snapshot's shape, gate/lane coherence, and the gate ledger (no writes).

    Every gate_history entry is re-verified: evidence file present, sha256 unchanged since the
    gate closed, and entries in the installed gate order.
    """
    ok, messages = pipeline.validate(path, strict=strict)
    if json_out:
        snapshot, error = pipeline.snapshot_document(path)
        extra = {"snapshot": snapshot} if error is None else {"snapshot_error": error}
        typer.echo(report.Report.from_lines(ok, messages).to_json(extra=extra))
        if not ok:
            raise typer.Exit(1)
    else:
        _print_report(ok, messages)


@pipeline_app.command("status")
def pipeline_status(
    path: str = typer.Argument(".", help="target project dir (default: .)"),
    json_out: bool = typer.Option(
        False, "--json", help="emit a machine-readable JSON report instead of text"
    ),
) -> None:
    """Print a summary of the current pipeline run (stage, lanes, gate, findings, next)."""
    ok, messages = pipeline.status(path)
    if json_out:
        snapshot, error = pipeline.snapshot_document(path)
        extra = {"snapshot": snapshot} if error is None else {"snapshot_error": error}
        typer.echo(report.Report.from_lines(ok, messages).to_json(extra=extra))
        if not ok:
            raise typer.Exit(1)
    else:
        _print_report(ok, messages)


@pipeline_app.command("start")
def pipeline_start(
    task: str = typer.Option(
        ..., "--task", help="concise identity of the work being run"
    ),
    path: str = typer.Argument(".", help="target project dir (default: .)"),
    mode: str = typer.Option("B", "--mode", help="pipeline mode A, B, C, D, or E"),
) -> None:
    """Start a fresh schema-v2 run at the installed profile's first gate."""
    _print_report(*pipeline.start(path, task=task, mode=mode))


@pipeline_app.command("adopt")
def pipeline_adopt(
    gate: str = typer.Argument(..., help="first gate controlled by the adopted run"),
    task: str = typer.Option(
        ..., "--task", help="concise identity of the work being adopted"
    ),
    reason: str = typer.Option(
        ..., "--reason", help="why preceding gates are historical"
    ),
    adopted_by: str = typer.Option(
        ..., "--adopted-by", help="human or accountable role adopting the work"
    ),
    path: str = typer.Argument(".", help="target project dir (default: .)"),
    mode: str = typer.Option("B", "--mode", help="pipeline mode A, B, C, D, or E"),
) -> None:
    """Explicitly adopt work already in flight and preserve its historical boundary."""
    _print_report(
        *pipeline.adopt(
            path,
            task=task,
            gate=gate,
            reason=reason,
            adopted_by=adopted_by,
            mode=mode,
        )
    )


@pipeline_app.command("resume")
def pipeline_resume(
    path: str = typer.Argument(".", help="target project dir (default: .)"),
) -> None:
    """Validate and resume an active run bound to this repository and branch."""
    _print_report(*pipeline.resume(path))


@pipeline_app.command("reconcile-stale-attempt")
def pipeline_reconcile_stale_attempt(
    stage: str = typer.Argument(..., help="stage with the stale running claim"),
    dispatch_id: str = typer.Option(
        ..., "--dispatch-id", help="exact stale dispatch identifier"
    ),
    reconciled_by: str = typer.Option(
        ..., "--reconciled-by", help="accountable operator performing recovery"
    ),
    evidence: str = typer.Option(
        ...,
        "--evidence",
        help="project-contained operator record proving the coordinator stopped",
    ),
    path: str = typer.Argument(".", help="target project dir (default: .)"),
) -> None:
    """Recover one provably side-effect-free stale Claude stage claim."""

    _print_report(
        *pipeline.reconcile_stale_stage_attempt(
            path,
            stage=stage,
            dispatch_id=dispatch_id,
            reconciled_by=reconciled_by,
            evidence=evidence,
        )
    )


@pipeline_app.command("reconcile-stale-program-attempt", hidden=True)
def pipeline_reconcile_stale_program_attempt(
    unit: str = typer.Argument(..., help="Mode E unit with the stale running claim"),
    dispatch_id: str = typer.Option(
        ..., "--dispatch-id", help="exact stale dispatch identifier"
    ),
    reconciled_by: str = typer.Option(
        ..., "--reconciled-by", help="accountable operator performing recovery"
    ),
    evidence: str = typer.Option(
        ...,
        "--evidence",
        help="project-contained operator record proving the coordinator stopped",
    ),
    path: str = typer.Argument(".", help="target project dir (default: .)"),
) -> None:
    """Recover one unchanged, side-effect-free stale Mode E unit claim."""

    _print_report(
        *pipeline.reconcile_stale_program_attempt(
            path,
            unit_id=unit,
            dispatch_id=dispatch_id,
            reconciled_by=reconciled_by,
            evidence=evidence,
        )
    )


@pipeline_app.command("pause")
def pipeline_pause(
    reason: str = typer.Option(
        ...,
        "--reason",
        help="portable stop reason (for example missing-requirements or external-side-effect)",
    ),
    message: str = typer.Option(..., "--message", help="why autonomous work must stop"),
    requested_action: str = typer.Option(
        ...,
        "--requested-action",
        help="the exact decision or input needed from a human",
    ),
    path: str = typer.Argument(".", help="target project dir (default: .)"),
) -> None:
    """Persist a mandatory provider-neutral human stop on the active run."""

    _print_report(
        *pipeline.pause_for_human(
            path,
            reason=reason,
            message=message,
            requested_action=requested_action,
        )
    )


@pipeline_app.command("resolve-pause")
def pipeline_resolve_pause(
    stop_id: str = typer.Argument(..., help="pending human-stop identifier"),
    decision: str = typer.Option(..., "--decision", help="approved or rejected"),
    resolved_by: str = typer.Option(
        ..., "--resolved-by", help="accountable human making the decision"
    ),
    note: str = typer.Option(..., "--note", help="decision rationale and boundaries"),
    evidence: Optional[str] = typer.Option(
        None,
        "--evidence",
        help="project-contained approval record (required when approved)",
    ),
    path: str = typer.Argument(".", help="target project dir (default: .)"),
) -> None:
    """Resolve a pending stop; approved decisions require hashed local evidence."""

    _print_report(
        *pipeline.resolve_human_stop(
            path,
            stop_id,
            decision=decision,
            resolved_by=resolved_by,
            note=note,
            evidence=evidence,
        )
    )


@pipeline_app.command("record-findings")
def pipeline_record_findings(
    critical: int = typer.Option(
        ..., "--critical", min=0, help="exact open Critical finding count"
    ),
    high: int = typer.Option(
        ..., "--high", min=0, help="exact open High finding count"
    ),
    medium: int = typer.Option(
        ..., "--medium", min=0, help="exact open Medium finding count"
    ),
    low: int = typer.Option(..., "--low", min=0, help="exact open Low finding count"),
    cosmetic: int = typer.Option(
        ..., "--cosmetic", min=0, help="exact open Cosmetic finding count"
    ),
    evidence: str = typer.Option(
        ...,
        "--evidence",
        help="project-contained evidence artifact for this exact finding set",
    ),
    path: str = typer.Argument(".", help="target project dir (default: .)"),
) -> None:
    """Atomically record exact finding counts bound to current HEAD and evidence."""
    _print_report(
        *pipeline.record_findings(
            path,
            critical=critical,
            high=high,
            medium=medium,
            low=low,
            cosmetic=cosmetic,
            evidence=evidence,
        )
    )


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
        help="compatibility flag for repair tooling; never waives a finding or gate order",
    ),
    override_reason: Optional[str] = typer.Option(
        None,
        "--override-reason",
        help="repair/migration note; does not authorize a gate bypass",
    ),
    strict: bool = typer.Option(
        False,
        "--strict",
        help="fail (instead of warn) when the install snapshot is missing/unreadable — for CI",
    ),
) -> None:
    """Record a quality gate as passed, with an evidence file, in the pipeline gate ledger.

    Appends to gate_history with the evidence sha256, repository commit, and timestamp. Critical
    and High findings are never waivable; Medium uses the distinct accept-risk transition. The
    compatibility --force option cannot override a finding or gate order.
    """
    _print_report(
        *pipeline.close_gate(
            path,
            gate,
            evidence,
            force=force,
            override_reason=override_reason,
            strict=strict,
        )
    )


@pipeline_app.command("skip-gate")
def pipeline_skip_gate(
    gate: str = typer.Argument(
        ..., help="gate token to record as deliberately skipped (e.g. contract-clear)"
    ),
    reason: str = typer.Option(
        ..., "--reason", help="why this conditional gate does not apply to the run"
    ),
    condition: str = typer.Option(
        ..., "--condition", help="configured machine-readable skip condition identifier"
    ),
    evidence: str = typer.Option(
        ...,
        "--evidence",
        help="evidence proving that the condition holds at current HEAD",
    ),
    path: str = typer.Argument(".", help="target project dir (default: .)"),
    strict: bool = typer.Option(
        False,
        "--strict",
        help="fail (instead of warn) when the install snapshot is missing/unreadable — for CI",
    ),
) -> None:
    """Compatibility alias that records the structured status ``not-applicable``."""
    _print_report(
        *pipeline.skip_gate(
            path,
            gate,
            reason,
            condition=condition,
            evidence=evidence,
            strict=strict,
        )
    )


@pipeline_app.command("not-applicable")
def pipeline_not_applicable(
    gate: str = typer.Argument(..., help="conditional gate to resolve"),
    condition: str = typer.Option(
        ..., "--condition", help="configured condition identifier"
    ),
    reason: str = typer.Option(..., "--reason", help="why the condition applies"),
    evidence: str = typer.Option(
        ..., "--evidence", help="evidence proving the condition"
    ),
    path: str = typer.Argument(".", help="target project dir (default: .)"),
) -> None:
    """Resolve the next conditional gate as not applicable, never as an ordinary pass."""
    _print_report(
        *pipeline.not_applicable(
            path, gate, condition=condition, reason=reason, evidence=evidence
        )
    )


@pipeline_app.command("accept-risk")
def pipeline_accept_risk(
    gate: str = typer.Argument(..., help="gate affected by the Medium finding"),
    finding_id: str = typer.Option(
        ..., "--finding-id", help="stable Medium finding identifier"
    ),
    reason: str = typer.Option(
        ..., "--reason", help="why this Medium risk is accepted"
    ),
    accepted_by: str = typer.Option(
        ..., "--accepted-by", help="accepting human or accountable role"
    ),
    owner: str = typer.Option(
        ..., "--owner", help="owner responsible for the residual risk"
    ),
    ticket: str = typer.Option(..., "--ticket", help="issue or ticket reference"),
    revisit: str = typer.Option(..., "--revisit", help="expiry or revisit trigger"),
    evidence: str = typer.Option(..., "--evidence", help="finding evidence artifact"),
    compensating_control: Optional[str] = typer.Option(
        None, "--compensating-control", help="control that bounds the residual risk"
    ),
    refresh: bool = typer.Option(
        False,
        "--refresh",
        help="explicitly re-attest an existing stale acceptance at the current commit",
    ),
    supersedes_finding_id: Optional[str] = typer.Option(
        None,
        "--supersedes-finding-id",
        help="prior finding ID replaced by --finding-id during a refresh",
    ),
    path: str = typer.Argument(".", help="target project dir (default: .)"),
) -> None:
    """Record a structured Medium acceptance; never represents an ordinary PASS."""
    _print_report(
        *pipeline.accept_risk(
            path,
            gate,
            finding_id=finding_id,
            reason=reason,
            accepted_by=accepted_by,
            owner=owner,
            ticket=ticket,
            revisit=revisit,
            evidence=evidence,
            compensating_control=compensating_control,
            refresh=refresh,
            supersedes_finding_id=supersedes_finding_id,
        )
    )


@pipeline_app.command("complete")
def pipeline_complete(
    path: str = typer.Argument(".", help="target project dir (default: .)"),
) -> None:
    """Complete a coherent run after every active gate is explicitly resolved."""
    _print_report(*pipeline.complete(path))


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
