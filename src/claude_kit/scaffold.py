"""Installer — writes a resolved claude-kit configuration into a target project.

Given a :class:`~claude_kit.models.ResolvedPlan` (from :func:`claude_kit.catalog.resolve`), this
module copies the profile's agent/skill/hook **subset**, the core rules, the selected stack
**overlay** rules + agents, assembles ``.claude/settings.json`` from the chosen hooks, optionally
writes ``.mcp.json``, installs artifact templates and a tuned ``CLAUDE.md`` + ``README.claude-sdlc.md``
+ a root ``AGENTS.md`` (the export projection, for non-Claude agents), creates gitignored runtime
dirs, and records per-file checksums in ``.claude/config/init-options.json`` for safe upgrades. It writes **no application code and no Docker** — configuration only.

``install_sdlc`` is the single spine used by the pip CLI and the plugin's compatibility launcher.
"""

from __future__ import annotations

import hashlib
import json
import tempfile
from contextlib import ExitStack
from copy import deepcopy
from importlib.resources import as_file, files
from pathlib import Path, PurePosixPath
from typing import Any, NamedTuple

import yaml

from claude_kit import __version__, detect
from claude_kit import hooks as hooks_mod
from claude_kit.mcp import project_resolved_servers as project_mcp_servers
from claude_kit.models import FileRecord, InitOptions, ResolvedPlan, StateLayout
from claude_kit.render import _is_ignored as _is_payload_junk
from claude_kit.render import render_text
from claude_kit.secure_fs import (
    ProjectFS,
    ProjectTransaction,
    UnsafePathError,
    normalize_relative_path,
)

#: Marker in the generic CLAUDE.md whose section is replaced with the stack-specific block.
_STACK_MARKER = "## Project-specific rules"
_LEGACY_STATE_LAYOUT = StateLayout.legacy_claude()
_LEGACY_CONFIG_ROOT = PurePosixPath(_LEGACY_STATE_LAYOUT.manifest).parent.as_posix()
_LEGACY_MEMORY_PREFIX = _LEGACY_STATE_LAYOUT.memory.rstrip("/") + "/"
_LEGACY_JOURNAL_IN_ROOT = (
    PurePosixPath(_LEGACY_STATE_LAYOUT.journal)
    .relative_to(_LEGACY_STATE_LAYOUT.root)
    .as_posix()
)

#: Selective .gitignore entries for a scaffolded project (commit the rest of .claude/).
GITIGNORE_ENTRIES = (
    ".claude/settings.local.json",
    "CLAUDE.local.md",
    f"{_LEGACY_STATE_LAYOUT.state}/",
    f"{_LEGACY_STATE_LAYOUT.temporary}/",
    # upgrade/merge artifacts written by `claude-kit upgrade` — never commit these
    ".claude-kit.bak-*/",
    ".claude.bak-*/",
    ".claude-kit-txn-*/",
    "*.claude-kit",
    _LEGACY_STATE_LAYOUT.journal,
)


def payload_dir(stack: ExitStack) -> Path:
    """Return a real filesystem path to the bundled payload directory.

    Resolution order: (1) the bundled ``claude_kit/_payload`` (installed/built package); (2) the
    repository root (two levels above this file) when running from a source checkout.

    Args:
        stack: An ``ExitStack`` keeping any temporary extraction alive for the caller's scope.

    Returns:
        Path to the payload root containing ``rules/ agents/ skills/ hooks/ templates/ catalog/``.

    Raises:
        FileNotFoundError: If no payload can be located by either route.
    """
    try:
        resource = files("claude_kit").joinpath("_payload")
        path = Path(stack.enter_context(as_file(resource)))
        if path.is_dir():
            return path
    except (FileNotFoundError, ModuleNotFoundError, NotADirectoryError):
        pass

    repo_root = Path(__file__).resolve().parents[2]
    if (repo_root / "rules").is_dir() and (repo_root / "catalog").is_dir():
        return repo_root

    raise FileNotFoundError(
        "claude-kit payload not found — the package was built without its data files."
    )


# --- small fs helpers ------------------------------------------------------------------------------


class _Rescue(NamedTuple):
    """Where to preserve user files a directory-replacing install would otherwise delete.

    Attributes:
        root: The ``.claude-kit.bak-N/`` directory (created lazily, on the first rescue).
        target: Project root, used to mirror each rescued file's project-relative path.
    """

    root: Path
    target: Path


def next_backup_dir(target: Path) -> Path:
    """Return a fresh, non-existing ``.claude-kit.bak-N/`` directory under ``target``."""
    fs = ProjectFS(target)
    n = 1
    while fs.exists(f".claude-kit.bak-{n}"):
        n += 1
    return fs.path(f".claude-kit.bak-{n}")


def _rescue_extraneous(
    src: Path,
    dest: Path,
    rescue: _Rescue | None,
    also_shipped: frozenset[str],
    fs: ProjectFS,
) -> list[Path]:
    """Move files in ``dest`` that this install will not rewrite into the rescue directory.

    ``_copy_tree`` replaces a whole directory, which is right for kit-owned trees but would also
    take anything the user added to them — a hand-written ``.claude/rules/team-conventions.md``, an
    extra artifact template. Those files are not tracked in ``init-options.json`` (the kit never
    wrote them), so no other safety net covers them. Moving them aside preserves the clean-replace
    semantics for kit content while making the operation recoverable.

    Args:
        src: The reference tree about to be copied over ``dest``.
        dest: The live directory being replaced.
        rescue: Where to move rescued files, and the project root to mirror paths against.
            ``None`` disables rescue (used when ``dest`` is a throwaway render sandbox, where
            every file is kit-written by definition).
        also_shipped: Names the *caller* writes into ``dest`` after the replace — overlay and org
            rules land in ``.claude/rules/`` one file at a time, after the core tree is copied, so
            without this they would look like user additions on every re-install.

    Returns:
        The rescued paths, relative to ``dest``, for the caller to log.
    """
    dest_rel = fs.relpath(dest)
    if rescue is None or not fs.is_dir(dest_rel):
        return []
    fs.assert_tree_safe(dest_rel)
    rescued: list[Path] = []
    for live in sorted(dest.rglob("*")):
        if not live.is_file():
            continue
        rel = live.relative_to(dest)
        if (
            (src / rel).is_file() and not _is_payload_junk(rel)
        ) or rel.as_posix() in also_shipped:
            continue  # this install rewrites the path — a normal refresh, not a loss
        # Mirror the project-relative path so a rescued file is unambiguous, matching the layout
        # `upgrade` already uses for .claude-kit.bak-N/.
        try:
            keep = rescue.root / dest.relative_to(rescue.target) / rel
        except ValueError:  # pragma: no cover - dest is always under target in practice
            keep = rescue.root / dest.name / rel
        fs.move(fs.relpath(live), fs.relpath(keep))
        rescued.append(rel)
    return rescued


def _copy_tree(
    src: Path,
    dest: Path,
    *,
    fs: ProjectFS,
    rescue: _Rescue | None = None,
    log: list[str] | None = None,
    also_shipped: frozenset[str] = frozenset(),
) -> None:
    """Replace ``dest`` with a copy of ``src`` (directory), rescuing files this install won't rewrite.

    Args:
        src: Reference directory to copy.
        dest: Directory to replace.
        rescue: When set, files unique to ``dest`` are moved there instead of being deleted.
        log: Optional install log to append a line to when anything was rescued.
        also_shipped: Paths (relative to ``dest``) the caller writes after the replace.
    """
    dest_rel = fs.relpath(dest)
    rescued = _rescue_extraneous(src, dest, rescue, also_shipped, fs)
    if fs.exists(dest_rel):
        fs.remove_tree(dest_rel)
    fs.copy_tree(src, dest_rel, ignore=_is_payload_junk)
    if rescued and log is not None and rescue is not None:
        shown = ", ".join(str(r) for r in rescued[:3])
        more = f" (+{len(rescued) - 3} more)" if len(rescued) > 3 else ""
        where = rescue.root.name
        log.append(f"  • kept your {dest.name}/ additions -> {where}/: {shown}{more}")


def _copy_user_file(
    src: Path,
    dest: Path,
    *,
    fs: ProjectFS,
    force: bool,
    log: list[str],
    label: str,
) -> None:
    """Copy a user-editable file, writing a ``.claude-kit`` sidecar instead of clobbering edits.

    An existing file that already matches byte-for-byte is reported as current — a re-run over an
    unedited install stays quiet instead of littering sidecars.
    """
    rel = fs.relpath(dest)
    if fs.is_file(rel) and not force:
        if fs.read_bytes(rel) == src.read_bytes():
            log.append(f"  • {label} already current")
            return
        sidecar = dest.with_name(dest.name + ".claude-kit")
        fs.copy_file(src, fs.relpath(sidecar))
        log.append(
            f"  • {label} exists — wrote {sidecar.name} (use --force to overwrite)"
        )
    else:
        fs.copy_file(src, rel)
        log.append(f"  • {label} installed")


def _write_user_text(
    dest: Path,
    text: str,
    *,
    fs: ProjectFS,
    force: bool,
    log: list[str],
    label: str,
) -> None:
    """Write rendered text to a user-editable file, sidecar'ing instead of clobbering edits.

    An existing file that already matches byte-for-byte is reported as current — a re-run over an
    unedited install stays quiet instead of littering sidecars.
    """
    rel = fs.relpath(dest)
    if fs.is_file(rel) and not force:
        try:
            current: str | None = fs.read_text(rel)
        except UnicodeDecodeError:
            current = None
        if current == text:
            log.append(f"  • {label} already current")
            return
        sidecar = dest.with_name(dest.name + ".claude-kit")
        fs.write_text(fs.relpath(sidecar), text)
        log.append(
            f"  • {label} exists — wrote {sidecar.name} (use --force to overwrite)"
        )
    else:
        fs.write_text(rel, text)
        log.append(f"  • {label} installed")


def _sha256(path: Path) -> str:
    """Return the hex SHA-256 of a file's bytes."""
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def _find_overlay(
    src: Path, stack_dirs: dict[str, str], kind_dir: str, name: str
) -> Path | None:
    """Locate an overlay file (``rules`` or ``agents``) by name across the selected stack dirs."""
    stacks = src / "templates" / "stacks"
    for stack_dir in stack_dirs.values():
        if not stack_dir:
            continue
        safe_stack = normalize_relative_path(stack_dir)
        safe_kind = normalize_relative_path(kind_dir)
        safe_name = normalize_relative_path(name)
        candidate = stacks / safe_stack / safe_kind / safe_name
        if candidate.is_file():
            return candidate
    return None


# --- install steps ---------------------------------------------------------------------------------


def _install_rules(
    src: Path,
    dest: Path,
    plan: ResolvedPlan,
    log: list[str],
    fs: ProjectFS,
    rescue: _Rescue | None = None,
) -> None:
    """Install all core rules plus the selected overlay rules into ``.claude/rules/``."""
    rules_dest = dest / "rules"
    # Overlay rules (and org rules, installed later by _install_org) are written into this same
    # directory file-by-file after the core tree is replaced. Declaring them keeps a re-install
    # from mistaking last run's overlay rules for the user's own additions.
    later = set(plan.overlay_rules)
    if plan.org is not None:
        later |= set(plan.org.org_rules)
    _copy_tree(
        src / "rules",
        rules_dest,
        fs=fs,
        rescue=rescue,
        log=log,
        also_shipped=frozenset(later),
    )
    log.append(f"  • rules/ ({sum(1 for _ in rules_dest.glob('*.md'))} core)")
    for name in plan.overlay_rules:
        found = _find_overlay(src, plan.stack_dirs, "rules", name)
        if found is None:  # protected by _preflight_plan
            raise FileNotFoundError(f"selected overlay rule missing: {name}")
        fs.copy_file(found, fs.relpath(rules_dest / name))
        log.append(f"  • overlay rule: rules/{name}")


def _install_agents(
    src: Path, dest: Path, plan: ResolvedPlan, log: list[str], fs: ProjectFS
) -> None:
    """Install the profile's core-agent subset plus selected overlay agents into ``.claude/agents/``."""
    agents_dest = dest / "agents"
    fs.mkdir(fs.relpath(agents_dest))
    installed = 0
    for name in plan.agents:
        srcf = src / "agents" / f"{name}.md"
        if not srcf.is_file():  # protected by _preflight_plan
            raise FileNotFoundError(f"selected agent missing: {name}")
        fs.copy_file(srcf, fs.relpath(agents_dest / f"{name}.md"))
        installed += 1
    log.append(f"  • agents/ ({installed} of {len(plan.agents)} selected)")
    for name in plan.overlay_agents:
        found = _find_overlay(src, plan.stack_dirs, "agents", f"{name}.md")
        if found is None:  # protected by _preflight_plan
            raise FileNotFoundError(f"selected overlay agent missing: {name}")
        fs.copy_file(found, fs.relpath(agents_dest / f"{name}.md"))
        log.append(f"  • overlay agent: agents/{name}.md")


def _install_skills(
    src: Path,
    dest: Path,
    plan: ResolvedPlan,
    log: list[str],
    fs: ProjectFS,
    rescue: _Rescue | None = None,
) -> None:
    """Install the profile's skill subset into ``.claude/skills/``."""
    skills_dest = dest / "skills"
    fs.mkdir(fs.relpath(skills_dest))
    installed = 0
    for name in plan.skills:
        srcd = src / "skills" / name
        if not (srcd / "SKILL.md").is_file():  # protected by _preflight_plan
            raise FileNotFoundError(f"selected skill missing: {name}")
        _copy_tree(srcd, skills_dest / name, fs=fs, rescue=rescue, log=log)
        installed += 1
    log.append(f"  • skills/ ({installed} of {len(plan.skills)} selected)")
    # _references/ is shared support content (not a profile-selected skill), but several SKILL.md
    # files link into .claude/skills/_references/…; copy it so those "See Also" links resolve.
    refs_src = src / "skills" / "_references"
    if refs_src.is_dir():
        _copy_tree(refs_src, skills_dest / "_references", fs=fs, rescue=rescue, log=log)
        log.append("  • skills/_references/ (shared deep-dive references)")


def _install_org(
    src: Path,
    dest: Path,
    plan: ResolvedPlan,
    log: list[str],
    fs: ProjectFS,
    rescue: _Rescue | None = None,
) -> None:
    """Install the org capability layer (only when ``plan.org`` is present — organization scope).

    The new skills/agents/rules install into the standard auto-discovered ``.claude/`` dirs (so Claude
    Code picks them up like any other component); the pack manifests install under ``.claude/org-packs/``
    as a governance/catalog layer that *references* the active components.
    """
    org = plan.org
    if org is None:
        return
    org_src = src / "templates" / "org"

    for name in org.org_skills:
        srcd = org_src / "skills" / name
        if not (srcd / "SKILL.md").is_file():  # protected by _preflight_plan
            raise FileNotFoundError(f"selected org skill missing: {name}")
        _copy_tree(srcd, dest / "skills" / name, fs=fs, rescue=rescue, log=log)
    for name in org.org_agents:
        srcf = org_src / "agents" / f"{name}.md"
        if not srcf.is_file():  # protected by _preflight_plan
            raise FileNotFoundError(f"selected org agent missing: {name}")
        fs.copy_file(srcf, fs.relpath(dest / "agents" / f"{name}.md"))
    for name in org.org_rules:
        srcf = org_src / "rules" / name
        if not srcf.is_file():  # protected by _preflight_plan
            raise FileNotFoundError(f"selected org rule missing: {name}")
        fs.copy_file(srcf, fs.relpath(dest / "rules" / name))
    log.append(
        f"  • org layer: {len(org.org_skills)} skills, {len(org.org_agents)} persona agents, "
        f"{len(org.org_rules)} rules (autonomy={org.autonomy})"
    )

    if org.packs:
        packs_dest = dest / "org-packs"
        fs.mkdir(fs.relpath(packs_dest))
        index = org_src / "README.md"
        if index.is_file():
            fs.copy_file(index, fs.relpath(packs_dest / "README.md"))
        installed = 0
        for pack in org.packs:
            srcd = org_src / "packs" / pack
            if not (srcd / "pack.yaml").is_file():  # protected by _preflight_plan
                raise FileNotFoundError(f"selected org pack missing: {pack}")
            _copy_tree(srcd, packs_dest / pack, fs=fs, rescue=rescue, log=log)
            installed += 1
        log.append(f"  • org-packs/ ({installed} pack manifests)")


def _install_hooks_and_settings(
    src: Path,
    dest: Path,
    plan: ResolvedPlan,
    *,
    fs: ProjectFS,
    force: bool,
    log: list[str],
) -> None:
    """Copy the scripts needed by selected hooks and assemble ``.claude/settings.json``."""
    hooks_dest = dest / "hooks"
    fs.mkdir(fs.relpath(hooks_dest))
    for script in hooks_mod.scripts_for(plan.hooks):
        srcf = src / "hooks" / "scripts" / script
        if not srcf.is_file():  # protected by _preflight_plan
            raise FileNotFoundError(f"selected hook script missing: {script}")
        script_rel = fs.relpath(hooks_dest / script)
        fs.copy_file(srcf, script_rel)
        fs.chmod(script_rel, 0o755)
    log.append(f"  • hooks/ ({sum(1 for _ in hooks_dest.glob('*.sh'))} scripts)")
    settings = hooks_mod.build_settings(plan.hooks)
    _write_user_text(
        dest / "settings.json",
        json.dumps(settings, indent=2) + "\n",
        fs=fs,
        force=force,
        log=log,
        label="settings.json",
    )


def _install_artifact_templates(
    src: Path,
    dest: Path,
    log: list[str],
    fs: ProjectFS,
    rescue: _Rescue | None = None,
) -> None:
    """Install the artifact markdown templates into ``.claude/templates/``."""
    srcd = src / "templates" / "artifacts"
    if not srcd.is_dir():
        return
    tdest = dest / "templates"
    _copy_tree(srcd, tdest, fs=fs, rescue=rescue, log=log)
    log.append(
        f"  • templates/ ({sum(1 for _ in tdest.glob('*.md'))} artifact templates)"
    )


def _install_loop_script(src: Path, dest: Path, log: list[str], fs: ProjectFS) -> None:
    """Install the bounded headless-loop runner into ``.claude/scripts/``.

    The script self-configures its exit condition from the ``gates:`` list in
    ``stack-catalog.snapshot.yaml`` (execution-ordered; last entry = final gate) and
    exposes every knob as an ``SDLC_*`` environment variable, so it ships kit-owned —
    upgrades keep the brakes current, and hand-edits still get the upgrader's
    checksum-based sidecar protection like any other kit file.
    """
    srcf = src / "templates" / "scripts" / "sdlc-loop.sh"
    if not srcf.is_file():
        return
    sdest = dest / "scripts"
    fs.mkdir(fs.relpath(sdest))
    script_rel = fs.relpath(sdest / srcf.name)
    fs.copy_file(srcf, script_rel)
    fs.chmod(script_rel, 0o755)
    log.append("  • scripts/ (sdlc-loop.sh — bounded headless runner)")


def _write_claude_md(
    src: Path,
    target: Path,
    plan: ResolvedPlan,
    *,
    fs: ProjectFS,
    force: bool,
    log: list[str],
) -> None:
    """Write CLAUDE.md and fill its 'Project-specific rules' block from the resolved stack."""
    claude_md = target / "CLAUDE.md"
    base = (src / "templates" / "CLAUDE.md").read_text(encoding="utf-8")
    block_tmpl = src / "templates" / "CLAUDE.stack.md.tmpl"
    if block_tmpl.is_file():
        block = (
            render_text(block_tmpl.read_text(encoding="utf-8"), plan.context).rstrip()
            + "\n"
        )
        idx = base.find(_STACK_MARKER)
        base = (
            (base[:idx].rstrip() + "\n\n" + block)
            if idx != -1
            else (base.rstrip() + "\n\n" + block)
        )
    _write_user_text(claude_md, base, fs=fs, force=force, log=log, label="CLAUDE.md")


def _mcp_lock(mcp_servers: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Derive a deterministic ``.mcp.lock.json`` document from the resolved server configs.

    Captures the *resolved* package + pinned version (parsed from the ``npx -y <pkg>@<ver>`` args) or
    the hosted URL per server, so a reviewer / ``doctor --mcp`` can see exactly what would run. Purely
    a function of the catalog config (no timestamps), so the same selection always locks identically.
    """
    locked: dict[str, dict[str, Any]] = {}
    for sid in sorted(mcp_servers):
        cfg = mcp_servers[sid]
        url = cfg.get("url")
        if url:
            locked[sid] = {"type": str(cfg.get("type", "http")), "url": str(url)}
            continue
        command = str(cfg.get("command", ""))
        entry: dict[str, Any] = {"type": str(cfg.get("type", "stdio"))}
        spec = _mcp_package_spec(command, list(cfg.get("args", [])))
        if spec:
            package, version = spec
            entry["package"] = package
            if version:
                entry["version"] = version
        else:
            entry["command"] = command
        locked[sid] = entry
    return {"schema": 1, "servers": locked}


def _mcp_package_spec(command: str, args: list[Any]) -> tuple[str, str] | None:
    """Return ``(package, version)`` for an ``npx`` server, or None if not npx-resolvable.

    Picks the first non-flag, non-``${ENV}`` argument as the package spec and splits a trailing
    ``@version`` (handling scoped ``@scope/name@version`` via the last ``@``). Version is ``""`` if
    the spec is unpinned.
    """
    if command != "npx":
        return None
    for arg in args:
        token = str(arg)
        if not token or token.startswith("-") or token.startswith("${"):
            continue
        if token.startswith(("http://", "https://", "file://")):
            return None  # a URL/path argument is not an npm package spec to pin
        if token.startswith("@"):  # scoped: @scope/name[@version]
            at = token.rfind("@")
            if at > 0:
                return token[:at], token[at + 1 :]
            return token, ""
        name, sep, version = token.partition("@")
        return name, version if sep else ""
    return None


def _write_mcp(
    target: Path,
    plan: ResolvedPlan,
    *,
    fs: ProjectFS,
    force: bool,
    log: list[str],
) -> None:
    """Write a project-root ``.mcp.json`` (+ a derived ``.mcp.lock.json``) if MCP servers chosen."""
    if not plan.mcp_servers:
        # No servers selected: drop a now-orphaned lockfile, but only when there is no ``.mcp.json``
        # beside it to describe — never delete a file from a user's own hand-written MCP config pair.
        if fs.is_file(".mcp.lock.json") and not fs.is_file(".mcp.json"):
            fs.unlink(".mcp.lock.json")
            log.append("  • removed orphaned .mcp.lock.json (no MCP servers)")
        return
    mcp_existed = (target / ".mcp.json").is_file()
    rendered_servers = project_mcp_servers(
        plan.mcp_servers, plan.mcp_server_specs, "claude"
    )
    doc = {"mcpServers": rendered_servers}
    _write_user_text(
        target / ".mcp.json",
        json.dumps(doc, indent=2) + "\n",
        fs=fs,
        force=force,
        log=log,
        label=".mcp.json",
    )
    # The lockfile is derived from .mcp.json. Regenerate it only when we actually (over)wrote
    # .mcp.json — a fresh write or --force. If the user's own .mcp.json was preserved (written as a
    # sidecar), leave their lockfile untouched so the two never describe different server sets.
    if force or not mcp_existed:
        fs.write_text(
            ".mcp.lock.json",
            json.dumps(_mcp_lock(rendered_servers), indent=2) + "\n",
        )
        log.append("  • .mcp.lock.json (resolved MCP versions)")


def _write_readme(
    src: Path,
    target: Path,
    plan: ResolvedPlan,
    *,
    fs: ProjectFS,
    force: bool,
    log: list[str],
) -> None:
    """Render ``README.claude-sdlc.md`` from the template."""
    tmpl = src / "templates" / "README.claude-sdlc.md.tmpl"
    if not tmpl.is_file():
        return
    text = render_text(tmpl.read_text(encoding="utf-8"), plan.context)
    # Honor `force` (don't hardcode True): README.claude-sdlc.md is a user-editable onboarding doc, so
    # an existing one is preserved and the new render lands as a .claude-kit sidecar unless --force.
    _write_user_text(
        target / "README.claude-sdlc.md",
        text,
        fs=fs,
        force=force,
        log=log,
        label="README.claude-sdlc.md",
    )


def _write_agents_md(
    src: Path,
    target: Path,
    plan: ResolvedPlan,
    *,
    fs: ProjectFS,
    force: bool,
    log: list[str],
) -> None:
    """Emit a root ``AGENTS.md`` — the same projection the ``export`` command builds.

    Claude Code itself reads ``CLAUDE.md``, not ``AGENTS.md`` — this file exists for every *other*
    agent working in the repo (Cursor, Copilot, Codex, …), so teammates outside Claude Code get the
    kit's standards from day one. An existing ``AGENTS.md`` is never clobbered (sidecar unless
    ``force``); ``claude-kit export`` regenerates it on demand.
    """
    # Deferred import: export imports this module at load time, so importing it lazily here
    # avoids the cycle.
    from claude_kit import export

    _write_user_text(
        target / "AGENTS.md",
        export._agents_document(src, plan),
        fs=fs,
        force=force,
        log=log,
        label="AGENTS.md",
    )


def _update_gitignore(target: Path, log: list[str], fs: ProjectFS) -> None:
    """Append the selective claude-kit gitignore entries (idempotently)."""
    existing = (
        fs.read_text(".gitignore").splitlines() if fs.is_file(".gitignore") else []
    )
    have = set(existing)
    missing = [e for e in GITIGNORE_ENTRIES if e not in have]
    if not missing:
        return
    lines = list(existing)
    if lines and lines[-1].strip():
        lines.append("")
    lines.append("# claude-kit runtime + local overrides")
    lines.extend(missing)
    fs.write_text(".gitignore", "\n".join(lines) + "\n")
    log.append(f"  • .gitignore (+{len(missing)} entries)")


def _seed_runtime_dirs(_dest: Path, log: list[str], fs: ProjectFS) -> None:
    """Create gitignored runtime dirs (state/, tmp/) with a .gitkeep so they exist but stay empty."""
    for relative in (_LEGACY_STATE_LAYOUT.state, _LEGACY_STATE_LAYOUT.temporary):
        fs.mkdir(relative)
        fs.write_text(f"{relative}/.gitkeep", "")


def _seed_agent_memory(src: Path, _dest: Path, log: list[str], fs: ProjectFS) -> None:
    """Install the agent-memory seed (only if the project doesn't already have one)."""
    if fs.exists(_LEGACY_STATE_LAYOUT.memory):
        return
    seed = src / "templates" / "agent-memory"
    if seed.is_dir():
        _copy_tree(seed, fs.path(_LEGACY_STATE_LAYOUT.memory), fs=fs)
        log.append("  • agent-memory/ seed")


def _classify_owner(rel: str, plan: ResolvedPlan) -> str:
    """Classify a relative path as kit / overlay / user-editable for upgrade policy."""
    user_editable = {
        "CLAUDE.md",
        "AGENTS.md",
        "README.claude-sdlc.md",
        ".mcp.json",
        ".claude/settings.json",
        _LEGACY_STATE_LAYOUT.continuity,
    }
    if rel in user_editable or rel.startswith(_LEGACY_MEMORY_PREFIX):
        return "user-editable"
    overlay_paths = {f".claude/rules/{r}" for r in plan.overlay_rules}
    overlay_paths |= {f".claude/agents/{a}.md" for a in plan.overlay_agents}
    if rel in overlay_paths:
        return "overlay"
    return "kit"


def _record_files(target: Path, plan: ResolvedPlan, fs: ProjectFS) -> list[FileRecord]:
    """Compute checksum + ownership records for every installed file (excluding runtime/self)."""
    records: list[FileRecord] = []
    candidates: list[Path] = []
    for top in (
        "CLAUDE.md",
        "AGENTS.md",
        "README.claude-sdlc.md",
        ".mcp.json",
        ".mcp.lock.json",
    ):
        p = target / top
        if p.is_file():
            candidates.append(p)
    dest = target / _LEGACY_STATE_LAYOUT.root
    fs.assert_tree_safe(_LEGACY_STATE_LAYOUT.root)
    skip_dirs = {
        target / _LEGACY_STATE_LAYOUT.state,
        target / _LEGACY_STATE_LAYOUT.temporary,
    }
    init_options = target / _LEGACY_STATE_LAYOUT.manifest
    journal = target / _LEGACY_STATE_LAYOUT.journal
    for p in sorted(dest.rglob("*")):
        if not p.is_file() or p in {init_options, journal}:
            continue
        if p.name.endswith(".claude-kit"):
            continue  # transient sidecar of a protected file — not a tracked install artifact
        if any(sd in p.parents for sd in skip_dirs):
            continue
        candidates.append(p)
    for p in candidates:
        rel = p.relative_to(target).as_posix()
        records.append(
            FileRecord(path=rel, sha256=_sha256(p), owner=_classify_owner(rel, plan))
        )
    return sorted(records, key=lambda r: r.path)


def _write_config(
    src: Path,
    target: Path,
    plan: ResolvedPlan,
    log: list[str],
    fs: ProjectFS,
) -> None:
    """Write the resolved catalog snapshot and init-options.json (with file checksums)."""
    config_dest = target / _LEGACY_CONFIG_ROOT
    fs.mkdir(fs.relpath(config_dest))
    snapshot = {
        "schema_version": 1,
        "selection": plan.selection.to_dict(),
        "agents": plan.agents,
        "skills": plan.skills,
        "overlay_rules": plan.overlay_rules,
        "overlay_agents": plan.overlay_agents,
        "hooks": plan.hooks,
        "gates": plan.gates,
        "gate_definitions": {
            gate: definition.to_dict()
            for gate, definition in plan.gate_definitions.items()
        },
        "gate_definition_digest": plan.gate_definition_digest,
        "mcp": list(plan.mcp_servers),
        "mcp_semantics": plan.mcp_semantics,
        "org": plan.org.to_dict() if plan.org else None,
        "detected_commands": plan.detected_commands or {},
    }
    fs.write_text(
        _LEGACY_STATE_LAYOUT.stack_snapshot,
        yaml.safe_dump(snapshot, sort_keys=False),
    )
    options = InitOptions(
        claude_kit_version=__version__,
        selection=plan.selection,
        files=_record_files(target, plan, fs),
    )
    fs.write_text(
        _LEGACY_STATE_LAYOUT.manifest,
        json.dumps(options.to_dict(), indent=2) + "\n",
    )
    log.append("  • config/ (init-options.json + stack snapshot)")


def _component_name(value: str, *, kind: str) -> str:
    """Validate a catalog component name before it reaches source or destination paths."""

    normalized = normalize_relative_path(value)
    if "/" in normalized:
        raise UnsafePathError(
            f"unsafe selected {kind} {value!r}: component names cannot contain directories"
        )
    return normalized


def _preflight_plan(src: Path, plan: ResolvedPlan) -> None:
    """Verify every selected payload component before the live tree is touched."""

    missing: list[str] = []

    def require(path: Path, label: str, *, directory: bool = False) -> None:
        present = path.is_dir() if directory else path.is_file()
        if not present:
            missing.append(f"{label} ({path})")

    require(src / "rules", "core rules", directory=True)
    require(src / "templates" / "CLAUDE.md", "CLAUDE.md template")
    require(
        src / "templates" / "CLAUDE.stack.md.tmpl",
        "project-specific CLAUDE.md template",
    )
    require(src / "templates" / "CONTINUITY.template.md", "CONTINUITY template")
    require(
        src / "templates" / "README.claude-sdlc.md.tmpl",
        "README.claude-sdlc.md template",
    )
    require(src / "templates" / "artifacts", "artifact templates", directory=True)
    require(src / "templates" / "agent-memory", "agent-memory seed", directory=True)
    require(src / "templates" / "scripts" / "sdlc-loop.sh", "bounded loop script")
    for name in plan.agents:
        safe = _component_name(name, kind="agent")
        require(src / "agents" / f"{safe}.md", f"agent {name}")
    for name in plan.skills:
        safe = _component_name(name, kind="skill")
        require(src / "skills" / safe / "SKILL.md", f"skill {name}")
    for name in plan.overlay_rules:
        safe = _component_name(name, kind="overlay rule")
        if _find_overlay(src, plan.stack_dirs, "rules", safe) is None:
            missing.append(f"overlay rule {name}")
    for name in plan.overlay_agents:
        safe = _component_name(name, kind="overlay agent")
        if _find_overlay(src, plan.stack_dirs, "agents", f"{safe}.md") is None:
            missing.append(f"overlay agent {name}")
    for script in hooks_mod.scripts_for(plan.hooks):
        safe = _component_name(script, kind="hook script")
        require(src / "hooks" / "scripts" / safe, f"hook script {script}")
    for stack_dir in plan.stack_dirs.values():
        if stack_dir:
            normalize_relative_path(stack_dir)

    if plan.org is not None:
        org_src = src / "templates" / "org"
        if plan.org.packs:
            require(org_src / "README.md", "org-pack index")
        for name in plan.org.org_skills:
            safe = _component_name(name, kind="org skill")
            require(org_src / "skills" / safe / "SKILL.md", f"org skill {name}")
        for name in plan.org.org_agents:
            safe = _component_name(name, kind="org agent")
            require(org_src / "agents" / f"{safe}.md", f"org agent {name}")
        for name in plan.org.org_rules:
            safe = _component_name(name, kind="org rule")
            require(org_src / "rules" / safe, f"org rule {name}")
        for name in plan.org.packs:
            safe = _component_name(name, kind="org pack")
            require(org_src / "packs" / safe / "pack.yaml", f"org pack {name}")
    for server_id, config in plan.mcp_servers.items():
        _component_name(server_id, kind="MCP server")
        if not isinstance(config, dict) or not (
            str(config.get("command", "")).strip() or str(config.get("url", "")).strip()
        ):
            missing.append(f"MCP server {server_id} has no command or URL")

    if missing:
        details = "\n  - ".join(missing)
        raise FileNotFoundError(
            "selected claude-kit payload is incomplete; no project files were changed:\n"
            f"  - {details}"
        )


def _stage_inventory(stage: Path) -> dict[str, tuple[str, int]]:
    """Snapshot every staged regular file's digest and permission bits."""

    stage_fs = ProjectFS(stage)
    inventory: dict[str, tuple[str, int]] = {}
    for path in sorted(stage.rglob("*")):
        rel = path.relative_to(stage).as_posix()
        checked = stage_fs.assert_tree_safe(rel)
        if checked.is_dir():
            continue
        if not checked.is_file():
            raise UnsafePathError(f"staged install contains a special file: {rel}")
        data = stage_fs.read_bytes(rel)
        inventory[rel] = (
            hashlib.sha256(data).hexdigest(),
            checked.lstat().st_mode & 0o777,
        )
    return inventory


def _validate_manifest(root: Path, *, strict: bool) -> None:
    """Verify manifest targets and hashes, then run installed-config validation."""

    root_fs = ProjectFS(root)
    config_rel = _LEGACY_STATE_LAYOUT.manifest
    try:
        document = json.loads(root_fs.read_text(config_rel))
    except (FileNotFoundError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise RuntimeError(
            f"staged install has no valid init-options manifest: {exc}"
        ) from exc
    records = document.get("files")
    if not isinstance(records, list) or not records:
        raise RuntimeError("staged install manifest contains no file records")
    absent: list[str] = []
    mismatched: list[str] = []
    for record in records:
        if not isinstance(record, dict):
            raise RuntimeError(
                "staged install manifest contains a malformed file record"
            )
        rel = normalize_relative_path(str(record.get("path", "")))
        if not root_fs.is_file(rel):
            absent.append(rel)
            continue
        expected = record.get("sha256")
        actual = hashlib.sha256(root_fs.read_bytes(rel)).hexdigest()
        if not isinstance(expected, str) or expected != actual:
            mismatched.append(rel)
    if absent:
        raise RuntimeError(
            "staged install manifest references missing target(s): " + ", ".join(absent)
        )
    if mismatched:
        raise RuntimeError(
            "staged install manifest checksum mismatch for target(s): "
            + ", ".join(mismatched)
        )
    # Local import avoids scaffold <-> validator import-time cycles.
    from claude_kit import validator

    ok, messages = validator.validate(root, strict=strict)
    if not ok:
        failures = "; ".join(
            message for message in messages if message.startswith("FAIL")
        )
        raise RuntimeError(f"staged install failed strict validation: {failures}")


def _validate_stage(stage: Path) -> dict[str, tuple[str, int]]:
    """Validate staged output and return its immutable apply inventory."""

    _validate_manifest(stage, strict=True)
    return _stage_inventory(stage)


def _verify_stage_inventory(stage: Path, expected: dict[str, tuple[str, int]]) -> None:
    current = _stage_inventory(stage)
    if current != expected:
        raise RuntimeError(
            "validated install stage changed before it could be applied; no changes committed"
        )


def _copy_staged_file(
    stage_fs: ProjectFS,
    inventory: dict[str, tuple[str, int]],
    source_rel: str,
    live_fs: ProjectFS,
    destination_rel: str | None = None,
) -> Path:
    """Copy one digest-pinned staged file through root-bound atomic writes."""

    destination_rel = destination_rel or source_rel
    expected_digest, mode = inventory[source_rel]
    data = stage_fs.read_bytes(source_rel)
    if hashlib.sha256(data).hexdigest() != expected_digest:
        raise RuntimeError(f"validated staged file changed before apply: {source_rel}")
    return live_fs.write_bytes(destination_rel, data, mode=mode)


def _files_below(inventory: dict[str, tuple[str, int]], prefix: str) -> list[str]:
    marker = prefix.rstrip("/") + "/"
    return sorted(rel for rel in inventory if rel.startswith(marker))


def _copy_staged_subtree(
    stage_fs: ProjectFS,
    inventory: dict[str, tuple[str, int]],
    source_prefix: str,
    live_fs: ProjectFS,
    destination_prefix: str | None = None,
) -> set[str]:
    destination_prefix = destination_prefix or source_prefix
    copied: set[str] = set()
    live_fs.mkdir(destination_prefix)
    marker = source_prefix.rstrip("/") + "/"
    for source_rel in _files_below(inventory, source_prefix):
        suffix = source_rel.removeprefix(marker)
        destination_rel = f"{destination_prefix.rstrip('/')}/{suffix}"
        _copy_staged_file(stage_fs, inventory, source_rel, live_fs, destination_rel)
        copied.add(source_rel)
    return copied


def _recorded_live_paths(live_fs: ProjectFS) -> set[str]:
    """Return paths owned by the previous manifest, failing closed on corruption."""

    rel = _LEGACY_STATE_LAYOUT.manifest
    if not live_fs.is_file(rel):
        return set()
    try:
        document = json.loads(live_fs.read_text(rel))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise RuntimeError(f"existing init-options manifest is corrupt: {exc}") from exc
    records = document.get("files", [])
    if not isinstance(records, list):
        raise RuntimeError("existing init-options manifest has an invalid files list")
    owned: set[str] = set()
    for record in records:
        if not isinstance(record, dict):
            raise RuntimeError("existing init-options manifest has a malformed record")
        owned.add(normalize_relative_path(str(record.get("path", ""))))
    return owned


def _promote_staged_subtree(
    stage_fs: ProjectFS,
    inventory: dict[str, tuple[str, int]],
    source_prefix: str,
    live_fs: ProjectFS,
    *,
    transaction_rel: str,
    previously_owned: set[str],
    rescue: _Rescue,
    rescue_untracked: bool,
    log: list[str],
) -> set[str]:
    """Assemble, verify, and two-rename a complete kit-owned subtree.

    The two renames are individually atomic and rollback-journaled. Portable
    Python has no cross-platform rename-exchange primitive, so a process may
    observe a brief destination gap; the exclusive project lease prevents every
    cooperating claude-kit writer from entering that gap.
    """

    token = source_prefix.removeprefix(".claude/").replace("/", "-")
    assembled = f"{transaction_rel}/assembled/{token}"
    retired = f"{transaction_rel}/retired/{token}"
    source_files = _files_below(inventory, source_prefix)
    source_set = set(source_files)
    if source_files:
        _copy_staged_subtree(stage_fs, inventory, source_prefix, live_fs, assembled)
        assembled_marker = assembled.rstrip("/") + "/"
        source_marker = source_prefix.rstrip("/") + "/"
        for source_rel in source_files:
            suffix = source_rel.removeprefix(source_marker)
            assembled_rel = assembled_marker + suffix
            expected, _mode = inventory[source_rel]
            actual = hashlib.sha256(live_fs.read_bytes(assembled_rel)).hexdigest()
            if actual != expected:
                raise RuntimeError(
                    f"assembled install subtree failed digest verification: {source_rel}"
                )

    rescued: list[Path] = []
    if live_fs.is_dir(source_prefix):
        live_fs.assert_tree_safe(source_prefix)
        live_root = live_fs.path(source_prefix)
        for live in sorted(live_root.rglob("*")):
            if not live.is_file():
                continue
            rel = live.relative_to(live_fs.root).as_posix()
            if rel in source_set or rel in previously_owned:
                continue
            suffix = live.relative_to(live_root).as_posix()
            if rescue_untracked:
                keep = rescue.root / rel
                live_fs.move(rel, live_fs.relpath(keep))
                rescued.append(Path(suffix))
            else:
                destination = f"{assembled}/{suffix}"
                live_fs.copy_file(live, destination)

    if live_fs.exists(source_prefix):
        live_fs.move(source_prefix, retired)
    if live_fs.exists(assembled):
        live_fs.move(assembled, source_prefix)

    if rescued:
        shown = ", ".join(str(path) for path in rescued[:3])
        more = f" (+{len(rescued) - 3} more)" if len(rescued) > 3 else ""
        log.append(
            f"  • kept your {Path(source_prefix).name}/ additions -> "
            f"{rescue.root.name}/: {shown}{more}"
        )
    return source_set


def _copy_staged_user_file(
    stage_fs: ProjectFS,
    inventory: dict[str, tuple[str, int]],
    rel: str,
    live_fs: ProjectFS,
    *,
    force: bool,
    log: list[str],
    label: str,
) -> None:
    data = stage_fs.read_bytes(rel)
    expected, mode = inventory[rel]
    if hashlib.sha256(data).hexdigest() != expected:
        raise RuntimeError(f"validated staged file changed before apply: {rel}")
    if live_fs.is_file(rel) and not force:
        if live_fs.read_bytes(rel) == data:
            log.append(f"  • {label} already current")
            return
        sidecar = rel + ".claude-kit"
        live_fs.write_bytes(sidecar, data, mode=mode)
        log.append(
            f"  • {label} exists — wrote {Path(sidecar).name} "
            "(use --force to overwrite)"
        )
        return
    live_fs.write_bytes(rel, data, mode=mode)
    log.append(f"  • {label} installed")


def _merge_staged_gitignore(
    stage_fs: ProjectFS,
    inventory: dict[str, tuple[str, int]],
    live_fs: ProjectFS,
    log: list[str],
) -> None:
    staged = stage_fs.read_text(".gitignore").splitlines()
    existing = (
        live_fs.read_text(".gitignore").splitlines()
        if live_fs.is_file(".gitignore")
        else []
    )
    have = set(existing)
    desired = [line for line in staged if line and not line.startswith("#")]
    missing = [line for line in desired if line not in have]
    if not missing:
        return
    lines = list(existing)
    if lines and lines[-1].strip():
        lines.append("")
    comment = next(
        (line for line in staged if line.startswith("#")),
        "# claude-kit runtime + local overrides",
    )
    lines.append(comment)
    lines.extend(missing)
    _expected, mode = inventory[".gitignore"]
    live_fs.write_text(".gitignore", "\n".join(lines) + "\n", mode=mode)
    log.append(f"  • .gitignore (+{len(missing)} entries)")


def _write_final_manifest_from_stage(
    stage_fs: ProjectFS,
    live_fs: ProjectFS,
    log: list[str],
) -> None:
    """Preserve staged metadata while recording the actual preserved live bytes."""

    document = json.loads(stage_fs.read_text(_LEGACY_STATE_LAYOUT.manifest))
    final_records: dict[str, FileRecord] = {}
    raw_records = document.get("files", [])
    if not isinstance(raw_records, list):
        raise RuntimeError("staged init-options manifest has an invalid files list")
    staged_mcp_active = True
    staged_paths = {
        str(raw.get("path", "")) for raw in raw_records if isinstance(raw, dict)
    }
    if ".mcp.json" in staged_paths:
        staged_mcp_active = live_fs.is_file(".mcp.json") and (
            live_fs.read_bytes(".mcp.json") == stage_fs.read_bytes(".mcp.json")
        )
    for raw in raw_records:
        if not isinstance(raw, dict):
            raise RuntimeError("staged init-options manifest has a malformed record")
        rel = normalize_relative_path(str(raw.get("path", "")))
        if rel == ".mcp.lock.json" and not staged_mcp_active:
            continue
        if not live_fs.is_file(rel):
            if rel.startswith(_LEGACY_MEMORY_PREFIX):
                continue
            raise RuntimeError(
                f"staged manifest target disappeared during apply: {rel}"
            )
        final_records[rel] = FileRecord(
            path=rel,
            sha256=hashlib.sha256(live_fs.read_bytes(rel)).hexdigest(),
            owner=str(raw.get("owner", "kit")),
        )

    preserved_user_paths: list[str] = []
    if live_fs.is_file(_LEGACY_STATE_LAYOUT.continuity):
        preserved_user_paths.append(_LEGACY_STATE_LAYOUT.continuity)
    if live_fs.is_dir(_LEGACY_STATE_LAYOUT.memory):
        memory = live_fs.assert_tree_safe(_LEGACY_STATE_LAYOUT.memory)
        preserved_user_paths.extend(
            path.relative_to(live_fs.root).as_posix()
            for path in sorted(memory.rglob("*"))
            if path.is_file()
        )
    for rel in preserved_user_paths:
        final_records[rel] = FileRecord(
            path=rel,
            sha256=hashlib.sha256(live_fs.read_bytes(rel)).hexdigest(),
            owner="user-editable",
        )
    document["files"] = [final_records[rel].to_dict() for rel in sorted(final_records)]
    live_fs.write_text(
        _LEGACY_STATE_LAYOUT.manifest,
        json.dumps(document, indent=2) + "\n",
    )
    log.append("  • config/ (init-options.json + stack snapshot)")


def _apply_validated_stage(
    stage_fs: ProjectFS,
    inventory: dict[str, tuple[str, int]],
    live_fs: ProjectFS,
    *,
    transaction_rel: str,
    force: bool,
    log: list[str],
) -> None:
    """Apply only digest-pinned staged bytes, preserving established merge policy."""

    applied: set[str] = set()
    rescue = _Rescue(root=next_backup_dir(live_fs.root), target=live_fs.root)
    previously_owned = _recorded_live_paths(live_fs)

    applied |= _promote_staged_subtree(
        stage_fs,
        inventory,
        ".claude/rules",
        live_fs,
        transaction_rel=transaction_rel,
        previously_owned=previously_owned,
        rescue=rescue,
        rescue_untracked=True,
        log=log,
    )
    log.append(
        f"  • rules/ ({len(_files_below(inventory, '.claude/rules'))} core + overlays)"
    )

    for prefix in (
        ".claude/agents",
        ".claude/hooks",
        ".claude/scripts",
        ".claude/org-packs",
    ):
        applied |= _promote_staged_subtree(
            stage_fs,
            inventory,
            prefix,
            live_fs,
            transaction_rel=transaction_rel,
            previously_owned=previously_owned,
            rescue=rescue,
            rescue_untracked=False,
            log=log,
        )
    for prefix in (".claude/skills", ".claude/templates"):
        applied |= _promote_staged_subtree(
            stage_fs,
            inventory,
            prefix,
            live_fs,
            transaction_rel=transaction_rel,
            previously_owned=previously_owned,
            rescue=rescue,
            rescue_untracked=True,
            log=log,
        )
    memory_prefix = _LEGACY_STATE_LAYOUT.memory
    memory_files = _files_below(inventory, memory_prefix)
    if memory_files:
        if not live_fs.exists(memory_prefix):
            applied |= _copy_staged_subtree(stage_fs, inventory, memory_prefix, live_fs)
            log.append("  • agent-memory/ seed")
        else:
            applied.update(memory_files)

    for prefix in (_LEGACY_STATE_LAYOUT.state, _LEGACY_STATE_LAYOUT.temporary):
        applied |= _copy_staged_subtree(stage_fs, inventory, prefix, live_fs)

    settings_rel = ".claude/settings.json"
    _copy_staged_user_file(
        stage_fs,
        inventory,
        settings_rel,
        live_fs,
        force=force,
        log=log,
        label="settings.json",
    )
    applied.add(settings_rel)

    continuity = ".claude/CONTINUITY.template.md"
    _copy_staged_file(stage_fs, inventory, continuity, live_fs)
    applied.add(continuity)

    config_prefix = _LEGACY_CONFIG_ROOT
    init_rel = _LEGACY_STATE_LAYOUT.manifest
    for rel in _files_below(inventory, config_prefix):
        if rel == init_rel:
            continue
        _copy_staged_file(stage_fs, inventory, rel, live_fs)
        applied.add(rel)

    for rel, label in (
        ("CLAUDE.md", "CLAUDE.md"),
        ("AGENTS.md", "AGENTS.md"),
        ("README.claude-sdlc.md", "README.claude-sdlc.md"),
    ):
        _copy_staged_user_file(
            stage_fs,
            inventory,
            rel,
            live_fs,
            force=force,
            log=log,
            label=label,
        )
        applied.add(rel)

    if ".mcp.json" in inventory:
        mcp_existed = live_fs.is_file(".mcp.json")
        _copy_staged_user_file(
            stage_fs,
            inventory,
            ".mcp.json",
            live_fs,
            force=force,
            log=log,
            label=".mcp.json",
        )
        applied.add(".mcp.json")
        if ".mcp.lock.json" in inventory:
            mcp_active = live_fs.is_file(".mcp.json") and (
                live_fs.read_bytes(".mcp.json") == stage_fs.read_bytes(".mcp.json")
            )
            if (
                force
                or not mcp_existed
                or (mcp_active and not live_fs.is_file(".mcp.lock.json"))
            ):
                _copy_staged_file(stage_fs, inventory, ".mcp.lock.json", live_fs)
            applied.add(".mcp.lock.json")
    elif (
        live_fs.is_file(".mcp.lock.json")
        and not live_fs.is_file(".mcp.json")
        and ".mcp.lock.json" in previously_owned
    ):
        live_fs.unlink(".mcp.lock.json")
        log.append("  • removed orphaned .mcp.lock.json (no MCP servers)")

    _merge_staged_gitignore(stage_fs, inventory, live_fs, log)
    applied.add(".gitignore")
    applied.add(init_rel)
    unhandled = sorted(set(inventory) - applied)
    if unhandled:
        raise RuntimeError(
            "validated install contains unhandled staged file(s): "
            + ", ".join(unhandled)
        )
    _write_final_manifest_from_stage(stage_fs, live_fs, log)


def _before_live_apply(_stage: Path) -> None:
    """Test seam between immutable-stage validation and live transaction setup."""


def _install_sdlc_direct(
    src: Path,
    target: Path,
    plan: ResolvedPlan,
    *,
    force: bool = False,
    log: list[str] | None = None,
    detect_target: str | Path | None = None,
    rescue_existing: bool = True,
) -> list[str]:
    """Render directly into a preflighted target through :class:`ProjectFS`."""

    if log is None:
        log = []
    target = Path(target)
    fs = ProjectFS(target)
    fs.mkdir(_LEGACY_STATE_LAYOUT.root)
    dest = fs.root / _LEGACY_STATE_LAYOUT.root

    plan.context.setdefault("project_name", fs.root.name)
    plan.context["agent_count"] = str(len(plan.agents) + len(plan.overlay_agents))
    plan.context["skill_count"] = str(len(plan.skills))
    plan.context["overlay_rules_list"] = ", ".join(plan.overlay_rules) or "none"

    if plan.selection.detect_commands:
        detect_from = Path(detect_target) if detect_target is not None else fs.root
        overrides = detect.detect_commands(detect_from, plan.selection)
        if overrides:
            plan.context.update(overrides)
            log.append(f"  • detected commands: {', '.join(sorted(overrides))}")
        plan.detected_commands = overrides

    rescue = (
        _Rescue(root=next_backup_dir(fs.root), target=fs.root)
        if rescue_existing
        else None
    )

    _install_rules(src, dest, plan, log, fs, rescue)
    _write_claude_md(src, fs.root, plan, fs=fs, force=force, log=log)
    fs.copy_file(
        src / "templates" / "CONTINUITY.template.md",
        ".claude/CONTINUITY.template.md",
    )
    _install_agents(src, dest, plan, log, fs)
    _install_skills(src, dest, plan, log, fs, rescue)
    _install_org(src, dest, plan, log, fs, rescue)
    _seed_agent_memory(src, dest, log, fs)
    _install_hooks_and_settings(src, dest, plan, fs=fs, force=force, log=log)
    _install_artifact_templates(src, dest, log, fs, rescue)
    _install_loop_script(src, dest, log, fs)
    _write_mcp(fs.root, plan, fs=fs, force=force, log=log)
    _write_readme(src, fs.root, plan, fs=fs, force=force, log=log)
    _write_agents_md(src, fs.root, plan, fs=fs, force=force, log=log)
    _seed_runtime_dirs(dest, log, fs)
    _update_gitignore(fs.root, log, fs)
    _write_config(src, fs.root, plan, log, fs)
    return log


def install_sdlc(
    src: Path,
    target: Path,
    plan: ResolvedPlan,
    *,
    force: bool = False,
    backup_existing: bool = False,
    log: list[str] | None = None,
    detect_target: str | Path | None = None,
) -> list[str]:
    """Stage, validate, and transactionally install a resolved configuration.

    Args:
        src: Payload root (contains ``rules/ agents/ skills/ hooks/ templates/ catalog/``).
        target: Project root to install into.
        plan: The resolved install plan from :func:`claude_kit.catalog.resolve`.
        force: Overwrite user-editable files (CLAUDE.md, settings.json, .mcp.json) instead of
            writing ``.claude-kit`` sidecars.
        backup_existing: Move an existing ``.claude/`` to the next
            ``.claude.bak-N/`` inside the same rollback transaction before installing.
        log: Optional list to append human-readable log lines to.
        detect_target: Repo to inspect for real package-manager commands (defaults to ``target``).
            The previewer passes the real project here while installing into a throwaway sandbox, so
            a dry run reflects the repo's tooling rather than the empty sandbox.

    Returns:
        The log list, one line per installed component.
    """
    if log is None:
        log = []
    src = Path(src)
    target = Path(target).expanduser()
    _preflight_plan(src, plan)
    plan.context.setdefault("project_name", target.name)
    detection_root = Path(detect_target) if detect_target is not None else target

    # The stage is isolated from the project.  It validates the complete selected
    # payload and the final checksum manifest before the transaction may begin.
    staged_plan = deepcopy(plan)
    with tempfile.TemporaryDirectory(prefix="claude-kit-stage-") as tmp:
        # ``tempfile`` may spell the trusted OS temp root through a platform
        # alias (macOS: /var -> /private/var). Canonicalize only this
        # process-created boundary; user-entered project paths stay lexical.
        stage = Path(tmp).resolve()
        _install_sdlc_direct(
            src,
            stage,
            staged_plan,
            force=True,
            log=[],
            detect_target=detection_root,
            rescue_existing=False,
        )
        inventory = _validate_stage(stage)
        # Preserve the public API's successful-call behavior: command detection
        # and derived render context remain visible on the caller's plan even
        # though the immutable stage is rendered from an isolated copy.
        plan.context.update(staged_plan.context)
        plan.detected_commands = deepcopy(staged_plan.detected_commands)
        _before_live_apply(stage)

        fs = ProjectFS(target)
        operation = (
            "force"
            if force or backup_existing
            else ("merge" if fs.root.exists() else "install")
        )
        with ProjectTransaction(
            fs,
            operation=operation,
            to_version=__version__,
        ) as transaction:
            # Freeze the validated result on the destination filesystem. Every
            # live byte below is read from this digest-pinned transaction-local
            # tree; payload and detection are never consulted a second time.
            staged_rel = f"{transaction.transaction_rel}/validated-stage"
            fs.copy_tree(stage, staged_rel)
            transaction_stage = fs.path(staged_rel)
            _verify_stage_inventory(transaction_stage, inventory)
            stage_fs = ProjectFS(transaction_stage)
            if backup_existing and fs.is_dir(_LEGACY_STATE_LAYOUT.root):
                n = 1
                while fs.exists(f"{_LEGACY_STATE_LAYOUT.root}.bak-{n}"):
                    n += 1
                backup_rel = f"{_LEGACY_STATE_LAYOUT.root}.bak-{n}"
                fs.move(_LEGACY_STATE_LAYOUT.root, backup_rel)
                # The transaction journal moved with the old tree; the top-level
                # recovery marker remains authoritative until commit/rollback.
                fs.unlink(f"{backup_rel}/{_LEGACY_JOURNAL_IN_ROOT}", missing_ok=True)
                log.append(f"  • backed up existing .claude/ -> {backup_rel}")
            _apply_validated_stage(
                stage_fs,
                inventory,
                fs,
                transaction_rel=transaction.transaction_rel,
                force=force,
                log=log,
            )
            _verify_stage_inventory(transaction_stage, inventory)
            _validate_manifest(fs.root, strict=True)
    return log


def preview_install(
    src: Path, target: Path, plan: ResolvedPlan
) -> tuple[list[str], list[str]]:
    """Compute what :func:`install_sdlc` would write, without touching ``target``.

    Runs the real installer into a throwaway temporary directory (``force=True`` so it always writes
    the full fresh-install set), captures its per-component log, and walks the temp tree to list the
    files that would be created. The temp dir is discarded before returning, so the caller's project
    is never modified. Reusing the real installer keeps the preview from ever drifting from actual
    install behavior — there is no second code path to keep in sync.

    Args:
        src: Payload root (same as :func:`install_sdlc`).
        target: The project that *would* be installed into — used to label the render context
            (project name) and inspected read-only for its real package-manager commands (see
            ``detect_target``). It is never written to.
        plan: The resolved install plan.

    Returns:
        ``(log_lines, would_write_paths)`` — the installer's per-component log, and the sorted list of
        file paths (relative to the project root) that a fresh install would create.
    """
    # Pin the project name to the real target so the previewed context matches a real install
    # (install_sdlc uses setdefault, so this wins over the sandbox dir name).
    plan.context.setdefault("project_name", target.name)
    with tempfile.TemporaryDirectory(prefix="claude-kit-dryrun-") as tmp:
        sandbox = Path(tmp).resolve()
        # Detect from the REAL target, not the empty sandbox, so the preview matches a real install.
        log = install_sdlc(src, sandbox, plan, force=True, detect_target=target)
        paths = sorted(
            str(p.relative_to(sandbox)) for p in sandbox.rglob("*") if p.is_file()
        )
    return log, paths
