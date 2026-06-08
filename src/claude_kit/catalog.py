"""Catalog loader + resolver — turns a :class:`~claude_kit.models.Selection` into a concrete
:class:`~claude_kit.models.ResolvedPlan` with **no hard-coded branching**.

Everything selectable lives in ``catalog/{stacks,profiles,mcp}.yaml``. Adding a framework, database,
profile, or MCP server is a YAML edit (plus a ``templates/stacks/<stack_dir>/`` folder for overlay
content); this module never needs to change.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from claude_kit import hooks as hooks_mod
from claude_kit.models import ResolvedPlan, Selection

#: Canonical backend command keys surfaced in CLAUDE.md (defaulted to "" so templates never break).
_BACKEND_CMD_KEYS = (
    "install",
    "dev",
    "test",
    "lint",
    "format",
    "migrate",
    "make_migration",
)
#: Canonical frontend command keys surfaced in CLAUDE.md.
_FRONTEND_CMD_KEYS = ("install", "dev", "test", "lint", "typecheck", "build")


def catalog_dir(payload_root: Path) -> Path:
    """Return the ``catalog/`` directory inside a payload root."""
    return Path(payload_root) / "catalog"


def _load(payload_root: Path, name: str) -> dict[str, Any]:
    """Load and parse a catalog YAML file by name (e.g. ``"stacks.yaml"``)."""
    path = catalog_dir(payload_root) / name
    if not path.is_file():
        raise FileNotFoundError(f"catalog file not found: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"catalog file {name} did not parse to a mapping")
    return data


def _dedup(items: list[str]) -> list[str]:
    """Return ``items`` with duplicates removed, order preserved."""
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def available(payload_root: Path) -> dict[str, list[str]]:
    """Discover the installable agents/skills/hooks present in a payload root.

    Used to expand the ``all`` token in profiles and to validate profile membership.

    Returns:
        Mapping with keys ``agents`` (agent file stems), ``skills`` (skill dir names, excluding
        ``_references``), and ``hooks`` (every registered hook id).
    """
    root = Path(payload_root)
    agents_dir = root / "agents"
    skills_dir = root / "skills"
    agents = (
        sorted(p.stem for p in agents_dir.glob("*.md")) if agents_dir.is_dir() else []
    )
    skills = (
        sorted(
            p.name
            for p in skills_dir.iterdir()
            if p.is_dir() and not p.name.startswith("_") and (p / "SKILL.md").is_file()
        )
        if skills_dir.is_dir()
        else []
    )
    return {"agents": agents, "skills": skills, "hooks": hooks_mod.all_ids()}


# --- selection lookups (raise ValueError on unknown / not-yet-shipped choices) --------------------


def _frontend(stacks: dict[str, Any], framework: str) -> dict[str, Any]:
    fws = stacks.get("frontend", {}).get("frameworks", {})
    fw = fws.get(framework)
    if fw is None:
        raise ValueError(
            f"unknown frontend framework {framework!r} (choices: {', '.join(fws)})"
        )
    if fw.get("status") == "planned":
        raise ValueError(
            f"frontend framework {framework!r} is planned but not yet available"
        )
    return fw


def _backend(
    stacks: dict[str, Any], language: str, framework: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    langs = stacks.get("backend", {}).get("languages", {})
    lang = langs.get(language)
    if lang is None:
        raise ValueError(
            f"unknown backend language {language!r} (choices: {', '.join(langs)})"
        )
    if lang.get("status") == "planned":
        raise ValueError(
            f"backend language {language!r} is planned but not yet available"
        )
    fws = lang.get("frameworks", {})
    fw = fws.get(framework)
    if fw is None:
        raise ValueError(
            f"unknown backend framework {framework!r} for {language} (choices: {', '.join(fws)})"
        )
    if fw.get("status") == "planned":
        raise ValueError(
            f"backend framework {framework!r} is planned but not yet available"
        )
    return lang, fw


def _database(stacks: dict[str, Any], database: str) -> dict[str, Any]:
    opts = stacks.get("database", {}).get("options", {})
    db = opts.get(database)
    if db is None:
        raise ValueError(f"unknown database {database!r} (choices: {', '.join(opts)})")
    return db


def _resolve_profile(
    profiles: dict[str, Any], name: str, avail: dict[str, list[str]]
) -> dict[str, list[str]]:
    """Resolve a profile's agents/skills/gates/hooks, honouring ``inherit:`` and the ``all`` token."""
    table = profiles.get("profiles", {})
    prof = table.get(name)
    if prof is None:
        raise ValueError(f"unknown profile {name!r} (choices: {', '.join(table)})")

    base: dict[str, list[str]] = {"agents": [], "skills": [], "gates": [], "hooks": []}
    if prof.get("inherit"):
        base = _resolve_profile(profiles, prof["inherit"], avail)

    out: dict[str, list[str]] = {}
    for key in ("agents", "skills", "gates", "hooks"):
        val = prof.get(key)
        if val == "all":
            out[key] = list(avail.get(key, base[key]))
        elif val is None:
            out[key] = list(base[key])
        else:
            out[key] = _dedup(list(base[key]) + list(val))
    return out


def _build_context(
    sel: Selection,
    frontend: dict[str, Any],
    backend_lang: dict[str, Any],
    backend_fw: dict[str, Any],
    database: dict[str, Any],
    profiles: dict[str, Any],
) -> dict[str, str]:
    """Build the flat string context used to render CLAUDE.md / README from the selection."""
    fe_cmds = frontend.get("commands", {})
    be_cmds = backend_fw.get("commands", {})
    profile_label = (
        profiles.get("profiles", {}).get(sel.profile, {}).get("label", sel.profile)
    )
    ctx: dict[str, str] = {
        "frontend_framework": sel.frontend_framework,
        "frontend_label": str(frontend.get("label", sel.frontend_framework)),
        "frontend_language": sel.frontend_language,
        "backend_language": sel.backend_language,
        "backend_language_label": str(backend_lang.get("label", sel.backend_language)),
        "backend_framework": sel.backend_framework,
        "backend_label": str(backend_fw.get("label", sel.backend_framework)),
        "database": sel.database,
        "db": sel.database,
        "db_label": str(database.get("label", sel.database)),
        "profile": sel.profile,
        "profile_label": str(profile_label),
        "mcp_list": ", ".join(sel.mcp) if sel.mcp else "none",
        "frontend_overlay_rule": (frontend.get("overlay_rules") or [""])[0],
        "backend_overlay_rule": (backend_fw.get("overlay_rules") or [""])[0],
        "db_overlay_rule": (database.get("overlay_rules") or [""])[0],
    }
    for key in _BACKEND_CMD_KEYS:
        ctx[f"backend_{key}_cmd"] = str(be_cmds.get(key, ""))
    for key in _FRONTEND_CMD_KEYS:
        ctx[f"frontend_{key}_cmd"] = str(fe_cmds.get(key, ""))
    return ctx


def resolve(payload_root: str | Path, selection: Selection) -> ResolvedPlan:
    """Resolve a :class:`Selection` into a concrete :class:`ResolvedPlan`.

    Args:
        payload_root: Payload root containing ``catalog/``, ``agents/``, ``skills/``.
        selection: The user's choices.

    Returns:
        The install plan: agent/skill/hook subsets, overlay rules+agents, gates, MCP configs,
        per-stack dirs, and the render context.

    Raises:
        ValueError: If any selected stack/profile is unknown or not yet shipped.
        FileNotFoundError: If a catalog file is missing.
    """
    payload_root = Path(payload_root)
    stacks = _load(payload_root, "stacks.yaml")
    profiles = _load(payload_root, "profiles.yaml")
    mcp = _load(payload_root, "mcp.yaml")

    frontend = _frontend(stacks, selection.frontend_framework)
    backend_lang, backend_fw = _backend(
        stacks, selection.backend_language, selection.backend_framework
    )
    database = _database(stacks, selection.database)

    avail = available(payload_root)
    prof = _resolve_profile(profiles, selection.profile, avail)

    overlay_rules = _dedup(
        list(frontend.get("overlay_rules", []))
        + list(backend_fw.get("overlay_rules", []))
        + list(database.get("overlay_rules", []))
    )
    overlay_agents = _dedup(
        list(frontend.get("overlay_agents", []))
        + list(backend_fw.get("overlay_agents", []))
        + list(database.get("overlay_agents", []))
    )
    skills = _dedup(
        prof["skills"]
        + list(frontend.get("skills", []))
        + list(backend_fw.get("skills", []))
        + list(database.get("skills", []))
    )

    mcp_servers: dict[str, dict[str, Any]] = {}
    servers = mcp.get("servers", {})
    for sid in selection.mcp:
        if sid not in servers:
            raise ValueError(
                f"unknown MCP server {sid!r} (choices: {', '.join(servers)})"
            )
        mcp_servers[sid] = servers[sid]["config"]

    stack_dirs = {
        "frontend": str(frontend.get("stack_dir", "")),
        "backend": str(backend_fw.get("stack_dir", "")),
        "database": str(database.get("stack_dir", "")),
    }

    return ResolvedPlan(
        selection=selection,
        agents=_dedup(prof["agents"]),
        skills=skills,
        overlay_rules=overlay_rules,
        overlay_agents=overlay_agents,
        hooks=prof["hooks"],
        gates=prof["gates"],
        mcp_servers=mcp_servers,
        context=_build_context(
            selection, frontend, backend_lang, backend_fw, database, profiles
        ),
        stack_dirs=stack_dirs,
    )


def defaults(payload_root: str | Path) -> Selection:
    """Return the default :class:`Selection` (every catalog default, no MCP)."""
    payload_root = Path(payload_root)
    stacks = _load(payload_root, "stacks.yaml")
    profiles = _load(payload_root, "profiles.yaml")
    fe_default = stacks["frontend"]["default"]
    be_lang_default = stacks["backend"]["default"]
    be_lang = stacks["backend"]["languages"][be_lang_default]
    be_fw_default = be_lang["default_framework"]
    fe = stacks["frontend"]["frameworks"][fe_default]
    return Selection(
        frontend_framework=fe_default,
        frontend_language=fe.get("languages", {}).get("default", "typescript"),
        backend_language=be_lang_default,
        backend_framework=be_fw_default,
        database=stacks["database"]["default"],
        profile=profiles.get("default", "standard"),
        mcp=[],
    )


def list_options(payload_root: str | Path) -> dict[str, Any]:
    """Return a structured view of every selectable option (for ``list-options`` and prompts)."""
    payload_root = Path(payload_root)
    stacks = _load(payload_root, "stacks.yaml")
    profiles = _load(payload_root, "profiles.yaml")
    mcp = _load(payload_root, "mcp.yaml")

    def _live(entry: dict[str, Any]) -> bool:
        return entry.get("status") != "planned"

    frontends = [
        {
            "id": fid,
            "label": fw.get("label", fid),
            "status": fw.get("status", "live"),
            "languages": fw.get("languages", {}).get("options", []),
            "default_language": fw.get("languages", {}).get("default", ""),
        }
        for fid, fw in stacks["frontend"]["frameworks"].items()
    ]
    backends = []
    for lid, lang in stacks["backend"]["languages"].items():
        backends.append(
            {
                "id": lid,
                "label": lang.get("label", lid),
                "status": lang.get("status", "live"),
                "default_framework": lang.get("default_framework", ""),
                "frameworks": [
                    {
                        "id": fid,
                        "label": fw.get("label", fid),
                        "status": fw.get("status", "live"),
                    }
                    for fid, fw in lang.get("frameworks", {}).items()
                ],
            }
        )
    databases = [
        {"id": did, "label": db.get("label", did)}
        for did, db in stacks["database"]["options"].items()
    ]
    profile_list = [
        {"id": pid, "label": p.get("label", pid)}
        for pid, p in profiles["profiles"].items()
    ]
    mcp_list = [
        {"id": sid, "label": s.get("label", sid)}
        for sid, s in mcp.get("servers", {}).items()
    ]
    return {
        "frontend": frontends,
        "backend": backends,
        "database": databases,
        "profiles": profile_list,
        "mcp": mcp_list,
        "live": {
            "frontend": [f for f in frontends if _live(f)],
            "databases": databases,
            "profiles": profile_list,
        },
    }
