"""The repo's docs/versions/counts stay in sync — and the checker that proves it actually bites."""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

from claude_kit import catalog, hooks
from claude_kit.components import HookEffect
from claude_kit.models import INIT_OPTIONS_SCHEMA
from tests._helpers import make_selection

_SCRIPT = (
    Path(__file__).resolve().parent.parent / "scripts" / "check_docs_consistency.py"
)
_ROOT = _SCRIPT.parent.parent


def _load():
    spec = importlib.util.spec_from_file_location("check_docs_consistency", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_docs_are_consistent():
    """Version strings, component counts, and profile→gate tables all agree across the repo."""
    errors = _load().run()
    assert errors == [], "docs consistency drift:\n  " + "\n  ".join(errors)


def test_checker_detects_version_drift(monkeypatch):
    """Guard against a vacuously-passing checker: a planted bad version must be reported."""
    mod = _load()
    real_read = mod._read

    def fake_read(rel: str) -> str:
        if rel == "SECURITY.md":
            return "claude-kit is pre-1.0 ... (currently **9.9.9**) receives security fixes."
        return real_read(rel)

    monkeypatch.setattr(mod, "_read", fake_read)
    errors = mod.check_versions()
    assert any("SECURITY.md" in e for e in errors)


def test_checker_detects_count_drift(monkeypatch):
    """A planted wrong component count must be reported."""
    mod = _load()
    real_actuals = mod._actuals

    monkeypatch.setattr(mod, "_actuals", lambda: {**real_actuals(), "agents": 999})
    errors = mod.check_counts()
    assert any("agents" in e for e in errors)


def test_checker_detects_skill_total_drift(monkeypatch):
    """The headline skill total (core + collection) is pinned to the filesystem, not just core."""
    mod = _load()
    real_actuals = mod._actuals

    monkeypatch.setattr(mod, "_actuals", lambda: {**real_actuals(), "skills": 999})
    errors = mod.check_counts()
    assert any("skills count says" in e for e in errors), errors


def test_checker_detects_duplicate_gate_tables(monkeypatch):
    """A second (stale) gate table must be flagged, not silently shadowed by a later correct one."""
    mod = _load()
    real_read = mod._read
    stale = (
        "| **lean** | stale-gate |\n"
        "| **standard** | stale-gate |\n"
        "| **enterprise** | stale-gate |\n\n"
    )

    def fake_read(rel: str) -> str:
        if rel == "README.md":
            return stale + real_read(rel)  # a stale table ahead of the real one
        return real_read(rel)

    monkeypatch.setattr(mod, "_read", fake_read)
    errors = mod.check_profile_gates()
    assert any("duplicate gate table" in e for e in errors), errors


def test_readme_profile_inventory_matches_resolved_default_stack(payload):
    """The current README table is derived from the catalog, including overlay agents."""
    readme = (_ROOT / "README.md").read_text(encoding="utf-8")
    core_rules = len(list((payload / "rules").glob("*.md")))

    for profile in ("lean", "standard", "enterprise"):
        match = re.search(
            rf"\| `{profile}`(?: \(default\))? \| (\d+) \| (\d+) \| (\d+) \|",
            readme,
        )
        assert match is not None, profile
        selection = make_selection(
            payload,
            profile=profile,
            scope="individual",
            teams=[],
            org_packs=False,
        )
        plan = catalog.resolve(payload, selection)
        expected = (
            len(set(plan.agents) | set(plan.overlay_agents)),
            len(plan.skills),
            core_rules + len(plan.overlay_rules),
        )
        assert tuple(map(int, match.groups())) == expected

    assert "installs the whole skill collection" not in readme


def test_directory_submission_hook_audit_matches_registry_and_static_plugin():
    """The release self-audit must name every handler and its real effect/channel."""
    text = (_ROOT / "docs/launch/directory-submission.md").read_text(encoding="utf-8")
    table = text.split("| Hook | Event | Mode | Network | In plugin hooks.json |", 1)[1]
    table = table.split("\n\n**Audit result:**", 1)[0]
    rows: dict[str, tuple[str, str]] = {}
    for line in table.splitlines():
        if not line.startswith("|") or line.startswith("|---"):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) == 5:
            rows[cells[0]] = (cells[2], cells[4])

    expected = set(hooks.HOOK_REGISTRY) | set(hooks.PLUGIN_ONLY_HOOKS)
    assert set(rows) == expected
    documented_plugin = {
        hook_id
        for hook_id, (_mode, plugin) in rows.items()
        if plugin.lower().startswith("yes")
    }
    assert documented_plugin == set(hooks.PLUGIN_HOOK_IDS) | set(
        hooks.PLUGIN_ONLY_HOOKS
    )
    for hook_id, (mode, _plugin) in rows.items():
        documented_blocking = "gated" in mode.lower()
        assert documented_blocking is (
            hooks.HOOK_SPECS[hook_id].effect is HookEffect.BLOCKING
        ), hook_id


def test_roadmap_names_the_current_native_manifest_schema():
    roadmap = (_ROOT / "docs/launch/road-to-1.0.md").read_text(encoding="utf-8")
    assert f"`schema_version` (currently `{INIT_OPTIONS_SCHEMA}`)" in roadmap
