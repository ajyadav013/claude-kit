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
