"""Installer — writes a resolved claude-kit configuration into a target project.

Given a :class:`~claude_kit.models.ResolvedPlan` (from :func:`claude_kit.catalog.resolve`), this
module copies the profile's agent/skill/hook **subset**, the core rules, the selected stack
**overlay** rules + agents, assembles ``.claude/settings.json`` from the chosen hooks, optionally
writes ``.mcp.json``, installs artifact templates and a tuned ``CLAUDE.md`` + ``README.claude-sdlc.md``,
creates gitignored runtime dirs, and records per-file checksums in ``.claude/config/init-options.json``
for safe upgrades. It writes **no application code and no Docker** — configuration only.

``install_sdlc`` is the single spine shared by the pip CLI and (via a thin fallback) the plugin.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from contextlib import ExitStack
from importlib.resources import as_file, files
from pathlib import Path
from typing import Any

import yaml

from claude_kit import __version__, detect
from claude_kit import hooks as hooks_mod
from claude_kit.models import FileRecord, InitOptions, ResolvedPlan
from claude_kit.render import render_text

#: Marker in the generic CLAUDE.md whose section is replaced with the stack-specific block.
_STACK_MARKER = "## Project-specific rules"

#: Selective .gitignore entries for a scaffolded project (commit the rest of .claude/).
GITIGNORE_ENTRIES = (
    ".claude/settings.local.json",
    "CLAUDE.local.md",
    ".claude/state/",
    ".claude/tmp/",
    # upgrade/merge artifacts written by `claude-kit upgrade` — never commit these
    ".claude-kit.bak-*/",
    "*.claude-kit",
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


def _copy_tree(src: Path, dest: Path) -> None:
    """Replace ``dest`` with a copy of ``src`` (directory)."""
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(src, dest)


def _copy_user_file(
    src: Path, dest: Path, *, force: bool, log: list[str], label: str
) -> None:
    """Copy a user-editable file, writing a ``.claude-kit`` sidecar instead of clobbering edits."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and not force:
        sidecar = dest.with_name(dest.name + ".claude-kit")
        shutil.copy2(src, sidecar)
        log.append(
            f"  • {label} exists — wrote {sidecar.name} (use --force to overwrite)"
        )
    else:
        shutil.copy2(src, dest)
        log.append(f"  • {label} installed")


def _write_user_text(
    dest: Path, text: str, *, force: bool, log: list[str], label: str
) -> None:
    """Write rendered text to a user-editable file, sidecar'ing instead of clobbering edits."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and not force:
        sidecar = dest.with_name(dest.name + ".claude-kit")
        sidecar.write_text(text, encoding="utf-8")
        log.append(
            f"  • {label} exists — wrote {sidecar.name} (use --force to overwrite)"
        )
    else:
        dest.write_text(text, encoding="utf-8")
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
        candidate = stacks / stack_dir / kind_dir / name
        if candidate.is_file():
            return candidate
    return None


# --- install steps ---------------------------------------------------------------------------------


def _install_rules(src: Path, dest: Path, plan: ResolvedPlan, log: list[str]) -> None:
    """Install all core rules plus the selected overlay rules into ``.claude/rules/``."""
    rules_dest = dest / "rules"
    _copy_tree(src / "rules", rules_dest)
    log.append(f"  • rules/ ({sum(1 for _ in rules_dest.glob('*.md'))} core)")
    for name in plan.overlay_rules:
        found = _find_overlay(src, plan.stack_dirs, "rules", name)
        if found:
            shutil.copy2(found, rules_dest / name)
            log.append(f"  • overlay rule: rules/{name}")
        else:
            log.append(f"  ! overlay rule missing (skipped): {name}")


def _install_agents(src: Path, dest: Path, plan: ResolvedPlan, log: list[str]) -> None:
    """Install the profile's core-agent subset plus selected overlay agents into ``.claude/agents/``."""
    agents_dest = dest / "agents"
    agents_dest.mkdir(parents=True, exist_ok=True)
    installed = 0
    for name in plan.agents:
        srcf = src / "agents" / f"{name}.md"
        if srcf.is_file():
            shutil.copy2(srcf, agents_dest / f"{name}.md")
            installed += 1
        else:
            log.append(f"  ! agent missing (skipped): {name}")
    log.append(f"  • agents/ ({installed} of {len(plan.agents)} selected)")
    for name in plan.overlay_agents:
        found = _find_overlay(src, plan.stack_dirs, "agents", f"{name}.md")
        if found:
            shutil.copy2(found, agents_dest / f"{name}.md")
            log.append(f"  • overlay agent: agents/{name}.md")
        else:
            log.append(f"  ! overlay agent missing (skipped): {name}")


def _install_skills(src: Path, dest: Path, plan: ResolvedPlan, log: list[str]) -> None:
    """Install the profile's skill subset into ``.claude/skills/``."""
    skills_dest = dest / "skills"
    skills_dest.mkdir(parents=True, exist_ok=True)
    installed = 0
    for name in plan.skills:
        srcd = src / "skills" / name
        if (srcd / "SKILL.md").is_file():
            _copy_tree(srcd, skills_dest / name)
            installed += 1
        else:
            log.append(f"  ! skill missing (skipped): {name}")
    log.append(f"  • skills/ ({installed} of {len(plan.skills)} selected)")
    # _references/ is shared support content (not a profile-selected skill), but several SKILL.md
    # files link into .claude/skills/_references/…; copy it so those "See Also" links resolve.
    refs_src = src / "skills" / "_references"
    if refs_src.is_dir():
        _copy_tree(refs_src, skills_dest / "_references")
        log.append("  • skills/_references/ (shared deep-dive references)")


def _install_org(src: Path, dest: Path, plan: ResolvedPlan, log: list[str]) -> None:
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
        if (srcd / "SKILL.md").is_file():
            _copy_tree(srcd, dest / "skills" / name)
        else:
            log.append(f"  ! org skill missing (skipped): {name}")
    for name in org.org_agents:
        srcf = org_src / "agents" / f"{name}.md"
        if srcf.is_file():
            shutil.copy2(srcf, dest / "agents" / f"{name}.md")
        else:
            log.append(f"  ! org agent missing (skipped): {name}")
    for name in org.org_rules:
        srcf = org_src / "rules" / name
        if srcf.is_file():
            shutil.copy2(srcf, dest / "rules" / name)
        else:
            log.append(f"  ! org rule missing (skipped): {name}")
    log.append(
        f"  • org layer: {len(org.org_skills)} skills, {len(org.org_agents)} persona agents, "
        f"{len(org.org_rules)} rules (autonomy={org.autonomy})"
    )

    if org.packs:
        packs_dest = dest / "org-packs"
        packs_dest.mkdir(parents=True, exist_ok=True)
        index = org_src / "README.md"
        if index.is_file():
            shutil.copy2(index, packs_dest / "README.md")
        installed = 0
        for pack in org.packs:
            srcd = org_src / "packs" / pack
            if (srcd / "pack.yaml").is_file():
                _copy_tree(srcd, packs_dest / pack)
                installed += 1
            else:
                log.append(f"  ! org pack missing (skipped): {pack}")
        log.append(f"  • org-packs/ ({installed} pack manifests)")


def _install_hooks_and_settings(
    src: Path, dest: Path, plan: ResolvedPlan, *, force: bool, log: list[str]
) -> None:
    """Copy the scripts needed by selected hooks and assemble ``.claude/settings.json``."""
    hooks_dest = dest / "hooks"
    hooks_dest.mkdir(parents=True, exist_ok=True)
    for script in hooks_mod.scripts_for(plan.hooks):
        srcf = src / "hooks" / "scripts" / script
        if srcf.is_file():
            shutil.copy2(srcf, hooks_dest / script)
            (hooks_dest / script).chmod(0o755)
    log.append(f"  • hooks/ ({sum(1 for _ in hooks_dest.glob('*.sh'))} scripts)")
    settings = hooks_mod.build_settings(plan.hooks)
    _write_user_text(
        dest / "settings.json",
        json.dumps(settings, indent=2) + "\n",
        force=force,
        log=log,
        label="settings.json",
    )


def _install_artifact_templates(src: Path, dest: Path, log: list[str]) -> None:
    """Install the artifact markdown templates into ``.claude/templates/``."""
    srcd = src / "templates" / "artifacts"
    if not srcd.is_dir():
        return
    tdest = dest / "templates"
    _copy_tree(srcd, tdest)
    log.append(
        f"  • templates/ ({sum(1 for _ in tdest.glob('*.md'))} artifact templates)"
    )


def _write_claude_md(
    src: Path, target: Path, plan: ResolvedPlan, *, force: bool, log: list[str]
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
    _write_user_text(claude_md, base, force=force, log=log, label="CLAUDE.md")


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
    target: Path, plan: ResolvedPlan, *, force: bool, log: list[str]
) -> None:
    """Write a project-root ``.mcp.json`` (+ a derived ``.mcp.lock.json``) if MCP servers chosen."""
    lock = target / ".mcp.lock.json"
    if not plan.mcp_servers:
        # No servers selected: drop a now-orphaned lockfile, but only when there is no ``.mcp.json``
        # beside it to describe — never delete a file from a user's own hand-written MCP config pair.
        if lock.is_file() and not (target / ".mcp.json").is_file():
            lock.unlink()
            log.append("  • removed orphaned .mcp.lock.json (no MCP servers)")
        return
    mcp_existed = (target / ".mcp.json").is_file()
    doc = {"mcpServers": plan.mcp_servers}
    _write_user_text(
        target / ".mcp.json",
        json.dumps(doc, indent=2) + "\n",
        force=force,
        log=log,
        label=".mcp.json",
    )
    # The lockfile is derived from .mcp.json. Regenerate it only when we actually (over)wrote
    # .mcp.json — a fresh write or --force. If the user's own .mcp.json was preserved (written as a
    # sidecar), leave their lockfile untouched so the two never describe different server sets.
    if force or not mcp_existed:
        lock.write_text(
            json.dumps(_mcp_lock(plan.mcp_servers), indent=2) + "\n", encoding="utf-8"
        )
        log.append("  • .mcp.lock.json (resolved MCP versions)")


def _write_readme(
    src: Path, target: Path, plan: ResolvedPlan, *, force: bool, log: list[str]
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
        force=force,
        log=log,
        label="README.claude-sdlc.md",
    )


def _update_gitignore(target: Path, log: list[str]) -> None:
    """Append the selective claude-kit gitignore entries (idempotently)."""
    gi = target / ".gitignore"
    existing = gi.read_text(encoding="utf-8").splitlines() if gi.is_file() else []
    have = set(existing)
    missing = [e for e in GITIGNORE_ENTRIES if e not in have]
    if not missing:
        return
    lines = list(existing)
    if lines and lines[-1].strip():
        lines.append("")
    lines.append("# claude-kit runtime + local overrides")
    lines.extend(missing)
    gi.write_text("\n".join(lines) + "\n", encoding="utf-8")
    log.append(f"  • .gitignore (+{len(missing)} entries)")


def _seed_runtime_dirs(dest: Path, log: list[str]) -> None:
    """Create gitignored runtime dirs (state/, tmp/) with a .gitkeep so they exist but stay empty."""
    for name in ("state", "tmp"):
        d = dest / name
        d.mkdir(parents=True, exist_ok=True)
        (d / ".gitkeep").write_text("", encoding="utf-8")


def _seed_agent_memory(src: Path, dest: Path, log: list[str]) -> None:
    """Install the agent-memory seed (only if the project doesn't already have one)."""
    if (dest / "agent-memory").exists():
        return
    seed = src / "templates" / "agent-memory"
    if seed.is_dir():
        _copy_tree(seed, dest / "agent-memory")
        log.append("  • agent-memory/ seed")


def _classify_owner(rel: str, plan: ResolvedPlan) -> str:
    """Classify a relative path as kit / overlay / user-editable for upgrade policy."""
    user_editable = {
        "CLAUDE.md",
        "README.claude-sdlc.md",
        ".mcp.json",
        ".claude/settings.json",
        ".claude/CONTINUITY.md",
    }
    if rel in user_editable or rel.startswith(".claude/agent-memory/"):
        return "user-editable"
    overlay_paths = {f".claude/rules/{r}" for r in plan.overlay_rules}
    overlay_paths |= {f".claude/agents/{a}.md" for a in plan.overlay_agents}
    if rel in overlay_paths:
        return "overlay"
    return "kit"


def _record_files(target: Path, plan: ResolvedPlan) -> list[FileRecord]:
    """Compute checksum + ownership records for every installed file (excluding runtime/self)."""
    records: list[FileRecord] = []
    candidates: list[Path] = []
    for top in ("CLAUDE.md", "README.claude-sdlc.md", ".mcp.json", ".mcp.lock.json"):
        p = target / top
        if p.is_file():
            candidates.append(p)
    dest = target / ".claude"
    skip_dirs = {dest / "state", dest / "tmp"}
    init_options = dest / "config" / "init-options.json"
    for p in sorted(dest.rglob("*")):
        if not p.is_file() or p == init_options:
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


def _write_config(src: Path, target: Path, plan: ResolvedPlan, log: list[str]) -> None:
    """Write the resolved catalog snapshot and init-options.json (with file checksums)."""
    config_dest = target / ".claude" / "config"
    config_dest.mkdir(parents=True, exist_ok=True)
    snapshot = {
        "selection": plan.selection.to_dict(),
        "agents": plan.agents,
        "skills": plan.skills,
        "overlay_rules": plan.overlay_rules,
        "overlay_agents": plan.overlay_agents,
        "hooks": plan.hooks,
        "gates": plan.gates,
        "mcp": list(plan.mcp_servers),
        "org": plan.org.to_dict() if plan.org else None,
        "detected_commands": plan.detected_commands or {},
    }
    (config_dest / "stack-catalog.snapshot.yaml").write_text(
        yaml.safe_dump(snapshot, sort_keys=False), encoding="utf-8"
    )
    options = InitOptions(
        claude_kit_version=__version__,
        selection=plan.selection,
        files=_record_files(target, plan),
    )
    (config_dest / "init-options.json").write_text(
        json.dumps(options.to_dict(), indent=2) + "\n", encoding="utf-8"
    )
    log.append("  • config/ (init-options.json + stack snapshot)")


def install_sdlc(
    src: Path,
    target: Path,
    plan: ResolvedPlan,
    *,
    force: bool = False,
    log: list[str] | None = None,
    detect_target: str | Path | None = None,
) -> list[str]:
    """Install a resolved claude-kit configuration into ``target``.

    Args:
        src: Payload root (contains ``rules/ agents/ skills/ hooks/ templates/ catalog/``).
        target: Project root to install into.
        plan: The resolved install plan from :func:`claude_kit.catalog.resolve`.
        force: Overwrite user-editable files (CLAUDE.md, settings.json, .mcp.json) instead of
            writing ``.claude-kit`` sidecars.
        log: Optional list to append human-readable log lines to.
        detect_target: Repo to inspect for real package-manager commands (defaults to ``target``).
            The previewer passes the real project here while installing into a throwaway sandbox, so
            a dry run reflects the repo's tooling rather than the empty sandbox.

    Returns:
        The log list, one line per installed component.
    """
    if log is None:
        log = []
    target = Path(target)
    dest = target / ".claude"
    dest.mkdir(parents=True, exist_ok=True)

    # Augment the render context with project identity + summary counts.
    plan.context.setdefault("project_name", target.resolve().name)
    plan.context["agent_count"] = str(len(plan.agents) + len(plan.overlay_agents))
    plan.context["skill_count"] = str(len(plan.skills))
    plan.context["overlay_rules_list"] = ", ".join(plan.overlay_rules) or "none"

    # Override generic catalog commands with the target repo's real package-manager commands.
    # Keyed on detect_target (the REAL project) so a preview into a sandbox still reflects the repo;
    # a no-op on an empty target keeps dry-run ≡ install.
    if plan.selection.detect_commands:
        detect_from = Path(detect_target) if detect_target is not None else target
        overrides = detect.detect_commands(detect_from, plan.selection)
        if overrides:
            plan.context.update(overrides)
            log.append(f"  • detected commands: {', '.join(sorted(overrides))}")
        plan.detected_commands = overrides

    _install_rules(src, dest, plan, log)
    _write_claude_md(src, target, plan, force=force, log=log)
    shutil.copy2(
        src / "templates" / "CONTINUITY.template.md", dest / "CONTINUITY.template.md"
    )
    _install_agents(src, dest, plan, log)
    _install_skills(src, dest, plan, log)
    _install_org(src, dest, plan, log)
    _seed_agent_memory(src, dest, log)
    _install_hooks_and_settings(src, dest, plan, force=force, log=log)
    _install_artifact_templates(src, dest, log)
    _write_mcp(target, plan, force=force, log=log)
    _write_readme(src, target, plan, force=force, log=log)
    _seed_runtime_dirs(dest, log)
    _update_gitignore(target, log)
    _write_config(src, target, plan, log)
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
        sandbox = Path(tmp)
        # Detect from the REAL target, not the empty sandbox, so the preview matches a real install.
        log = install_sdlc(src, sandbox, plan, force=True, detect_target=target)
        paths = sorted(
            str(p.relative_to(sandbox)) for p in sandbox.rglob("*") if p.is_file()
        )
    return log, paths
