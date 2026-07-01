"""scripts/check_rule_sizes.py — offline size gate over shipped rule files.

Claude Code loads a rule only partially once it passes 40,000 characters, so every rule the kit
ships must stay under the guard's threshold. These tests pin that the real repo is clean and that
the guard actually trips on an over-limit file.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "check_rule_sizes", ROOT / "scripts" / "check_rule_sizes.py"
)
assert _spec and _spec.loader
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)


def test_real_repo_has_no_oversized_rule():
    """Every shipped rule file is under the threshold (regression guard for the 40k limit)."""
    bad = mod.oversized()
    assert bad == [], "oversized rule file(s): " + ", ".join(
        f"{rel} ({count:,} chars)" for rel, count in bad
    )


def test_scan_finds_the_shipped_rules():
    """Sanity: the globs actually match real files, so a green result means something."""
    files = mod.rule_files()
    names = {p.name for p in files}
    assert "ui-design-system.md" in names  # a split React overlay
    assert "ui-components.md" in names  # created by the 0.55.0 split
    assert len(files) > 20  # the 24-file core plus overlays


def test_oversized_file_is_flagged(tmp_path):
    """A synthetic rule at/over the threshold trips the guard."""
    rules = tmp_path / "rules"
    rules.mkdir()
    (rules / "ok.md").write_text("x" * (mod.THRESHOLD - 1), encoding="utf-8")
    (rules / "too-big.md").write_text("x" * (mod.THRESHOLD + 1), encoding="utf-8")

    bad = mod.oversized(root=tmp_path)
    flagged = {rel.name for rel, _ in bad}
    assert flagged == {"too-big.md"}
