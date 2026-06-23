"""Validate the Claude Code *plugin* payload (manifest + hooks file).

These guard the plugin-distribution channel (as opposed to the pip CLI, which builds
``.claude/settings.json`` from ``claude_kit.hooks.HOOK_REGISTRY``). Claude Code **auto-discovers** a
plugin's ``hooks/hooks.json`` from the plugin root, and that file must be shaped like a settings
fragment: a top-level ``hooks`` record mapping event names to matcher groups. A flat ``{event: [...]}``
file is rejected (``invalid_type … path: ["hooks"] … expected record, received undefined``).

The manifest's ``hooks`` field is reserved for *additional* hook files. Pointing it back at the
auto-discovered ``./hooks/hooks.json`` makes the loader read the same file twice and fail with
``Hook load failed: Duplicate hooks file detected``, so this module also guards against that.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_MANIFEST = REPO_ROOT / ".claude-plugin" / "plugin.json"
HOOKS_FILE = REPO_ROOT / "hooks" / "hooks.json"

pytestmark = pytest.mark.skipif(
    not PLUGIN_MANIFEST.exists(),
    reason="plugin manifest only present in a source checkout, not the wheel",
)

VALID_EVENTS = {
    "PreToolUse",
    "PostToolUse",
    "UserPromptSubmit",
    "Notification",
    "Stop",
    "SubagentStop",
    "SessionStart",
    "SessionEnd",
    "PreCompact",
}


def test_plugin_hooks_file_is_wrapped() -> None:
    """The auto-discovered hooks file must wrap events under a top-level ``hooks`` record."""
    data = json.loads(HOOKS_FILE.read_text())
    assert isinstance(data, dict) and "hooks" in data, (
        "plugin hooks file must be {'hooks': {<event>: [...]}}; a flat event map is rejected "
        "by the plugin loader (expected record at path 'hooks', received undefined)"
    )
    assert isinstance(data["hooks"], dict) and data["hooks"], (
        "`hooks` must be a non-empty record"
    )


def test_plugin_hooks_event_structure() -> None:
    """Every event maps to matcher groups, each with a non-empty ``hooks`` list of typed entries."""
    events = json.loads(HOOKS_FILE.read_text())["hooks"]
    for event, groups in events.items():
        assert event in VALID_EVENTS, f"unknown hook event: {event}"
        assert isinstance(groups, list) and groups, f"{event} must be a non-empty list"
        for group in groups:
            entries = group.get("hooks")
            assert isinstance(entries, list) and entries, (
                f"{event} group needs a 'hooks' list"
            )
            for entry in entries:
                assert entry.get("type") in {"command", "prompt"}, (
                    f"{event}: bad hook type"
                )


def test_manifest_does_not_redeclare_standard_hooks() -> None:
    """``plugin.json`` must not point ``hooks`` at the auto-discovered ``./hooks/hooks.json``.

    Claude Code already loads ``hooks/hooks.json`` automatically; referencing it again in the manifest
    makes the loader read the same file twice and fail with "Duplicate hooks file detected". The
    manifest ``hooks`` field is reserved for *additional* hook files.
    """
    manifest = json.loads(PLUGIN_MANIFEST.read_text())
    ref = manifest.get("hooks")
    if ref is None:
        return  # relies purely on auto-discovery (the norm for claude-kit)
    # A string (or list of strings) is a path reference; an inline object declares hooks directly
    # (no path to collide). None of the referenced paths may resolve to the standard file.
    if isinstance(ref, str):
        paths = [ref]
    elif isinstance(ref, list):
        paths = [p for p in ref if isinstance(p, str)]
    else:
        paths = []
    for p in paths:
        assert (REPO_ROOT / p).resolve() != HOOKS_FILE.resolve(), (
            "plugin.json must not reference the auto-discovered ./hooks/hooks.json; it is loaded "
            "automatically, so re-declaring it triggers 'Duplicate hooks file detected'"
        )


def _load_gen_hooks():
    """Load scripts/gen_hooks.py (not a package) so tests share its exact JSON rendering."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "gen_hooks", REPO_ROOT / "scripts" / "gen_hooks.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_static_hook_files_match_registry() -> None:
    """hooks/hooks.json and templates/settings.json must equal the registry-driven generator output.

    This is the drift guard for the single-source-of-truth model: edit hooks.py, run
    `python scripts/gen_hooks.py`, commit. A hand-edit to either JSON file fails here.
    """
    from claude_kit import hooks

    gen = _load_gen_hooks()
    assert gen._render(hooks.generate_plugin_hooks_json()) == HOOKS_FILE.read_text(
        encoding="utf-8"
    ), "hooks/hooks.json drifted from the registry — run `python scripts/gen_hooks.py`"
    starter = REPO_ROOT / "templates" / "settings.json"
    assert gen._render(hooks.generate_starter_settings()) == starter.read_text(
        encoding="utf-8"
    ), (
        "templates/settings.json drifted from the registry — run `python scripts/gen_hooks.py`"
    )


def test_gen_hooks_check_reports_in_sync() -> None:
    """The `gen_hooks.py --check` entrypoint passes against the committed files."""
    assert _load_gen_hooks().main(["--check"]) == 0


def test_plugin_only_hooks_declared_with_reason() -> None:
    """Plugin-only hooks are explicit data (with a reason) and absent from the CLI registry."""
    from claude_kit import hooks

    assert hooks.PLUGIN_ONLY_HOOKS, "expected at least one declared plugin-only hook"
    for hid, spec in hooks.PLUGIN_ONLY_HOOKS.items():
        assert spec.get("reason"), f"plugin-only hook {hid} must carry a reason"
        assert hid not in hooks.HOOK_REGISTRY, (
            f"{hid} is plugin-only; not in HOOK_REGISTRY"
        )


def test_kubectl_guard_is_plugin_only() -> None:
    """guard-kubectl-delete ships in the plugin file but NOT the CLI starter or the registry."""
    from claude_kit import hooks

    assert "guard-kubectl-delete" in hooks.PLUGIN_ONLY_HOOKS
    assert "guard-kubectl-delete.sh" in HOOKS_FILE.read_text(encoding="utf-8")
    starter = (REPO_ROOT / "templates" / "settings.json").read_text(encoding="utf-8")
    assert "guard-kubectl-delete" not in starter


INIT_COMMAND = REPO_ROOT / "commands" / "init.md"
INIT_SH = REPO_ROOT / "scripts" / "init.sh"


def test_init_command_requires_cli_and_fails_loud() -> None:
    """/claude-kit:init must require the CLI and refuse to silently degrade when it's absent."""
    text = INIT_COMMAND.read_text(encoding="utf-8")
    assert "CKIT_CLI_MISSING" in text and "STOP" in text, (
        "must detect a missing CLI and stop"
    )
    assert (
        "pipx install claude-code-kit" in text or "pip install claude-code-kit" in text
    )
    # The thin fallback must be opt-in (gated behind CLAUDE_KIT_BASIC), never the silent default.
    assert "CLAUDE_KIT_BASIC" in text
    assert (
        "do not scaffold anything" in text.lower()
        or "not silently fall back" in text.lower()
    )


def test_basic_scaffolder_warns_it_is_degraded() -> None:
    """The no-pip shell scaffolder must announce that it is a degraded, no-resolution install."""
    text = INIT_SH.read_text(encoding="utf-8")
    assert "BASIC scaffolder" in text
    assert "upgrade" in text and "NOT work" in text
