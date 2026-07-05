"""Validation and health checks for a scaffolded claude-kit configuration.

``validate`` performs structural checks (files present, JSON parses, frontmatter complete,
referenced overlays installed). Passing ``strict=True`` adds deep checks: settings.json hooks point
at installed, executable scripts on valid events; ``.mcp.json`` has a sane shape; the resolved stack
snapshot agrees with what's on disk; and the **bundled catalog** is referentially consistent
(profiles → existing agents/skills/hooks, stack overlay files present). ``doctor`` runs the strict
validate plus environment checks (git/jq available, hook scripts executable, runtime dirs gitignored)
and, with ``--mcp``, MCP command/env-var health. All return ``(ok, messages)`` so the CLI can print a
report and choose an exit code.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
from contextlib import ExitStack
from pathlib import Path
from typing import Callable

from claude_kit.models import UPGRADE_JOURNAL, InitOptions, UpgradeJournal

#: Claude Code hook event names. A settings.json hooks block keyed on anything else is suspect —
#: a typo'd event silently never fires — so strict validation flags unknown events.
KNOWN_EVENTS = frozenset(
    {
        "SessionStart",
        "UserPromptSubmit",
        "PreToolUse",
        "PostToolUse",
        "Stop",
        "SubagentStop",
        "PreCompact",
        "Notification",
        "SessionEnd",
    }
)

#: Extracts the script basenames a hook command runs from ``.claude/hooks/`` (inline guards match none).
_HOOK_SCRIPT_RE = re.compile(r"\.claude/hooks/([^\"'\s]+\.sh)")
#: Extracts ``${VAR}`` placeholders from an .mcp.json fragment (valid shell identifiers only — a
#: leading digit like ``${1}`` is a positional parameter, not an env var to warn about).
_ENV_VAR_RE = re.compile(r"\$\{([A-Za-z_]\w*)\}")


def _parse_frontmatter(text: str) -> dict[str, str] | None:
    """Return the frontmatter key/values at the top of a markdown file, or None if absent.

    Uses lenient line-based parsing (``key: value`` at column 0), deliberately mirroring Claude
    Code's own frontmatter reader rather than strict YAML. Real agent/skill files routinely carry
    a colon inside a ``description`` ("Read-only: routes fixes…") or a bracketed ``argument-hint``
    (``[optional: "x"]``); ``yaml.safe_load`` rejects both even though Claude Code accepts them, so
    validating with strict YAML would fail on valid files. Indented continuation lines, blanks, and
    comments are skipped — only the top-level scalar fields this module checks (``name``,
    ``description``) need to be recovered.
    """
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 3)
    if end == -1:
        return None
    data: dict[str, str] = {}
    for line in text[3:end].splitlines():
        if not line.strip() or line[0] in (" ", "\t", "#"):
            continue
        key, sep, value = line.partition(":")
        if sep:
            data[key.strip()] = value.strip()
    return data


def _sha256(path: Path) -> str:
    """Hex SHA-256 of a file's bytes (matches the digest recorded in init-options.json)."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_init_options(claude_dir: Path) -> tuple[InitOptions | None, str | None]:
    """Load ``init-options.json``, distinguishing *missing* from *corrupt*.

    Returns ``(options, None)`` on success; ``(None, "missing")`` when the file is absent; and
    ``(None, "corrupt: <detail>")`` when it exists but cannot be parsed. Callers can then surface a
    distinct, louder signal for a corrupt manifest (a real problem worth a FAIL) versus a missing
    one (an older install that merely predates upgrade tracking — a WARN).
    """
    path = claude_dir / "config" / "init-options.json"
    if not path.is_file():
        return None, "missing"
    try:
        return InitOptions.from_dict(json.loads(path.read_text(encoding="utf-8"))), None
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        return None, f"corrupt: {exc}"


def _load_init_options(claude_dir: Path) -> InitOptions | None:
    """Back-compat: the parsed options, or None for either a missing or corrupt manifest."""
    return _read_init_options(claude_dir)[0]


def validate(target: str | Path, *, strict: bool = False) -> tuple[bool, list[str]]:
    """Structurally validate the claude-kit config at ``target``.

    Args:
        target: Project root containing the ``.claude/`` to validate.
        strict: When True, add deep checks — settings.json hooks resolve to installed, executable
            scripts on valid events; ``.mcp.json`` shape; the stack snapshot agrees with installed
            files; and the bundled catalog is referentially consistent (see :func:`check_catalog`).

    Returns:
        ``(ok, messages)`` where each message is prefixed ``OK``/``WARN``/``FAIL`` and ``ok`` is
        False if any ``FAIL`` was recorded.
    """
    target = Path(target).expanduser().resolve()
    claude = target / ".claude"
    msgs: list[str] = []
    ok = True

    def fail(m: str) -> None:
        nonlocal ok
        ok = False
        msgs.append(f"FAIL  {m}")

    def warn(m: str) -> None:
        msgs.append(f"WARN  {m}")

    def good(m: str) -> None:
        msgs.append(f"OK    {m}")

    if not claude.is_dir():
        fail(f"no .claude/ directory in {target} — run `claude-kit init` here")
        return ok, msgs

    options, opt_err = _read_init_options(claude)
    if options is None:
        if opt_err == "missing":
            warn(
                "no .claude/config/init-options.json (validate/upgrade limited — "
                "re-run `claude-kit init` to start tracking)"
            )
        else:
            fail(
                f".claude/config/init-options.json is unreadable ({opt_err}) — repair the JSON "
                "or re-run `claude-kit init --force`"
            )
    else:
        good(
            f"init-options.json (schema v{options.schema_version}, kit {options.claude_kit_version})"
        )
        drifted: list[str] = []
        for rec in options.files:
            fp = target / rec.path
            if not fp.exists():
                fail(f"recorded file missing: {rec.path}")
            elif (
                rec.owner in ("kit", "overlay")
                and fp.is_file()
                and _sha256(fp) != rec.sha256
            ):
                drifted.append(rec.path)
        good(f"tracked files present ({len(options.files)} recorded)")
        if drifted:
            preview = ", ".join(sorted(drifted)[:3])
            more = "" if len(drifted) <= 3 else f" (+{len(drifted) - 3} more)"
            warn(
                f"{len(drifted)} kit-owned file(s) modified since install: {preview}{more} "
                "— run `claude-kit diff` to review (edits to user-editable files are not flagged)"
            )

    settings = claude / "settings.json"
    if settings.is_file():
        try:
            json.loads(settings.read_text(encoding="utf-8"))
            good("settings.json is valid JSON")
        except json.JSONDecodeError as exc:
            fail(f"settings.json is invalid JSON: {exc}")
    else:
        warn("no .claude/settings.json (hooks not configured)")

    agents_dir = claude / "agents"
    if agents_dir.is_dir():
        bad = [
            p.name
            for p in agents_dir.glob("*.md")
            if not (_parse_frontmatter(p.read_text(encoding="utf-8")) or {}).get("name")
            or not (_parse_frontmatter(p.read_text(encoding="utf-8")) or {}).get(
                "description"
            )
        ]
        if bad:
            fail(
                f"agents missing name/description frontmatter: {', '.join(sorted(bad))}"
            )
        else:
            good(
                f"agents/ frontmatter complete ({sum(1 for _ in agents_dir.glob('*.md'))} agents)"
            )
    else:
        warn("no .claude/agents/")

    skills_dir = claude / "skills"
    if skills_dir.is_dir():
        bad_skills = [
            d.name
            for d in skills_dir.iterdir()
            if d.is_dir()
            and (d / "SKILL.md").is_file()
            and not (
                _parse_frontmatter((d / "SKILL.md").read_text(encoding="utf-8")) or {}
            ).get("description")
        ]
        if bad_skills:
            fail(f"skills missing description: {', '.join(sorted(bad_skills))}")
        else:
            good(
                f"skills/ descriptions present "
                f"({sum(1 for d in skills_dir.iterdir() if d.is_dir() and (d / 'SKILL.md').is_file())} skills)"
            )

    rules_dir = claude / "rules"
    if not rules_dir.is_dir() or not any(rules_dir.glob("*.md")):
        fail("no .claude/rules/ content")
    else:
        good(f"rules/ present ({sum(1 for _ in rules_dir.glob('*.md'))} rules)")

    if strict:
        _strict_checks(claude, fail, warn, good)
        cat_ok, cat_msgs = check_catalog()
        msgs.extend(cat_msgs)
        if not cat_ok:
            ok = False

    return ok, msgs


# --- strict installed-config checks ---------------------------------------------------------------


def _strict_checks(
    claude: Path,
    fail: Callable[[str], None],
    warn: Callable[[str], None],
    good: Callable[[str], None],
) -> None:
    """Deep checks on a live install: hooks→scripts, .mcp.json shape, snapshot agreement."""
    settings = claude / "settings.json"
    if settings.is_file():
        try:
            doc = json.loads(settings.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            doc = None  # base checks already reported the parse error
        if isinstance(doc, dict):
            _strict_settings_hooks(claude, doc, fail, good)

    mcp = claude.parent / ".mcp.json"
    if mcp.is_file():
        _strict_mcp_shape(mcp, fail, good)

    snap = claude / "config" / "stack-catalog.snapshot.yaml"
    if snap.is_file():
        _strict_snapshot(claude, snap, fail, good)

    lock = claude.parent / ".mcp.lock.json"
    if lock.is_file():
        _strict_schema_artifact(lock, "mcp-lock", fail, good)

    psnap = claude / "state" / "pipeline-snapshot.json"
    if psnap.is_file():
        _strict_schema_artifact(psnap, "pipeline-snapshot", fail, good)


def _strict_schema_artifact(
    path: Path,
    schema_name: str,
    fail: Callable[[str], None],
    good: Callable[[str], None],
) -> None:
    """Validate a persisted JSON artifact against its JSON Schema (no-op without ``jsonschema``)."""
    from claude_kit import schemas

    if not schemas.available():
        return  # optional layer; referential checks already ran
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        fail(f"{path.name} is invalid JSON: {exc}")
        return
    with ExitStack() as stack:
        errs = schemas.validate_doc(doc, schema_name, stack)
    if errs:
        fail(f"{path.name} fails its JSON Schema: " + "; ".join(errs[:6]))
    else:
        good(f"{path.name} matches the {schema_name} schema")


def _strict_settings_hooks(
    claude: Path,
    doc: dict,
    fail: Callable[[str], None],
    good: Callable[[str], None],
) -> None:
    """Every settings.json hook must fire on a known event and run an installed, executable script."""
    clean = True
    for event, groups in (doc.get("hooks") or {}).items():
        if event not in KNOWN_EVENTS:
            fail(f"settings.json hooks: unknown event {event!r} (it will never fire)")
            clean = False
        for grp in groups or []:
            for entry in grp.get("hooks", []) or []:
                for script in _HOOK_SCRIPT_RE.findall(entry.get("command", "")):
                    sp = claude / "hooks" / script
                    if not sp.is_file():
                        fail(
                            f"settings.json hook references a missing script: {script}"
                        )
                        clean = False
                    elif not (sp.stat().st_mode & 0o111):
                        fail(f"hook script not executable: .claude/hooks/{script}")
                        clean = False
    if clean:
        good("settings.json hooks fire on known events and run installed scripts")


def _strict_mcp_shape(
    mcp: Path, fail: Callable[[str], None], good: Callable[[str], None]
) -> None:
    """.mcp.json must be a ``{mcpServers: {id: {command|url, ...}}}`` document."""
    try:
        doc = json.loads(mcp.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        fail(f".mcp.json is invalid JSON: {exc}")
        return
    servers = doc.get("mcpServers")
    if not isinstance(servers, dict):
        fail(".mcp.json has no valid 'mcpServers' object")
        return
    clean = True
    for sid, cfg in servers.items():
        if not isinstance(cfg, dict) or not (cfg.get("command") or cfg.get("url")):
            fail(f".mcp.json server {sid!r} has neither a command nor a url")
            clean = False
    if clean:
        good(f".mcp.json shape is valid ({len(servers)} server(s))")


def _strict_snapshot(
    claude: Path,
    snap: Path,
    fail: Callable[[str], None],
    good: Callable[[str], None],
) -> None:
    """The resolved stack snapshot must not list agents/skills/overlays absent from the install."""
    import yaml

    try:
        data = yaml.safe_load(snap.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        fail(f"stack snapshot is invalid YAML: {exc}")
        return
    missing: list[str] = []
    for agent in list(data.get("agents") or []) + list(
        data.get("overlay_agents") or []
    ):
        if not (claude / "agents" / f"{agent}.md").is_file():
            missing.append(f"agents/{agent}.md")
    for skill in data.get("skills") or []:
        if not (claude / "skills" / skill / "SKILL.md").is_file():
            missing.append(f"skills/{skill}/SKILL.md")
    for rule in data.get("overlay_rules") or []:
        if not (claude / "rules" / rule).is_file():
            missing.append(f"rules/{rule}")
    if missing:
        fail("stack snapshot lists files not installed: " + ", ".join(sorted(missing)))
    else:
        good("stack snapshot agrees with installed agents/skills/overlay files")


# --- catalog referential integrity (the kit's own data, checked against the payload) --------------


def _iter_stack_entries(stacks: dict) -> list[tuple[dict, str]]:
    """Yield ``(entry, stack_dir)`` for every non-planned frontend/backend/database stack entry."""
    out: list[tuple[dict, str]] = []
    for fw in (stacks.get("frontend", {}).get("frameworks", {}) or {}).values():
        if fw.get("status") != "planned":
            out.append((fw, str(fw.get("stack_dir", ""))))
    for lang in (stacks.get("backend", {}).get("languages", {}) or {}).values():
        if lang.get("status") == "planned":
            continue
        for fw in (lang.get("frameworks", {}) or {}).values():
            if fw.get("status") != "planned":
                out.append((fw, str(fw.get("stack_dir", ""))))
    for db in (stacks.get("database", {}).get("options", {}) or {}).values():
        if db.get("status") != "planned":
            out.append((db, str(db.get("stack_dir", ""))))
    return out


def _check_duplicate_skills(
    profiles: dict,
    cfail: Callable[[str], None],
    cgood: Callable[[str], None],
) -> None:
    """No profile may list the same skill twice in its own raw ``skills:`` list.

    Checks each profile's un-inherited list (not the resolved union, which dedupes by design), so it
    catches an accidental copy-paste in ``catalog/profiles.yaml``. The ``skills: all`` sentinel (a
    string) and any non-list value are skipped.
    """
    from collections import Counter

    dupes = False
    for name, prof in (profiles.get("profiles") or {}).items():
        skills = prof.get("skills") if isinstance(prof, dict) else None
        if not isinstance(skills, list):
            continue  # `all` sentinel or absent
        for skill, count in Counter(skills).items():
            if count > 1:
                dupes = True
                cfail(f"profile {name!r} has duplicate skill {skill!r} in skills list")
    if not dupes:
        cgood("no profile lists a duplicate skill")


def check_catalog(payload_root: str | Path | None = None) -> tuple[bool, list[str]]:
    """Check the kit catalog is referentially consistent (used by ``validate --strict`` / CI).

    Unlike :func:`claude_kit.catalog.resolve` (which validates *ids*), this confirms the referenced
    files physically exist — the gap that today only surfaces as a soft "missing (skipped)" line at
    install time. Verifies that every profile resolves to existing agents/skills/registered hooks,
    every stack's overlay rule/agent file is present on disk, and (if ``org.yaml`` exists) the org
    layer's new skills/agents/rules/packs and added core agents all exist.

    Args:
        payload_root: Payload root to check. Defaults to the bundled payload (the installed kit).

    Returns:
        ``(ok, messages)`` with each message prefixed ``OK``/``FAIL`` and tagged ``catalog:``.
    """
    from claude_kit import catalog

    msgs: list[str] = []
    ok = True

    def cfail(m: str) -> None:
        nonlocal ok
        ok = False
        msgs.append(f"FAIL  catalog: {m}")

    def cgood(m: str) -> None:
        msgs.append(f"OK    catalog: {m}")

    with ExitStack() as stack:
        if payload_root is None:
            from claude_kit import scaffold

            payload_root = scaffold.payload_dir(stack)
        payload_root = Path(payload_root)

        stacks = catalog._load(payload_root, "stacks.yaml")
        profiles = catalog._load(payload_root, "profiles.yaml")
        avail = catalog.available(payload_root)
        agent_set = set(avail["agents"])
        skill_set = set(avail["skills"])
        hook_set = set(avail["hooks"])

        prof_missing: set[str] = set()
        for name in profiles.get("profiles", {}):
            res = catalog._resolve_profile(profiles, name, avail)
            prof_missing |= {
                f"{name}: agent {a}" for a in res["agents"] if a not in agent_set
            }
            prof_missing |= {
                f"{name}: skill {s}" for s in res["skills"] if s not in skill_set
            }
            prof_missing |= {
                f"{name}: hook {h}" for h in res["hooks"] if h not in hook_set
            }
        if prof_missing:
            cfail(
                "profiles reference missing components: "
                + "; ".join(sorted(prof_missing))
            )
        else:
            cgood(
                f"{len(profiles.get('profiles', {}))} profiles reference only existing "
                "agents/skills/hooks"
            )

        _check_duplicate_skills(profiles, cfail, cgood)

        overlay_missing: set[str] = set()
        stack_skill_missing: set[str] = set()
        templates = payload_root / "templates" / "stacks"
        for entry, stack_dir in _iter_stack_entries(stacks):
            for rule in entry.get("overlay_rules", []) or []:
                if stack_dir and not (templates / stack_dir / "rules" / rule).is_file():
                    overlay_missing.add(f"{stack_dir}/rules/{rule}")
            for agent in entry.get("overlay_agents", []) or []:
                if (
                    stack_dir
                    and not (templates / stack_dir / "agents" / f"{agent}.md").is_file()
                ):
                    overlay_missing.add(f"{stack_dir}/agents/{agent}.md")
            for skill in entry.get("skills", []) or []:
                if skill not in skill_set:
                    stack_skill_missing.add(skill)
        if overlay_missing:
            cfail("stack overlay files missing: " + ", ".join(sorted(overlay_missing)))
        else:
            cgood("stack overlay rule/agent files all present")
        if stack_skill_missing:
            cfail(
                "stacks suggest missing skills: "
                + ", ".join(sorted(stack_skill_missing))
            )

        org_path = catalog.catalog_dir(payload_root) / "org.yaml"
        if org_path.is_file():
            _check_org_catalog(payload_root, catalog, agent_set, cfail, cgood)

        _check_catalog_schemas(payload_root, catalog, stack, cfail, cgood, msgs)

    return ok, msgs


def _check_catalog_schemas(
    payload_root: Path,
    catalog,  # noqa: ANN001 - the module, imported lazily by the caller
    stack: ExitStack,
    cfail: Callable[[str], None],
    cgood: Callable[[str], None],
    msgs: list[str],
) -> None:
    """Structurally validate catalog files + org pack manifests against their JSON Schemas.

    Optional: a no-op (one advisory line) when ``jsonschema`` is not installed.
    """
    from claude_kit import schemas

    if not schemas.available():
        msgs.append(
            "OK    catalog: jsonschema not installed — skipped JSON Schema checks "
            "(pip install claude-kit[schema])"
        )
        return

    cat_dir = catalog.catalog_dir(payload_root)
    file_schemas = [
        ("stacks", "stacks.yaml"),
        ("profiles", "profiles.yaml"),
        ("mcp", "mcp.yaml"),
        ("capture", "capture.yaml"),
    ]
    if (cat_dir / "org.yaml").is_file():
        file_schemas.append(("org", "org.yaml"))
    for sname, fn in file_schemas:
        if not (cat_dir / fn).is_file():
            continue
        errs = schemas.validate_doc(catalog._load(payload_root, fn), sname, stack)
        if errs:
            cfail(f"{fn} fails its JSON Schema: " + "; ".join(errs[:6]))
        else:
            cgood(f"{fn} matches its JSON Schema")

    import yaml

    packs_dir = payload_root / "templates" / "org" / "packs"
    pack_files = sorted(packs_dir.glob("*/pack.yaml")) if packs_dir.is_dir() else []
    pack_bad = False
    for pf in pack_files:
        doc = yaml.safe_load(pf.read_text(encoding="utf-8"))
        errs = schemas.validate_doc(doc, "org-pack", stack)
        if errs:
            cfail(
                f"{pf.parent.name}/pack.yaml fails its JSON Schema: "
                + "; ".join(errs[:6])
            )
            pack_bad = True
    if pack_files and not pack_bad:
        cgood(f"{len(pack_files)} org pack manifest(s) match the org-pack schema")


def _check_org_catalog(
    payload_root: Path,
    catalog,  # noqa: ANN001 - the module, imported lazily by the caller
    agent_set: set[str],
    cfail: Callable[[str], None],
    cgood: Callable[[str], None],
) -> None:
    """Check the org overlay's new skills/agents/rules/packs and added core agents all exist."""
    org = catalog._load(payload_root, "org.yaml")
    org_root = payload_root / "templates" / "org"
    missing: list[str] = []
    for skill in org.get("new_skills", []) or []:
        if not (org_root / "skills" / skill / "SKILL.md").is_file():
            missing.append(f"skills/{skill}/SKILL.md")
    for agent in org.get("new_agents", []) or []:
        if not (org_root / "agents" / f"{agent}.md").is_file():
            missing.append(f"agents/{agent}.md")
    for rule in org.get("new_rules", []) or []:
        if not (org_root / "rules" / rule).is_file():
            missing.append(f"rules/{rule}")
    for pack in org.get("packs", []) or []:
        pid = pack.get("id") if isinstance(pack, dict) else pack
        if pid and not (org_root / "packs" / pid / "pack.yaml").is_file():
            missing.append(f"packs/{pid}/pack.yaml")
    bad_agents = [
        a for a in org.get("core_agents_added", []) or [] if a not in agent_set
    ]
    if missing:
        cfail("org overlay files missing: " + ", ".join(sorted(missing)))
    if bad_agents:
        cfail(
            "org core_agents_added not found in agents/: "
            + ", ".join(sorted(bad_agents))
        )
    if not missing and not bad_agents:
        cgood("org overlay skills/agents/rules/packs all present")


# --- doctor (validate + environment) --------------------------------------------------------------


def doctor(target: str | Path, *, mcp: bool = False) -> tuple[bool, list[str]]:
    """Run a strict :func:`validate` plus environment/health checks.

    Note: ``doctor`` runs validation in **strict** mode, so it can FAIL on a deliberately hand-edited
    install (e.g. an agent/skill file removed by hand while the snapshot still records it). For a
    lenient structural check of a customized ``.claude/``, use ``validate`` without ``--strict``.

    Args:
        target: Project root to check.
        mcp: Also run MCP health checks (commands on PATH, ``${ENV}`` vars set, lockfile agreement).

    Returns:
        ``(ok, messages)``; environment issues are warnings (do not fail) unless they break config.
    """
    ok, msgs = validate(target, strict=True)
    target = Path(target).expanduser().resolve()
    claude = target / ".claude"

    for tool, why in (
        ("git", "version control"),
        ("jq", "command hooks parse tool input with jq"),
    ):
        if shutil.which(tool):
            msgs.append(f"OK    {tool} found ({why})")
        else:
            msgs.append(f"WARN  {tool} not on PATH — {why}")

    # Platform visibility: the shell hooks need a POSIX shell + jq. On Windows they no-op silently
    # unless run under WSL/Git Bash; the config and CLI work natively regardless. Never a failure.
    if platform.system() == "Windows":
        if shutil.which("jq"):
            msgs.append(
                "OK    Windows with jq on PATH — a POSIX shell (Git Bash/WSL) is providing the hooks"
            )
        else:
            msgs.append(
                "WARN  Windows detected and jq not on PATH — the shell hooks (guard-*, warn-*) will "
                "no-op. Run claude-kit inside WSL or Git Bash to enable them; the kit config "
                "(agents/skills/rules) and the claude-kit CLI work natively on Windows regardless."
            )

    hooks_dir = claude / "hooks"
    if hooks_dir.is_dir():
        nonexec = [
            p.name for p in hooks_dir.glob("*.sh") if not (p.stat().st_mode & 0o111)
        ]
        if nonexec:
            msgs.append(
                f"WARN  hook scripts not executable: {', '.join(sorted(nonexec))} "
                f"(run: chmod +x .claude/hooks/*.sh)"
            )
        elif any(hooks_dir.glob("*.sh")):
            msgs.append("OK    hook scripts are executable")

    gitignore = target / ".gitignore"
    gi = gitignore.read_text(encoding="utf-8") if gitignore.is_file() else ""
    for entry in (".claude/state/", ".claude/tmp/"):
        if entry in gi:
            msgs.append(f"OK    {entry} is gitignored")
        else:
            msgs.append(
                f"WARN  {entry} not gitignored (runtime artifacts may be committed)"
            )

    settings = claude / "settings.json"
    if settings.is_file() and "capture-learnings" in settings.read_text(
        encoding="utf-8"
    ):
        msgs.append(
            "WARN  learning capture is enabled — a background job reads your session transcript and "
            "writes durable notes to .claude/agent-memory/ (committed). Secret files are skipped and "
            "secret-shaped values redacted; still review new entries before committing. Disable with "
            "CLAUDE_KIT_NO_AUTOCAPTURE=1; bound with CLAUDE_KIT_CAPTURE_MAX_LINES/_MAX_BYTES."
        )

    journal = claude / "config" / UPGRADE_JOURNAL
    if journal.is_file():
        detail = ""
        try:
            j = UpgradeJournal.from_dict(
                json.loads(journal.read_text(encoding="utf-8"))
            )
            detail = f" ({j.from_version} -> {j.to_version}, started {j.started_at})"
        except (ValueError, OSError):
            detail = ""
        msgs.append(
            f"WARN  interrupted upgrade detected{detail} — re-run `claude-kit upgrade` to finish "
            f"(upgrade is convergent; this clears the journal)"
        )

    if mcp:
        _mcp_health(target, msgs)

    return ok, msgs


def _mcp_health(target: Path, msgs: list[str]) -> None:
    """Append MCP health lines: command on PATH, ``${ENV}`` vars set, lockfile agreement (warn-only)."""
    mcp = target / ".mcp.json"
    if not mcp.is_file():
        msgs.append("OK    no .mcp.json (no MCP servers configured)")
        return
    try:
        servers = json.loads(mcp.read_text(encoding="utf-8")).get("mcpServers", {})
    except json.JSONDecodeError as exc:
        msgs.append(f"WARN  .mcp.json unreadable for MCP health checks: {exc}")
        return
    for sid, cfg in servers.items():
        command = cfg.get("command") if isinstance(cfg, dict) else None
        if command and not shutil.which(command):
            msgs.append(f"WARN  MCP {sid}: command {command!r} not on PATH")
        elif command:
            msgs.append(f"OK    MCP {sid}: command {command!r} found")
        for var in sorted(set(_ENV_VAR_RE.findall(json.dumps(cfg)))):
            if not os.environ.get(var):
                msgs.append(f"WARN  MCP {sid}: env var ${{{var}}} is not set")

    lock = target / ".mcp.lock.json"
    if lock.is_file():
        try:
            locked = set(
                json.loads(lock.read_text(encoding="utf-8")).get("servers", {})
            )
        except json.JSONDecodeError:
            locked = set()
        if locked != set(servers):
            msgs.append(
                "WARN  .mcp.lock.json is out of sync with .mcp.json "
                "(run `claude-kit upgrade` to regenerate)"
            )
        else:
            msgs.append("OK    .mcp.lock.json matches .mcp.json")
