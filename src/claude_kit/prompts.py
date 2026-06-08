"""Interactive (and non-interactive) selection of an init configuration.

Produces a :class:`~claude_kit.models.Selection` three ways: ordered interactive prompts, the
catalog defaults (``--defaults``), or a YAML config file (``--config``). The prompt order matches
the spec: frontend framework → frontend language → backend language → backend framework → database →
SDLC profile → MCP integrations. (The target path is handled by the CLI before prompting.)

I/O uses ``input``/``print`` so it is trivially testable via a Typer ``CliRunner(input=...)`` or by
monkeypatching ``builtins.input``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from claude_kit import catalog
from claude_kit.models import Selection


def _ask(prompt: str, default: str) -> str:
    """Prompt for a single value with a default, tolerant of EOF (non-interactive) input."""
    try:
        resp = input(f"{prompt} [{default}]: ").strip()
    except EOFError:
        return default
    return resp or default


def _choose_one(title: str, options: list[dict[str, Any]], default: str) -> str:
    """Render a numbered menu of live options (planned ones shown but not selectable).

    Args:
        title: Section heading.
        options: Each dict has ``id``, ``label`` and may have ``status`` (``"planned"`` = disabled).
        default: The default option id (must be live).

    Returns:
        The chosen option id.
    """
    live = [o for o in options if o.get("status", "live") != "planned"]
    print(f"\n{title}")
    for n, o in enumerate(live, 1):
        mark = "  (default)" if o["id"] == default else ""
        print(f"  {n}) {o['label']}{mark}")
    for o in options:
        if o.get("status") == "planned":
            print(f"  -) {o['label']} (coming soon)")
    valid = {o["id"] for o in live}
    while True:
        resp = _ask("  choose", default)
        if resp in valid:
            return resp
        if resp.isdigit() and 1 <= int(resp) <= len(live):
            return live[int(resp) - 1]["id"]
        print("  please enter one of the listed ids or numbers")


def _choose_many(title: str, options: list[dict[str, Any]]) -> list[str]:
    """Render a menu and read a comma/space-separated multi-selection (empty = none)."""
    print(f"\n{title} (comma-separated ids or numbers; empty = none)")
    for n, o in enumerate(options, 1):
        print(f"  {n}) {o['id']} — {o['label']}")
    resp = _ask("  select", "none")
    if resp.lower() in ("", "none"):
        return []
    chosen: list[str] = []
    by_id = {o["id"]: o["id"] for o in options}
    for tok in resp.replace(",", " ").split():
        if tok in by_id:
            chosen.append(tok)
        elif tok.isdigit() and 1 <= int(tok) <= len(options):
            chosen.append(options[int(tok) - 1]["id"])
        else:
            print(f"  (ignoring unknown selection: {tok})")
    # de-dup, preserve order
    seen: set[str] = set()
    return [c for c in chosen if not (c in seen or seen.add(c))]


def interactive(payload_root: str | Path) -> Selection:
    """Run the ordered prompts and return the chosen :class:`Selection`."""
    opts = catalog.list_options(payload_root)
    dflt = catalog.defaults(payload_root)

    fe = _choose_one("Frontend framework", opts["frontend"], dflt.frontend_framework)
    fe_entry = next(o for o in opts["frontend"] if o["id"] == fe)
    langs = fe_entry.get("languages", []) or ["typescript"]
    lang_options = [{"id": lang_id, "label": lang_id} for lang_id in langs]
    fe_lang = _choose_one(
        "Frontend language",
        lang_options,
        fe_entry.get("default_language", "typescript"),
    )

    be = _choose_one("Backend language", opts["backend"], dflt.backend_language)
    be_entry = next(o for o in opts["backend"] if o["id"] == be)
    be_fw = _choose_one(
        "Backend framework",
        be_entry.get("frameworks", []),
        be_entry.get("default_framework", ""),
    )

    db = _choose_one("Database", opts["database"], dflt.database)
    profile = _choose_one("SDLC profile", opts["profiles"], dflt.profile)
    mcp = _choose_many("Optional MCP integrations", opts["mcp"])

    return Selection(
        frontend_framework=fe,
        frontend_language=fe_lang,
        backend_language=be,
        backend_framework=be_fw,
        database=db,
        profile=profile,
        mcp=mcp,
    )


def from_config(config_path: str | Path, payload_root: str | Path) -> Selection:
    """Build a :class:`Selection` from a YAML config file (``--config``).

    Accepts either flat keys (matching :class:`Selection` fields) or a friendly nested form::

        frontend: { framework: react, language: typescript }
        backend:  { language: python, framework: fastapi }
        database: postgres
        profile:  standard
        mcp:      [github]

    Missing keys fall back to the catalog defaults.
    """
    data = yaml.safe_load(Path(config_path).read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError("config file did not parse to a mapping")
    dflt = catalog.defaults(payload_root)

    fe = data.get("frontend", {})
    be = data.get("backend", {})
    flat = {
        "frontend_framework": data.get("frontend_framework")
        or (fe.get("framework") if isinstance(fe, dict) else fe)
        or dflt.frontend_framework,
        "frontend_language": data.get("frontend_language")
        or (fe.get("language") if isinstance(fe, dict) else None)
        or dflt.frontend_language,
        "backend_language": data.get("backend_language")
        or (be.get("language") if isinstance(be, dict) else be)
        or dflt.backend_language,
        "backend_framework": data.get("backend_framework")
        or (be.get("framework") if isinstance(be, dict) else None)
        or dflt.backend_framework,
        "database": data.get("database") or dflt.database,
        "profile": data.get("profile") or dflt.profile,
        "mcp": data.get("mcp") or [],
    }
    return Selection.from_dict(flat)
