"""hooks: the registry's settings-entry builders and the privacy report derived from them."""

from __future__ import annotations

import json

from claude_kit import hooks
from tests._helpers import install


def test_plugin_entry_uses_the_plugin_root_placeholder():
    entry = hooks._plugin_entry("load-continuity.sh")
    assert entry["type"] == "command"
    assert "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/load-continuity.sh" in entry["command"]
    assert "timeout" not in entry


def test_plugin_entry_appends_an_argument_and_a_timeout():
    """The arg is what distinguishes two hooks that share one script (e.g. capture modes)."""
    entry = hooks._plugin_entry("capture-learnings.sh", arg="catchup", timeout=30)
    assert entry["command"].endswith('capture-learnings.sh" catchup')
    assert entry["timeout"] == 30


def test_project_entry_uses_the_project_dir_placeholder():
    entry = hooks._script_entry("load-continuity.sh", arg="x", timeout=5)
    assert entry["command"].endswith('/.claude/hooks/load-continuity.sh" x')
    assert "${CLAUDE_PROJECT_DIR}" in entry["command"]
    assert entry["timeout"] == 5


def test_privacy_report_lists_installed_hooks_with_their_data_access(tmp_path, payload):
    install(payload, tmp_path)
    ok, msgs = hooks.privacy_report(tmp_path)
    assert ok, "\n".join(msgs)
    assert any("privacy report" in m for m in msgs)


def test_privacy_report_fails_on_unparseable_settings(tmp_path, payload):
    install(payload, tmp_path)
    (tmp_path / ".claude" / "settings.json").write_text("{ nope", encoding="utf-8")
    ok, msgs = hooks.privacy_report(tmp_path)
    assert not ok
    assert any("not valid JSON" in m for m in msgs)


def test_privacy_report_ignores_a_malformed_event_block(tmp_path, payload):
    """A hand-edited event whose value is not a list must be skipped, not crash the report."""
    install(payload, tmp_path)
    settings = tmp_path / ".claude" / "settings.json"
    doc = json.loads(settings.read_text(encoding="utf-8"))
    doc["hooks"]["SessionEnd"] = "not-a-list"
    settings.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    ok, msgs = hooks.privacy_report(tmp_path)
    assert ok, "\n".join(msgs)
    assert not any("not-a-list" in m for m in msgs)


def test_privacy_report_flags_a_foreign_hook_command(tmp_path, payload):
    install(payload, tmp_path)
    settings = tmp_path / ".claude" / "settings.json"
    doc = json.loads(settings.read_text(encoding="utf-8"))
    doc["hooks"]["SessionStart"] = [
        {"matcher": "", "hooks": [{"type": "command", "command": "bash /opt/other.sh"}]}
    ]
    settings.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    ok, msgs = hooks.privacy_report(tmp_path)
    assert any("not from this kit" in m for m in msgs)
