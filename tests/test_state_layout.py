"""Single-control-plane discovery tests."""

from __future__ import annotations

from claude_kit.models import StateLayout
from claude_kit.state import detect_state_layout, state_path


def test_fresh_project_defaults_to_neutral_without_writing(tmp_path):
    target = tmp_path / "project"
    assert detect_state_layout(target) == StateLayout.neutral()
    assert not target.exists()


def test_legacy_state_remains_readable_until_neutral_marker_exists(tmp_path):
    target = tmp_path / "project"
    legacy = StateLayout.legacy_claude()
    neutral = StateLayout.neutral()
    (target / legacy.stack_snapshot).parent.mkdir(parents=True)
    (target / legacy.stack_snapshot).write_text("gates: []\n", encoding="utf-8")

    assert detect_state_layout(target) == legacy
    assert state_path(target, "stack_snapshot") == target / legacy.stack_snapshot

    (target / neutral.manifest).parent.mkdir(parents=True)
    (target / neutral.manifest).write_text("{}\n", encoding="utf-8")
    assert detect_state_layout(target) == neutral


def test_empty_neutral_directory_does_not_shadow_legacy_manifest(tmp_path):
    target = tmp_path / "project"
    legacy = StateLayout.legacy_claude()
    (target / ".ckit").mkdir(parents=True)
    (target / legacy.manifest).parent.mkdir(parents=True)
    (target / legacy.manifest).write_text("{}\n", encoding="utf-8")

    assert detect_state_layout(target) == legacy
