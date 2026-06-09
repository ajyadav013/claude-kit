"""Validation and health checks for a scaffolded claude-kit configuration.

``validate`` performs structural checks (files present, JSON parses, frontmatter complete,
referenced overlays installed). ``doctor`` adds environment checks (git/jq available, hook scripts
executable, runtime dirs gitignored). Both return ``(ok, messages)`` so the CLI can print a report
and choose an exit code.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from claude_kit.models import InitOptions


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


def _load_init_options(claude_dir: Path) -> InitOptions | None:
    """Load and parse ``.claude/config/init-options.json`` if present."""
    path = claude_dir / "config" / "init-options.json"
    if not path.is_file():
        return None
    try:
        return InitOptions.from_dict(json.loads(path.read_text(encoding="utf-8")))
    except (json.JSONDecodeError, TypeError, ValueError):
        return None


def validate(target: str | Path) -> tuple[bool, list[str]]:
    """Structurally validate the claude-kit config at ``target``.

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

    options = _load_init_options(claude)
    if options is None:
        warn(
            "missing or unreadable .claude/config/init-options.json (validate/upgrade limited)"
        )
    else:
        good(
            f"init-options.json (schema v{options.schema_version}, kit {options.claude_kit_version})"
        )
        for rec in options.files:
            if not (target / rec.path).exists():
                fail(f"recorded file missing: {rec.path}")
        good(f"tracked files present ({len(options.files)} recorded)")

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

    return ok, msgs


def doctor(target: str | Path) -> tuple[bool, list[str]]:
    """Run :func:`validate` plus environment/health checks.

    Returns:
        ``(ok, messages)``; environment issues are warnings (do not fail) unless they break config.
    """
    ok, msgs = validate(target)
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

    return ok, msgs
