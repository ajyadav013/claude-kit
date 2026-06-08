"""Scaffolding logic for claude-kit.

Copies the bundled payload (``claude_kit/_payload``) — rules, agents, skills, hooks, and
templates — into a target project's ``.claude/`` directory, and writes a generic ``CLAUDE.md``
to the project root. This mirrors ``scripts/init.sh`` (used by the ``/claude-kit:init`` plugin
command) so both install channels behave identically.
"""

from __future__ import annotations

import shutil
from contextlib import ExitStack
from importlib.resources import as_file, files
from pathlib import Path


def payload_dir(stack: ExitStack) -> Path:
    """Return a real filesystem path to the bundled payload directory.

    Args:
        stack: An ``ExitStack`` that keeps any temporary extraction alive for the caller's
            scope (needed when the package is imported from a zip).

    Returns:
        Path to the ``_payload`` directory containing rules/agents/skills/hooks/templates.

    Raises:
        FileNotFoundError: If the payload is missing from the installed package.
    """
    resource = files("claude_kit").joinpath("_payload")
    path = Path(stack.enter_context(as_file(resource)))
    if not path.is_dir():
        raise FileNotFoundError(
            "claude-kit payload not found — the package was built without its data files."
        )
    return path


def _copy_tree(src: Path, dest: Path) -> None:
    """Replace ``dest`` with a copy of ``src`` (directory)."""
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(src, dest)


def _copy_root_file(
    src: Path, dest: Path, *, force: bool, log: list[str], label: str
) -> None:
    """Copy a single file to the project root, never clobbering unless ``force``."""
    if dest.exists() and not force:
        sidecar = dest.with_name(dest.name + ".claude-kit")
        shutil.copy2(src, sidecar)
        log.append(
            f"  • {label} exists — wrote {sidecar.name} (use --force to overwrite)"
        )
    else:
        shutil.copy2(src, dest)
        log.append(f"  • {label} installed")


def init(
    target: str | Path,
    *,
    force: bool = False,
    minimal: bool = False,
    no_hooks: bool = False,
) -> list[str]:
    """Scaffold claude-kit into ``target``.

    Args:
        target: Project directory to scaffold into.
        force: Overwrite an existing ``CLAUDE.md`` / ``settings.json`` instead of writing a sidecar.
        minimal: Install only ``CLAUDE.md`` and ``rules/`` (skip agents, skills, hooks, memory).
        no_hooks: Skip hook scripts and ``settings.json``.

    Returns:
        A list of human-readable log lines describing what was installed.
    """
    target = Path(target).expanduser().resolve()
    dest = target / ".claude"
    dest.mkdir(parents=True, exist_ok=True)
    log: list[str] = [f"claude-kit: scaffolding into {target}"]

    with ExitStack() as stack:
        src = payload_dir(stack)

        # Always installed: rules, the generic CLAUDE.md, and the continuity template.
        _copy_tree(src / "rules", dest / "rules")
        log.append(f"  • rules/ ({_count(dest / 'rules', '*.md')} files)")
        _copy_root_file(
            src / "templates" / "CLAUDE.md",
            target / "CLAUDE.md",
            force=force,
            log=log,
            label="CLAUDE.md",
        )
        shutil.copy2(
            src / "templates" / "CONTINUITY.template.md",
            dest / "CONTINUITY.template.md",
        )

        if not minimal:
            _copy_tree(src / "agents", dest / "agents")
            log.append(f"  • agents/ ({_count(dest / 'agents', '*.md')} files)")
            _copy_tree(src / "skills", dest / "skills")
            log.append(f"  • skills/ ({_count_dirs(dest / 'skills')} skills)")
            if not (dest / "agent-memory").exists():
                _copy_tree(src / "templates" / "agent-memory", dest / "agent-memory")
                log.append("  • agent-memory/ seed")

        if not minimal and not no_hooks:
            hooks_dest = dest / "hooks"
            hooks_dest.mkdir(parents=True, exist_ok=True)
            for script in (src / "hooks" / "scripts").glob("*.sh"):
                shutil.copy2(script, hooks_dest / script.name)
                (hooks_dest / script.name).chmod(0o755)
            log.append(f"  • hooks/ ({_count(hooks_dest, '*.sh')} scripts)")
            _copy_root_file(
                src / "templates" / "settings.json",
                dest / "settings.json",
                force=force,
                log=log,
                label="settings.json",
            )

    log.append(
        "claude-kit: done. Open the project in Claude Code; CLAUDE.md and .claude/ are now active."
    )
    return log


def upgrade(target: str | Path) -> list[str]:
    """Refresh the kit-owned payload (rules, agents, skills, hooks) without touching user files.

    Leaves ``CLAUDE.md``, ``settings.json``, ``CONTINUITY.md``, and ``agent-memory/`` untouched.

    Args:
        target: Project directory containing a ``.claude/`` to upgrade.

    Returns:
        Log lines describing what was refreshed.
    """
    target = Path(target).expanduser().resolve()
    dest = target / ".claude"
    if not dest.is_dir():
        return [
            f"claude-kit: no .claude/ found in {target} — run `claude-kit init` first."
        ]
    log = [f"claude-kit: upgrading payload in {target}"]
    with ExitStack() as stack:
        src = payload_dir(stack)
        _copy_tree(src / "rules", dest / "rules")
        _copy_tree(src / "agents", dest / "agents")
        _copy_tree(src / "skills", dest / "skills")
        hooks_dest = dest / "hooks"
        hooks_dest.mkdir(parents=True, exist_ok=True)
        for script in (src / "hooks" / "scripts").glob("*.sh"):
            shutil.copy2(script, hooks_dest / script.name)
            (hooks_dest / script.name).chmod(0o755)
    log.append(
        "  • refreshed rules/, agents/, skills/, hooks/ (user CLAUDE.md & settings.json left intact)"
    )
    return log


def inventory() -> dict[str, list[str]]:
    """Return the names of the agents, rules, and skills bundled in the kit.

    Returns:
        A mapping with keys ``agents``, ``rules``, and ``skills`` to sorted name lists.
    """
    with ExitStack() as stack:
        src = payload_dir(stack)
        return {
            "agents": sorted(p.stem for p in (src / "agents").glob("*.md")),
            "rules": sorted(p.stem for p in (src / "rules").glob("*.md")),
            "skills": sorted(p.name for p in (src / "skills").iterdir() if p.is_dir()),
        }


def _count(directory: Path, pattern: str) -> int:
    """Count files in ``directory`` matching ``pattern``."""
    return sum(1 for _ in directory.glob(pattern)) if directory.is_dir() else 0


def _count_dirs(directory: Path) -> int:
    """Count immediate subdirectories of ``directory``."""
    return (
        sum(1 for p in directory.iterdir() if p.is_dir()) if directory.is_dir() else 0
    )
