"""Validation and health checks for a scaffolded claude-kit configuration.

``validate`` performs structural checks (files present, JSON parses, frontmatter complete,
referenced overlays installed). Passing ``strict=True`` adds deep checks: settings.json hooks point
at installed, executable scripts on valid events; ``.mcp.json`` has a sane shape; the resolved stack
snapshot agrees with what's on disk; deployed prose is free of hidden/deceptive Unicode (an
invisible-instruction channel — critical classes FAIL); and the **bundled catalog** is referentially
consistent (profiles → existing agents/skills/hooks, stack overlay files present). ``doctor`` runs the strict
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
import subprocess
from contextlib import ExitStack
from pathlib import Path
from typing import Callable

from claude_kit.models import InitOptions, UpgradeJournal
from claude_kit.secure_fs import (
    TRANSACTION_SCHEMA,
    ProjectFS,
    inspect_interrupted_transaction,
)


def _load_claude_code_compatibility() -> dict:
    """Load the bundled, schema-validated Claude Code compatibility policy."""
    import yaml

    from claude_kit import scaffold

    with ExitStack() as stack:
        path = (
            scaffold.payload_dir(stack) / "catalog" / "claude-code-compatibility.yaml"
        )
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


CLAUDE_CODE_COMPATIBILITY = _load_claude_code_compatibility()
#: Officially recognized events are data, separate from the hook implementations the kit ships.
KNOWN_EVENTS = frozenset(CLAUDE_CODE_COMPATIBILITY["recognized_events"])

#: Extracts the script basenames a hook command runs from ``.claude/hooks/`` (inline guards match none).
_HOOK_SCRIPT_RE = re.compile(r"\.claude/hooks/([^\"'\s]+\.sh)")
#: Extracts ``${VAR}`` placeholders from an .mcp.json fragment (valid shell identifiers only — a
#: leading digit like ``${1}`` is a positional parameter, not an env var to warn about).
_ENV_VAR_RE = re.compile(r"\$\{([A-Za-z_]\w*)\}")

#: Hidden/deceptive Unicode in deployed prose, tiered by severity. **critical** characters have no
#: legitimate role in kit prose and form an invisible-instruction channel (content a human reviewer
#: cannot see but a model reads): Unicode tag characters, bidi overrides/isolates, variation
#: selectors 17-256. **warning** characters are suspicious but occasionally legitimate: zero-width
#: characters and bidi marks (a BOM appearing *mid-file* is flagged separately — a leading one is a
#: benign encoding artifact). **info** is NBSP — common in prose pasted from rich-text editors.
_UNICODE_CLASSES: tuple[tuple[str, str, tuple[tuple[int, int], ...]], ...] = (
    ("critical", "tag characters (U+E0001-E007F)", ((0xE0001, 0xE007F),)),
    (
        "critical",
        "bidi overrides/isolates (U+202A-E, U+2066-9)",
        ((0x202A, 0x202E), (0x2066, 0x2069)),
    ),
    ("critical", "variation selectors 17-256 (U+E0100-E01EF)", ((0xE0100, 0xE01EF),)),
    ("warning", "zero-width characters (U+200B-D)", ((0x200B, 0x200D),)),
    ("warning", "bidi marks (U+200E/F)", ((0x200E, 0x200F),)),
    ("info", "non-breaking spaces (U+00A0)", ((0x00A0, 0x00A0),)),
)


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
        document = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(document, dict):
            raise ValueError("document root must be an object")
        if not isinstance(document.get("selection", {}), dict):
            raise ValueError("selection must be an object")
        if not isinstance(document.get("files", []), list):
            raise ValueError("files must be an array")
        return InitOptions.from_dict(document), None
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

    def info(m: str) -> None:
        msgs.append(f"INFO  {m}")

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
        try:
            from claude_kit import catalog, scaffold

            with ExitStack() as stack:
                catalog.resolve(scaffold.payload_dir(stack), options.selection)
        except (FileNotFoundError, TypeError, ValueError) as exc:
            fail(
                ".claude/config/init-options.json contains a selection that does not resolve "
                f"against this kit's catalog ({exc}) — repair it or re-run "
                "`claude-kit init --force`"
            )
        else:
            good("installed selection resolves against the current catalog")
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
        _strict_checks(claude, fail, warn, good, info)
        cat_ok, cat_msgs = check_catalog(require_schema=True)
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
    info: Callable[[str], None],
) -> None:
    """Deep checks on a live install: hooks→scripts, .mcp.json shape, snapshot agreement, hidden Unicode."""
    settings = claude / "settings.json"
    if settings.is_file():
        try:
            doc = json.loads(settings.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            doc = None  # base checks already reported the parse error
        if isinstance(doc, dict):
            _strict_settings_hooks(claude, doc, fail, warn, good)
        elif doc is not None:
            fail("settings.json root must be an object")

    mcp = claude.parent / ".mcp.json"
    if mcp.is_file():
        _strict_mcp_shape(mcp, fail, good)

    snap = claude / "config" / "stack-catalog.snapshot.yaml"
    if snap.is_file():
        _strict_snapshot(claude, snap, fail, good)
        _strict_yaml_schema_artifact(snap, "stack-catalog-snapshot", fail, good)

    lock = claude.parent / ".mcp.lock.json"
    if lock.is_file():
        _strict_schema_artifact(lock, "mcp-lock", fail, good)

    psnap = claude / "state" / "pipeline-snapshot.json"
    if psnap.is_file():
        _strict_schema_artifact(psnap, "pipeline-snapshot", fail, good)

    _strict_hidden_unicode(claude, fail, warn, good, info)


def _scan_hidden_unicode(target: Path, claude: Path) -> dict[str, list[str]]:
    """Scan deployed prose (``*.md`` under ``.claude/`` plus the root ``CLAUDE.md``) for hidden Unicode.

    Returns ``{"critical": [...], "warning": [...], "info": [...]}`` where each entry reads
    ``<relpath>: Nx <class> (first at line L)``. A *leading* U+FEFF is a benign encoding artifact;
    only a BOM mid-file is flagged (warning tier). A file that is not valid UTF-8 is itself a
    warning-tier finding — the scan never crashes on one.
    """
    findings: dict[str, list[str]] = {"critical": [], "warning": [], "info": []}
    files = sorted(claude.rglob("*.md"))
    if (target / "CLAUDE.md").is_file():
        files.append(target / "CLAUDE.md")
    for path in files:
        rel = path.relative_to(target)
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            findings["warning"].append(f"{rel}: not valid UTF-8 — review manually")
            continue
        body = text[1:] if text.startswith("\ufeff") else text
        counts: dict[tuple[str, str], list[int]] = {}
        for idx, ch in enumerate(body):
            code = ord(ch)
            if code < 0xA0:
                continue
            if code == 0xFEFF:  # mid-file BOM (a leading one was stripped above)
                rec = counts.setdefault(
                    ("warning", "byte-order mark mid-file"), [0, idx]
                )
                rec[0] += 1
                continue
            for tier, label, ranges in _UNICODE_CLASSES:
                if any(lo <= code <= hi for lo, hi in ranges):
                    rec = counts.setdefault((tier, label), [0, idx])
                    rec[0] += 1
                    break
        for (tier, label), (n, first) in counts.items():
            line = body.count("\n", 0, first) + 1
            findings[tier].append(f"{rel}: {n}x {label} (first at line {line})")
    return findings


def _strict_hidden_unicode(
    claude: Path,
    fail: Callable[[str], None],
    warn: Callable[[str], None],
    good: Callable[[str], None],
    info: Callable[[str], None],
) -> None:
    """Hidden-Unicode scan of deployed prose: critical classes FAIL, warning classes WARN, NBSP is INFO.

    Critical characters (tag characters, bidi overrides/isolates, variation selectors) can carry
    instructions a human reviewer cannot see but a model reads — exactly the hidden-content vector
    the ``dependency-verification`` skill's agent-config intake greps for. Their presence in an
    installed config fails strict validation outright; the softer tiers surface via ``doctor``.
    """
    findings = _scan_hidden_unicode(claude.parent, claude)
    cap = 8  # keep a poisoned tree readable — the first hits identify the files to open
    for tier, emit in (("critical", fail), ("warning", warn)):
        entries = findings[tier]
        for m in entries[:cap]:
            emit(f"hidden unicode: {m}")
        if len(entries) > cap:
            emit(f"hidden unicode: +{len(entries) - cap} more {tier} finding(s)")
    if findings["info"]:
        info(
            f"hidden unicode: non-breaking spaces in {len(findings['info'])} file(s) "
            "(informational — common in pasted prose)"
        )
    if not findings["critical"] and not findings["warning"]:
        good("deployed prose is free of hidden/deceptive Unicode")


def _strict_schema_artifact(
    path: Path,
    schema_name: str,
    fail: Callable[[str], None],
    good: Callable[[str], None],
) -> None:
    """Validate a persisted JSON artifact against its JSON Schema, failing closed."""
    from claude_kit import schemas

    if not schemas.available():
        fail(
            "jsonschema not installed — strict validation cannot continue; "
            "repair the claude-code-kit installation"
        )
        return
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


def _strict_yaml_schema_artifact(
    path: Path,
    schema_name: str,
    fail: Callable[[str], None],
    good: Callable[[str], None],
) -> None:
    """Validate a persisted YAML artifact against its JSON Schema, failing closed."""
    from claude_kit import schemas

    if not schemas.available():
        fail(
            "jsonschema not installed — strict validation cannot continue; "
            "repair the claude-code-kit installation"
        )
        return
    import yaml

    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        fail(f"{path.name} is invalid YAML: {exc}")
        return
    if (
        schema_name == "stack-catalog-snapshot"
        and isinstance(doc, dict)
        and "schema_version" not in doc
    ):
        fail(
            f"{path.name} is a legacy unversioned stack snapshot; "
            "run `claude-kit upgrade` to migrate its gate-policy metadata"
        )
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
    warn: Callable[[str], None],
    good: Callable[[str], None],
) -> None:
    """Check hook scripts and flag events outside the tested compatibility catalog."""
    clean = True
    hooks = doc.get("hooks")
    if hooks is None:
        hooks = {}
    if not isinstance(hooks, dict):
        fail("settings.json 'hooks' must be an object")
        return
    for event, groups in hooks.items():
        if not isinstance(event, str) or not isinstance(groups, list):
            fail("settings.json hook entries must map event names to arrays")
            clean = False
            continue
        if event not in KNOWN_EVENTS:
            warn(
                f"settings.json hook event {event!r} is not in the tested compatibility catalog; "
                "run the official validator (`claude plugin validate . --strict`) with the "
                "target Claude Code version"
            )
            clean = False
        for grp in groups:
            if not isinstance(grp, dict):
                fail(f"settings.json hook event {event!r} contains a non-object group")
                clean = False
                continue
            entries = grp.get("hooks") or []
            if not isinstance(entries, list):
                fail(f"settings.json hook event {event!r} has a non-array hooks field")
                clean = False
                continue
            for entry in entries:
                if not isinstance(entry, dict) or not isinstance(
                    entry.get("command", ""), str
                ):
                    fail(
                        f"settings.json hook event {event!r} contains an invalid hook command"
                    )
                    clean = False
                    continue
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
    if not isinstance(doc, dict):
        fail(".mcp.json root must be an object")
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
    if not isinstance(data, dict):
        fail("stack snapshot root must be an object")
        return

    def string_list(name: str) -> list[str]:
        raw = data.get(name) or []
        if not isinstance(raw, list) or any(not isinstance(item, str) for item in raw):
            fail(f"stack snapshot {name!r} must be an array of strings")
            return []
        return raw

    missing: list[str] = []
    for agent in string_list("agents") + string_list("overlay_agents"):
        if not (claude / "agents" / f"{agent}.md").is_file():
            missing.append(f"agents/{agent}.md")
    for skill in string_list("skills"):
        if not (claude / "skills" / skill / "SKILL.md").is_file():
            missing.append(f"skills/{skill}/SKILL.md")
    for rule in string_list("overlay_rules"):
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


def check_catalog(
    payload_root: str | Path | None = None, *, require_schema: bool = False
) -> tuple[bool, list[str]]:
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

        _check_catalog_schemas(
            payload_root, catalog, stack, cfail, cgood, msgs, require_schema
        )

    return ok, msgs


def _check_catalog_schemas(
    payload_root: Path,
    catalog,  # noqa: ANN001 - the module, imported lazily by the caller
    stack: ExitStack,
    cfail: Callable[[str], None],
    cgood: Callable[[str], None],
    msgs: list[str],
    require_schema: bool,
) -> None:
    """Structurally validate catalog files + org pack manifests against their JSON Schemas.

    A missing runtime dependency is a failure when called from strict validation.
    """
    from claude_kit import schemas

    if not schemas.available():
        message = (
            "jsonschema not installed — strict validation cannot continue; "
            "repair the claude-code-kit installation"
        )
        if require_schema:
            cfail(message)
        else:
            msgs.append(f"WARN  catalog: {message}")
        return

    cat_dir = catalog.catalog_dir(payload_root)
    file_schemas = [
        ("stacks", "stacks.yaml"),
        ("profiles", "profiles.yaml"),
        ("mcp", "mcp.yaml"),
        ("capture", "capture.yaml"),
        ("claude-code-compatibility", "claude-code-compatibility.yaml"),
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


def _version_tuple(value: str) -> tuple[int, int, int]:
    """Parse the numeric core of a Claude Code version for compatibility comparisons."""
    match = re.search(r"(?<!\d)(\d+)\.(\d+)\.(\d+)(?!\d)", value)
    if not match:
        raise ValueError(f"unrecognized version: {value!r}")
    return tuple(int(part) for part in match.groups())  # type: ignore[return-value]


def _claude_version(executable: str) -> str | None:
    """Return Claude Code's semantic version, or ``None`` when it cannot be queried safely."""
    try:
        proc = subprocess.run(
            [executable, "--version"],
            capture_output=True,
            check=False,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    match = re.search(r"(?<!\d)(\d+\.\d+\.\d+)(?!\d)", proc.stdout)
    return match.group(1) if match else None


def _claude_code_health(msgs: list[str]) -> None:
    """Append missing/tested/untested/unsupported Claude Code compatibility state."""
    executable = shutil.which("claude")
    if not executable:
        msgs.append(
            "WARN  Claude Code not on PATH — official plugin validation and runtime compatibility "
            "could not be checked"
        )
        return
    version = _claude_version(executable)
    if version is None:
        msgs.append(
            f"WARN  Claude Code found at {executable}, but its version is unreadable"
        )
        return

    policy = CLAUDE_CODE_COMPATIBILITY
    minimum = str(policy["minimum"])
    if _version_tuple(version) < _version_tuple(minimum):
        msgs.append(
            f"WARN  Claude Code {version} is unsupported; minimum is {minimum} "
            "(upgrade before relying on hooks)"
        )
        return

    tested = {str(item["version"]) for item in policy.get("tested", [])}
    if version in tested:
        msgs.append(f"OK    Claude Code {version} is supported and tested")
    else:
        msgs.append(
            f"WARN  Claude Code {version} is supported but is not in the tested matrix; "
            "run `claude plugin validate . --strict`"
        )

    for feature, spec in policy.get("features", {}).items():
        feature_min = str(spec["minimum_version"])
        if not spec.get("required") and _version_tuple(version) < _version_tuple(
            feature_min
        ):
            msgs.append(
                f"INFO  optional feature unavailable: {feature} requires Claude Code {feature_min}+"
            )


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

    _claude_code_health(msgs)

    # Native pathname fallbacks cannot exclude a junction swap. Mutation therefore fails closed;
    # read-only/plugin use remains distinguishable from the shell-hook runtime limitation.
    if platform.system() == "Windows":
        msgs.append(
            "WARN  native Windows project mutation is unsupported in this release — init, merge, "
            "upgrade, export, and pipeline writes require WSL on a filesystem with POSIX "
            "descriptor and lock semantics; read-only inspection and plugin discovery remain "
            "available"
        )
        if shutil.which("jq"):
            msgs.append(
                "INFO  jq is on PATH, but .sh hooks still require a POSIX shell such as WSL"
            )
        else:
            msgs.append(
                "WARN  Windows detected and jq not on PATH — the shell hooks (guard-*, warn-*) will "
                "no-op. Run claude-kit inside WSL with jq to enable them."
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

    transaction_doc: dict | None = None
    try:
        transaction_doc = inspect_interrupted_transaction(ProjectFS(target))
    except OSError as exc:
        msgs.append(
            "WARN  interrupted transaction marker could not be inspected safely — "
            f"{exc}; do not mutate this project until the marker is repaired"
        )
    if transaction_doc is not None:
        detail = ""
        operation = "upgrade"
        recovery = "`claude-kit upgrade`"
        rollback = ""
        try:
            if transaction_doc.get(
                "schema_version"
            ) == TRANSACTION_SCHEMA and transaction_doc.get("transaction_kind") in {
                "install",
                "force",
                "merge",
                "upgrade",
            }:
                operation = transaction_doc["transaction_kind"]
                detail = (
                    f" ({transaction_doc.get('from_version', '')} -> "
                    f"{transaction_doc.get('to_version', '')}, started "
                    f"{transaction_doc.get('started_at', '')})"
                )
                recovery = {
                    "install": "`claude-kit init`",
                    "force": "`claude-kit init --force`",
                    "merge": "`claude-kit init --merge`",
                    "upgrade": "`claude-kit upgrade`",
                }[operation]
                rollback = (
                    "; the durable commit is complete but transaction cleanup is pending"
                    if transaction_doc.get("phase") == "committed"
                    else "; the schema-v2 journal is rollback-capable"
                )
            else:
                j = UpgradeJournal.from_dict(transaction_doc)
                detail = (
                    f" ({j.from_version} -> {j.to_version}, started {j.started_at})"
                )
        except (TypeError, ValueError):
            detail = ""
        msgs.append(
            f"WARN  interrupted {operation} detected{detail}{rollback} — re-run {recovery} to "
            "recover and finish (the operation is convergent and clears the journal)"
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
        document = json.loads(mcp.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        msgs.append(f"WARN  .mcp.json unreadable for MCP health checks: {exc}")
        return
    if not isinstance(document, dict) or not isinstance(
        document.get("mcpServers"), dict
    ):
        msgs.append("WARN  .mcp.json has no valid mcpServers object for health checks")
        return
    servers = document["mcpServers"]
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
            lock_document = json.loads(lock.read_text(encoding="utf-8"))
            if not isinstance(lock_document, dict) or not isinstance(
                lock_document.get("servers"), dict
            ):
                raise ValueError("lock root/servers has the wrong shape")
            locked = set(lock_document["servers"])
        except (json.JSONDecodeError, ValueError):
            locked = set()
        if locked != set(servers):
            msgs.append(
                "WARN  .mcp.lock.json is out of sync with .mcp.json "
                "(run `claude-kit upgrade` to regenerate)"
            )
        else:
            msgs.append("OK    .mcp.lock.json matches .mcp.json")
