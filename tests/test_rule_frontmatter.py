"""Payload invariants for rule-file frontmatter (Claude Code scoped rule loading).

Overlay rules ship ``paths:`` YAML frontmatter so `.claude/rules/` loads them only when Claude works
with matching files (official scoped-loading support) — except ``mongodb-patterns.md``, which stays
unconditional because a document store has no reliable file signal and a wrong glob would mean the
rule *never* loads. Core rules stay frontmatter-free on purpose: they are the stack-agnostic contract
and load at launch. The scaffolder must carry the block through verbatim (rules are copied, not
rendered).
"""

from __future__ import annotations

from pathlib import Path

import yaml

from tests._helpers import install

#: The one overlay rule that is deliberately unscoped (no reliable file signal for a document store —
#: mirrors the export module's ``_DB_GLOBS`` reasoning).
_UNSCOPED_OVERLAYS = {"mongodb-patterns.md"}


def _split_frontmatter(text: str) -> dict | None:
    """Return the parsed leading YAML frontmatter block, or ``None`` when the file has none."""
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---\n", 4)
    assert end != -1, "unterminated frontmatter fence"
    data = yaml.safe_load(text[4:end])
    assert isinstance(data, dict), "frontmatter is not a mapping"
    return data


def _overlay_rules(payload: Path) -> list[Path]:
    return sorted((payload / "templates" / "stacks").rglob("rules/*.md"))


def test_scoped_overlay_rules_carry_valid_paths(payload):
    """Every scopeable overlay rule opens with a ``paths:`` list of non-empty glob strings."""
    checked = 0
    for rule in _overlay_rules(payload):
        if rule.name in _UNSCOPED_OVERLAYS:
            continue
        meta = _split_frontmatter(rule.read_text(encoding="utf-8"))
        assert meta is not None, f"{rule.name}: missing paths frontmatter"
        paths = meta.get("paths")
        assert isinstance(paths, list) and paths, f"{rule.name}: paths must be a list"
        assert all(isinstance(p, str) and p.strip() for p in paths), (
            f"{rule.name}: empty glob"
        )
        # List form only — brace expansion would not project to Cursor globs verbatim.
        assert all("{" not in p for p in paths), (
            f"{rule.name}: use list form, not braces"
        )
        checked += 1
    assert checked >= 12


def test_mongodb_overlay_stays_unscoped(payload):
    """The documented exception: mongodb-patterns.md loads unconditionally (no frontmatter)."""
    mongo = payload / "templates" / "stacks" / "db" / "mongodb" / "rules"
    text = (mongo / "mongodb-patterns.md").read_text(encoding="utf-8")
    assert _split_frontmatter(text) is None


def test_core_rules_have_no_frontmatter(payload):
    """Core rules are the always-on contract — none may grow ``paths:`` scoping."""
    for rule in sorted((payload / "rules").glob("*.md")):
        assert _split_frontmatter(rule.read_text(encoding="utf-8")) is None, rule.name


def test_scaffold_installs_frontmatter_verbatim(tmp_path, payload):
    """An installed overlay rule keeps its ``paths:`` block byte-for-byte (copy, not render)."""
    install(
        payload,
        tmp_path,
        frontend_framework="react",
        frontend_language="typescript",
        backend_language="python",
        backend_framework="fastapi",
        database="postgres",
    )
    installed = tmp_path / ".claude" / "rules" / "react-patterns.md"
    source = (
        payload / "templates" / "stacks" / "frontend" / "react" / "rules"
    ) / "react-patterns.md"
    assert installed.read_text(encoding="utf-8") == source.read_text(encoding="utf-8")
    assert installed.read_text(encoding="utf-8").startswith("---\npaths:")
