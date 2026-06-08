"""Project generator for claude-kit (the ``claude-kit new`` command).

Generates a batteries-included monorepo from the **stack registry** under
``templates/stacks/`` and installs the claude-kit SDLC config, tuned to the chosen stack:

1. Render shared monorepo glue (``stacks/project/files/``) into the project root.
2. Render the chosen backend stack (``stacks/backend/<id>/files/``) into ``backend/``.
3. Render the chosen frontend stack (``stacks/frontend/<id>/files/``) into ``frontend/``.
4. Install the SDLC config (``.claude/`` + ``CLAUDE.md``) via :func:`claude_kit.scaffold.install_sdlc`.
5. Copy each chosen stack's overlay rule(s) (e.g. ``fastapi-patterns.md``) into ``.claude/rules/``.
6. Replace the ``## Project-specific rules`` placeholder in ``CLAUDE.md`` with a rendered, stack-aware
   block (exact commands, directory layout, overlay-rule pointers).

Stacks are pure data: each ``stacks/<kind>/<id>/`` directory carries a ``stack.json`` describing it.
Adding a stack is a new folder — never a code change. The generator works from any payload root, so
it serves both the pip CLI (``_payload``) and the plugin (``${CLAUDE_PLUGIN_ROOT}``).
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

from claude_kit import scaffold
from claude_kit.render import render_text, render_tree

#: Marker in the generic CLAUDE.md whose section is replaced with the stack-specific block.
_STACK_MARKER = "## Project-specific rules"


def stacks_root(payload_root: Path) -> Path:
    """Return the stack-registry directory for a payload root."""
    return Path(payload_root) / "templates" / "stacks"


def load_stack(payload_root: Path, kind: str, stack_id: str) -> dict:
    """Load and validate a single stack's ``stack.json``.

    Args:
        payload_root: Payload root containing ``templates/stacks``.
        kind: ``"backend"`` or ``"frontend"``.
        stack_id: The stack directory name (e.g. ``"python-fastapi"``).

    Returns:
        The parsed ``stack.json`` mapping, with ``id`` guaranteed present.

    Raises:
        FileNotFoundError: If the stack directory or its ``stack.json`` is missing.
    """
    stack_dir = stacks_root(payload_root) / kind / stack_id
    meta = stack_dir / "stack.json"
    if not meta.is_file():
        raise FileNotFoundError(f"unknown {kind} stack {stack_id!r} (no {meta} found)")
    data = json.loads(meta.read_text(encoding="utf-8"))
    data.setdefault("id", stack_id)
    return data


def list_stacks(payload_root: Path, kind: str) -> list[dict]:
    """List the registered stacks of a given kind, sorted by id.

    Args:
        payload_root: Payload root containing ``templates/stacks``.
        kind: ``"backend"`` or ``"frontend"``.

    Returns:
        A list of ``stack.json`` mappings (empty if the registry dir is absent).
    """
    base = stacks_root(payload_root) / kind
    if not base.is_dir():
        return []
    out: list[dict] = []
    for child in sorted(base.iterdir()):
        if child.is_dir() and (child / "stack.json").is_file():
            out.append(load_stack(payload_root, kind, child.name))
    return out


def slugify(name: str) -> str:
    """Convert a project name to a lowercase kebab-case slug.

    Args:
        name: Human-entered project name.

    Returns:
        A filesystem/package-safe kebab-case slug (falls back to ``"app"`` if empty).
    """
    slug = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    return slug or "app"


def build_context(
    project_name: str,
    backend: dict,
    frontend: dict,
    db: str,
) -> dict[str, str]:
    """Assemble the substitution context for the templates.

    Merges project identity, networking/database defaults, and per-stack metadata (prefixed
    ``backend_*`` / ``frontend_*``) drawn from each ``stack.json``.

    Args:
        project_name: Human-entered project name.
        backend: The backend ``stack.json`` mapping.
        frontend: The frontend ``stack.json`` mapping.
        db: Database identifier (currently ``"postgres"``).

    Returns:
        A flat ``str -> str`` mapping consumed by the renderer.
    """
    slug = slugify(project_name)
    snake = slug.replace("-", "_")
    ctx: dict[str, str] = {
        "project_name": project_name,
        "project_slug": slug,
        "project_snake": snake,
        "db": db,
        "db_name": f"{snake}",
        "db_user": "app",
        "db_password": "app",
        "db_host": "db",
        "db_port": "5432",
        "api_port": "8000",
        "web_port": "5173",
        "backend_id": str(backend.get("id", "")),
        "frontend_id": str(frontend.get("id", "")),
    }
    for key, value in backend.items():
        ctx[f"backend_{key}"] = str(value)
    for key, value in frontend.items():
        ctx[f"frontend_{key}"] = str(value)
    return ctx


def _inject_stack_block(
    claude_md: Path, block_tmpl: Path, context: dict[str, str]
) -> None:
    """Replace the ``## Project-specific rules`` section of ``claude_md`` with a rendered block."""
    if not block_tmpl.is_file():
        return
    block = render_text(block_tmpl.read_text(encoding="utf-8"), context).rstrip() + "\n"
    text = claude_md.read_text(encoding="utf-8")
    idx = text.find(_STACK_MARKER)
    if idx != -1:
        text = text[:idx].rstrip() + "\n\n" + block
    else:
        text = text.rstrip() + "\n\n" + block
    claude_md.write_text(text, encoding="utf-8")


def _copy_overlay_rules(stack_dir: Path, rules_dest: Path, log: list[str]) -> None:
    """Copy a stack's overlay rule files into the project's ``.claude/rules``."""
    rules_dir = stack_dir / "rules"
    if not rules_dir.is_dir():
        return
    rules_dest.mkdir(parents=True, exist_ok=True)
    for rule in sorted(rules_dir.glob("*.md")):
        shutil.copy2(rule, rules_dest / rule.name)
        log.append(f"  • overlay rule: .claude/rules/{rule.name}")


def generate(
    payload_root: str | Path,
    target: str | Path,
    *,
    project_name: str,
    backend_id: str,
    frontend_id: str,
    db: str = "postgres",
    force: bool = False,
    here: bool = False,
) -> list[str]:
    """Generate a new project from the stack registry into ``target``.

    Args:
        payload_root: Path to the payload (``_payload`` for pip, repo root for the plugin).
        target: Destination project directory.
        project_name: Human-entered project name (drives slugs and template substitution).
        backend_id: Backend stack id (must exist under ``stacks/backend/``).
        frontend_id: Frontend stack id (must exist under ``stacks/frontend/``).
        db: Database identifier.
        force: Allow generating into a non-empty directory (overwrites colliding files).
        here: Treat ``target`` as the project root directly (allow generating into the cwd).

    Returns:
        Human-readable log lines describing what was generated.

    Raises:
        FileExistsError: If ``target`` is non-empty and neither ``force`` nor ``here`` is set.
        FileNotFoundError: If a chosen stack or the project template is missing.
    """
    payload_root = Path(payload_root)
    target = Path(target).expanduser().resolve()
    stacks = stacks_root(payload_root)

    if target.exists() and any(target.iterdir()) and not (force or here):
        raise FileExistsError(
            f"{target} is not empty — pass --force to generate into it anyway, or --here."
        )
    target.mkdir(parents=True, exist_ok=True)

    backend = load_stack(payload_root, "backend", backend_id)
    frontend = load_stack(payload_root, "frontend", frontend_id)
    context = build_context(project_name, backend, frontend, db)

    log: list[str] = [f"claude-kit: generating {project_name} into {target}"]
    log.append(f"  • backend: {backend.get('label', backend_id)}")
    log.append(f"  • frontend: {frontend.get('label', frontend_id)}")

    # 1) Monorepo glue at the project root.
    render_tree(stacks / "project" / "files", target, context)
    log.append("  • project glue (compose, Makefile, README, env)")

    # 2) Backend + 3) frontend stacks.
    render_tree(stacks / "backend" / backend_id / "files", target / "backend", context)
    log.append("  • backend/ generated")
    render_tree(
        stacks / "frontend" / frontend_id / "files", target / "frontend", context
    )
    log.append("  • frontend/ generated")

    # 4) SDLC config (.claude/ + CLAUDE.md). force=True: this is a fresh project, nothing to guard.
    scaffold.install_sdlc(payload_root, target, force=True, log=log)

    # 5) Stack overlay rules into .claude/rules/.
    rules_dest = target / ".claude" / "rules"
    _copy_overlay_rules(stacks / "backend" / backend_id, rules_dest, log)
    _copy_overlay_rules(stacks / "frontend" / frontend_id, rules_dest, log)

    # 6) Fill the CLAUDE.md "Project-specific rules" section with the concrete stack.
    _inject_stack_block(
        target / "CLAUDE.md", stacks / "project" / "CLAUDE.stack.md.tmpl", context
    )
    log.append("  • CLAUDE.md tuned to the selected stack")

    log.append("claude-kit: done. See the generated README.md to run it.")
    return log
