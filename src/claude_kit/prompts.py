"""Interactive (and non-interactive) selection of an init configuration.

Produces a :class:`~claude_kit.models.Selection` three ways: ordered interactive prompts, the
catalog defaults (``--defaults``), or a YAML config file (``--config``). The prompt order matches
the spec: frontend framework → frontend language → backend language → backend framework → database →
SDLC profile → MCP integrations. (The target path is handled by the CLI before prompting.)

I/O uses ``input``/``print`` so it is trivially testable via a Typer ``CliRunner(input=...)`` or by
monkeypatching ``builtins.input``.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import yaml

from claude_kit import catalog
from claude_kit.models import Selection

#: Recognised top-level keys in a ``--config`` YAML — the friendly nested form plus the flat
#: Selection-field form. Anything else is a typo we reject rather than silently ignore.
_CONFIG_KEYS = {
    "frontend",
    "backend",
    "database",
    "profile",
    "capture_mode",
    "mcp",
    "scope",
    "teams",
    "autonomy",
    "review_strictness",
    "org",
    "org_packs",
    "detect_commands",
    "frontend_framework",
    "frontend_language",
    "backend_language",
    "backend_framework",
}


def _as_str_list(value: Any, field_name: str) -> list[str]:
    """Coerce a YAML scalar or sequence into a ``list[str]`` (a bare string becomes one element).

    Raises :class:`ValueError` for any other shape, so a typo like ``mcp: github`` is normalised to
    ``["github"]`` while ``mcp: {github: true}`` fails loudly instead of being iterated
    character-by-character (or key-by-key) deep inside :func:`catalog.resolve`.
    """
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple)):
        bad = [x for x in value if not isinstance(x, str)]
        if bad:
            raise ValueError(
                f"config {field_name!r} must be a list of strings; got {bad!r}"
            )
        return list(value)
    raise ValueError(
        f"config {field_name!r} must be a string or list of strings; "
        f"got {type(value).__name__}"
    )


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


def _ask_bool(prompt: str, default: bool) -> bool:
    """Prompt for a yes/no answer with a default, tolerant of EOF (non-interactive) input."""
    resp = _ask(f"{prompt} [y/n]", "y" if default else "n").strip().lower()
    if resp in ("y", "yes", "true", "1"):
        return True
    if resp in ("n", "no", "false", "0"):
        return False
    return default


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
    deduped: list[str] = []
    for c in chosen:
        if c not in seen:
            seen.add(c)
            deduped.append(c)
    return deduped


def interactive(payload_root: str | Path) -> Selection:
    """Run the ordered prompts and return the chosen :class:`Selection`."""
    opts = catalog.list_options(payload_root)
    dflt = catalog.defaults(payload_root)

    fe = _choose_one("Frontend framework", opts["frontend"], dflt.frontend_framework)
    fe_entry = next(o for o in opts["frontend"] if o["id"] == fe)
    langs = fe_entry.get("languages", [])
    if langs:
        lang_options = [{"id": lang_id, "label": lang_id} for lang_id in langs]
        fe_lang = _choose_one(
            "Frontend language",
            lang_options,
            fe_entry.get("default_language", "typescript"),
        )
    else:
        # A lane-less entry (e.g. "none") declares no languages — nothing to ask.
        fe_lang = fe_entry.get("default_language", "") or "none"

    be = _choose_one("Backend language", opts["backend"], dflt.backend_language)
    be_entry = next(o for o in opts["backend"] if o["id"] == be)
    be_fw = _choose_one(
        "Backend framework",
        be_entry.get("frameworks", []),
        be_entry.get("default_framework", ""),
    )

    db = _choose_one("Database", opts["database"], dflt.database)
    profile = _choose_one("SDLC profile", opts["profiles"], dflt.profile)

    # Learning-capture mode (the token-cost knob). This explicit question IS the consent gate for
    # the background capture job (it reads session transcript content) — every non-interactive
    # path stays `off` (capture.yaml `default`). The interactive preselection is the catalog's
    # `recommended` pick; lean preselects off (intentionally minimal). When stdin is not a TTY
    # (an agent's shell, a heredoc, EOF) nobody actually *saw* this question, so the
    # answer-yourself default must be off too — consent needs eyes on the prompt.
    cap = catalog.capture_mode_options(payload_root)
    capture_default = (
        "off" if profile == "lean" or not sys.stdin.isatty() else cap["recommended"]
    )
    capture_mode = _choose_one("Learning capture", cap["modes"], capture_default)

    mcp = _choose_many("Optional MCP integrations", opts["mcp"])

    # Usage scope — and, for organizations, the capability-layer questions.
    org = catalog.org_options(payload_root)
    scope = _choose_one("Usage scope", org["scopes"], org["defaults"]["scope"])
    teams: list[str] = []
    autonomy = org["defaults"]["autonomy"]
    review_strictness = org["defaults"]["strictness"]
    org_packs = True
    if scope == "organization":
        teams = _choose_many("Which teams will use this?", org["teams"])
        autonomy = _choose_one("Autonomy level", org["autonomy"], autonomy)
        review_strictness = _choose_one(
            "Review strictness", org["strictness"], review_strictness
        )
        org_packs = _ask_bool("Generate reusable org capability packs?", True)

    return Selection(
        frontend_framework=fe,
        frontend_language=fe_lang,
        backend_language=be,
        backend_framework=be_fw,
        database=db,
        profile=profile,
        capture_mode=capture_mode,
        mcp=mcp,
        scope=scope,
        teams=teams,
        autonomy=autonomy,
        review_strictness=review_strictness,
        org_packs=org_packs,
    )


def from_config(config_path: str | Path, payload_root: str | Path) -> Selection:
    """Build a :class:`Selection` from a YAML config file (``--config``).

    Accepts either flat keys (matching :class:`Selection` fields) or a friendly nested form::

        frontend: { framework: react, language: typescript }
        backend:  { language: python, framework: fastapi }
        database: postgres
        profile:  standard
        mcp:      [github]
        scope:    organization
        org:      { teams: [engineering, product], autonomy: autonomous-pr,
                    review_strictness: regulated, packs: true }

    Org fields may also be given flat (``scope``/``teams``/``autonomy``/``review_strictness``/
    ``org_packs``). Missing keys fall back to the catalog defaults — and a framework/language the
    config leaves out falls back to the **selected lane's** catalog default, exactly like the
    interactive flow: ``backend: go`` means go's ``net-http``, never the global default's
    ``fastapi``.
    """
    try:
        data = yaml.safe_load(Path(config_path).read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        # PyYAML's message spans lines but carries the line/column mark — keep it, one line.
        raise ValueError(
            f"config file is not valid YAML: {' '.join(str(exc).split())}"
        ) from exc
    if not isinstance(data, dict):
        raise ValueError("config file did not parse to a mapping")
    unknown = set(data) - _CONFIG_KEYS
    if unknown:
        raise ValueError(
            f"unknown config key(s): {', '.join(sorted(unknown))} "
            f"(recognised: {', '.join(sorted(_CONFIG_KEYS))})"
        )
    dflt = catalog.defaults(payload_root)
    org_defaults = catalog.org_options(payload_root)["defaults"]

    fe = data.get("frontend", {})
    be = data.get("backend", {})
    org = data.get("org", {})
    if not isinstance(org, dict):
        org = {}
    # YAML 1.1 parses bare off/no -> False and on/yes -> True; map an unquoted `capture_mode: off`
    # back to the "off" mode. A bare `on`/`true` is REJECTED, not guessed: since 0.76.0 the
    # default is off, so silently mapping True to the default would turn an explicit opt-IN into
    # a silent opt-OUT — the inverse consent failure.
    cap_mode = data.get("capture_mode")
    if isinstance(cap_mode, bool):
        if cap_mode is False:
            cap_mode = "off"
        else:
            raise ValueError(
                "config 'capture_mode: on/true' is ambiguous — name the mode you consent to "
                "(session-end, session-end-catchup, per-task) or 'off'; note unquoted on/off "
                "parse as YAML booleans"
            )
    # Normalise list-typed fields up front so a bare string (mcp: github) becomes ["github"] and a
    # wrong shape fails loudly here rather than being char-iterated inside catalog.resolve().
    mcp = _as_str_list(data.get("mcp"), "mcp")
    teams_raw = data.get("teams") if data.get("teams") is not None else org.get("teams")
    teams = _as_str_list(teams_raw, "teams")
    fe_fw = (
        data.get("frontend_framework")
        or (fe.get("framework") if isinstance(fe, dict) else fe)
        or dflt.frontend_framework
    )
    be_lang = (
        data.get("backend_language")
        or (be.get("language") if isinstance(be, dict) else be)
        or dflt.backend_language
    )
    # A language/framework the config leaves out defaults per the SELECTED lane's catalog data
    # (mirroring the interactive flow), not the global default Selection — otherwise
    # `backend: go` would silently pick up fastapi. An unknown lane id keeps the global
    # default here and fails loudly inside catalog.resolve().
    opts = catalog.list_options(payload_root)
    fe_lane = next((o for o in opts["frontend"] if o["id"] == fe_fw), None)
    be_lane = next((o for o in opts["backend"] if o["id"] == be_lang), None)
    fe_lang_default = (
        (fe_lane.get("default_language") or "none")
        if fe_lane is not None
        else dflt.frontend_language
    )
    be_fw_default = (
        be_lane.get("default_framework") if be_lane is not None else None
    ) or dflt.backend_framework
    flat = {
        "frontend_framework": fe_fw,
        "frontend_language": data.get("frontend_language")
        or (fe.get("language") if isinstance(fe, dict) else None)
        or fe_lang_default,
        "backend_language": be_lang,
        "backend_framework": data.get("backend_framework")
        or (be.get("framework") if isinstance(be, dict) else None)
        or be_fw_default,
        "database": data.get("database") or dflt.database,
        "profile": data.get("profile") or dflt.profile,
        "capture_mode": cap_mode or dflt.capture_mode,
        "mcp": mcp,
        "scope": data.get("scope") or org_defaults["scope"],
        "teams": teams,
        "autonomy": data.get("autonomy")
        or org.get("autonomy")
        or org_defaults["autonomy"],
        "review_strictness": data.get("review_strictness")
        or org.get("review_strictness")
        or org_defaults["strictness"],
    }
    # org_packs / org.packs: accept an explicit bool, else default True.
    packs = data.get("org_packs")
    if packs is None:
        packs = org.get("packs")
    flat["org_packs"] = True if packs is None else bool(packs)
    # detect_commands: accept an explicit bool, else default True (inspect the target repo for its
    # real package-manager commands). Set False in config to pin the generic catalog commands.
    detect = data.get("detect_commands")
    flat["detect_commands"] = True if detect is None else bool(detect)
    return Selection.from_dict(flat, strict=True)
