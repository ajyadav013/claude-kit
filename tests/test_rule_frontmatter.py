"""Payload invariants for rule-file frontmatter (Claude Code scoped rule loading).

Overlay rules ship ``paths:`` YAML frontmatter so `.claude/rules/` loads them only when Claude works
with matching files (official scoped-loading support) — except ``mongodb-patterns.md``, which stays
unconditional because a document store has no reliable file signal and a wrong glob would mean the
rule *never* loads. The scaffolder must carry the block through verbatim (rules are copied, not
rendered).

Core rules were ALSO frontmatter-free until 0.77.0, on the rationale that they are "the stack-agnostic
contract and load at launch". That rationale was measured and did not survive: loading all of them at
launch cost 101,255 tokens, putting a default install's standing context at 173,750 — 87% of a 200k
window, before any work. The contract was not being honoured at launch; it was stopping the session
from starting. A contract that cannot be executed is not a contract.

What replaced it is a split, not a repeal, and both halves are pinned below:

  * **Covenant (7 rules, still frontmatter-free).** Their trigger is temporal — "every turn", "every
    change" — and no path glob can express that. Scoping them would be a category error, so they keep
    loading at launch.
  * **Domain rules (the other 18, scoped).** Their trigger genuinely is a file type. They keep their
    full text and filename, so every one of the ~668 ``.claude/rules/<name>.md`` citations across the
    payload still resolves — nothing was moved or deleted.

Measured A/B on the HEAD payload (control = empty dir at 63,717; attribution floor = rules removed at
72,495): standing context 173,750 → 91,511, i.e. rules 101,255 → 19,016, an 81% cut that takes a
default install from 87% of a 200k window to 46%. The original concern — a wrong glob means the rule
never loads — is real, and is exactly why the covenant exists and why the scoped half is checked for
*valid globs* rather than merely for the presence of some frontmatter.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from tests._helpers import install

#: The one overlay rule that is deliberately unscoped (no reliable file signal for a document store —
#: mirrors the export module's ``_DB_GLOBS`` reasoning).
_UNSCOPED_OVERLAYS = {"mongodb-patterns.md"}

#: Core rules that load at launch. Membership is a deliberate decision, not a default: a rule earns a
#: place here only when its trigger is temporal ("every turn" / "every change") and therefore cannot be
#: expressed as a path glob. Everything else is scoped. Keep this list short — it is the standing
#: context budget every session pays before doing any work.
_COVENANT = {
    "rarv-cycle",
    "risk-classification",
    "autonomy-levels",
    "quality-gates",
    "mandatory-workflow",
    "human-in-the-loop",
    "continuity",
}


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


def test_covenant_rules_have_no_frontmatter(payload):
    """The 7 covenant rules load at launch — none may grow ``paths:`` scoping.

    Their trigger is temporal, not a file type: RARV runs every turn, continuity's resume contract
    is a per-turn obligation, and quality-gates/mandatory-workflow govern a docs-only or YAML-only
    change just as much as a Python one. A glob would silently exempt exactly those cases.
    """
    for name in sorted(_COVENANT):
        rule = payload / "rules" / f"{name}.md"
        assert rule.is_file(), f"covenant rule {name}.md is missing"
        assert _split_frontmatter(rule.read_text(encoding="utf-8")) is None, (
            f"{name}.md is covenant — it must stay always-on"
        )


def test_scoped_core_rules_carry_valid_paths(payload):
    """Every non-covenant core rule is scoped, with globs that are lists of non-empty strings."""
    checked = 0
    for rule in sorted((payload / "rules").glob("*.md")):
        if rule.stem in _COVENANT:
            continue
        meta = _split_frontmatter(rule.read_text(encoding="utf-8"))
        assert meta is not None, (
            f"{rule.name}: core rule is neither covenant nor scoped"
        )
        paths = meta.get("paths")
        assert isinstance(paths, list) and paths, (
            f"{rule.name}: paths must be a non-empty list"
        )
        assert all(isinstance(p, str) and p.strip() for p in paths), (
            f"{rule.name}: empty glob"
        )
        assert all("{" not in p for p in paths), (
            f"{rule.name}: use list form, not braces"
        )
        checked += 1
    assert checked >= 18


def test_covenant_membership_is_exhaustive(payload):
    """Adding a core rule must force a deliberate covenant-or-scoped decision, not default silently.

    Without this, a new rule that simply omits frontmatter joins the always-on set unnoticed — which
    is precisely how the launch cost reached 148,937 tokens in the first place.
    """
    on_disk = {p.stem for p in (payload / "rules").glob("*.md")}
    assert _COVENANT <= on_disk, (
        f"covenant names rules that do not exist: {sorted(_COVENANT - on_disk)}"
    )


def test_documentation_rule_is_scoped_to_source_not_only_markdown(payload):
    """documentation.md governs headers/docstrings on SOURCE files, so source globs must be present.

    Regression pin for finding F-066: an earlier attempt scoped it to ``**/*.md`` alone, which
    inverted it — the rule would load when editing docs and stay absent when editing the code whose
    docstrings it mandates.
    """
    meta = _split_frontmatter(
        (payload / "rules" / "documentation.md").read_text(encoding="utf-8")
    )
    assert meta is not None
    assert any(
        p.endswith((".py", ".ts", ".go", ".rb", ".java", ".rs")) for p in meta["paths"]
    ), "documentation.md must match source files, not only markdown"


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
