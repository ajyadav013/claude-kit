"""Validate the Claude Code *plugin* payload (manifest + hooks file).

These guard the plugin-distribution channel (as opposed to the pip CLI, which builds
``.claude/settings.json`` from ``claude_kit.hooks.HOOK_REGISTRY``). Claude Code loads a plugin's
hooks from the file named by ``plugin.json``'s ``hooks`` field, and — when that field is a *path* —
the file must be shaped like a settings fragment: a top-level ``hooks`` record mapping event names to
matcher groups. A flat ``{event: [...]}`` file is rejected with
``invalid_type … path: ["hooks"] … expected record, received undefined``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_MANIFEST = REPO_ROOT / ".claude-plugin" / "plugin.json"

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


def _hooks_file() -> Path:
    manifest = json.loads(PLUGIN_MANIFEST.read_text())
    ref = manifest["hooks"]
    assert isinstance(ref, str), (
        "this test covers the file-path form of plugin.json `hooks`"
    )
    return (REPO_ROOT / ref).resolve()


def test_plugin_hooks_file_is_wrapped() -> None:
    """The referenced hooks file must wrap events under a top-level ``hooks`` record."""
    data = json.loads(_hooks_file().read_text())
    assert isinstance(data, dict) and "hooks" in data, (
        "plugin hooks file must be {'hooks': {<event>: [...]}}; a flat event map is rejected "
        "by the plugin loader (expected record at path 'hooks', received undefined)"
    )
    assert isinstance(data["hooks"], dict) and data["hooks"], (
        "`hooks` must be a non-empty record"
    )


def test_plugin_hooks_event_structure() -> None:
    """Every event maps to matcher groups, each with a non-empty ``hooks`` list of typed entries."""
    events = json.loads(_hooks_file().read_text())["hooks"]
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
