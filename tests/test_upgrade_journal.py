"""Transactional upgrade journal (P2-14).

The schema-2 journal is written after a rollback snapshot and before the first live
mutation. Ordinary exceptions restore the snapshot immediately; process-level
interruptions retain journal + snapshot so the next invocation recovers before
recomputing and applying the upgrade.
"""

from __future__ import annotations

import json

import pytest

from claude_kit import catalog, upgrader, validator
from claude_kit.models import UPGRADE_JOURNAL
from tests._helpers import install, make_selection


def _journal(target):
    return target / ".claude" / "config" / UPGRADE_JOURNAL


def _drift_a_kit_file(target):
    """Corrupt a kit-owned file so the next upgrade/merge has a real `update` action to perform."""
    rule = target / ".claude" / "rules" / "testing.md"
    assert rule.is_file(), "expected a core kit rule to exist"
    rule.write_text("DRIFTED\n", encoding="utf-8")
    return rule


def _raise(*_a, **_k):
    raise RuntimeError("simulated crash mid-apply")


def test_successful_upgrade_leaves_no_journal(tmp_path, payload):
    install(payload, tmp_path)
    ok, msgs = upgrader.upgrade(tmp_path)
    assert ok, msgs
    assert not _journal(tmp_path).exists()


def test_journal_is_gitignored(tmp_path, payload):
    install(payload, tmp_path)
    gi = (tmp_path / ".gitignore").read_text(encoding="utf-8")
    assert f".claude/config/{UPGRADE_JOURNAL}" in gi


def test_ordinary_pre_apply_failure_rolls_back_without_a_journal(
    tmp_path, payload, monkeypatch
):
    install(payload, tmp_path)
    rule = _drift_a_kit_file(tmp_path)

    monkeypatch.setattr(upgrader, "_next_backup_dir", _raise)
    with pytest.raises(RuntimeError):
        upgrader.upgrade(tmp_path)
    assert not _journal(tmp_path).exists()
    assert rule.read_text(encoding="utf-8") == "DRIFTED\n"

    monkeypatch.undo()
    ok, msgs = upgrader.upgrade(tmp_path)
    assert ok, msgs
    assert not _journal(tmp_path).exists()
    assert (tmp_path / ".claude" / "rules" / "testing.md").read_text(
        encoding="utf-8"
    ) != "DRIFTED\n"


def test_stale_journal_on_current_tree_is_cleared(tmp_path, payload):
    """An upgrade interrupted *after* the baseline committed leaves a journal on an up-to-date tree."""
    install(payload, tmp_path)
    _journal(tmp_path).write_text(
        json.dumps(
            {
                "schema_version": 1,
                "from_version": "0.1.0",
                "to_version": "0.2.0",
                "started_at": "2026-01-01T00:00:00+00:00",
                "actions": [],
            }
        ),
        encoding="utf-8",
    )
    ok, msgs = upgrader.upgrade(tmp_path)
    assert ok, msgs
    assert not _journal(tmp_path).exists()
    assert any("leftover upgrade journal" in m for m in msgs)


def test_doctor_warns_on_leftover_journal(tmp_path, payload):
    install(payload, tmp_path)
    _journal(tmp_path).write_text(
        json.dumps(
            {
                "from_version": "0.1.0",
                "to_version": "0.2.0",
                "started_at": "2026-01-01T00:00:00+00:00",
                "actions": [],
            }
        ),
        encoding="utf-8",
    )
    _ok, msgs = validator.doctor(tmp_path)
    warn = [m for m in msgs if "interrupted upgrade" in m]
    assert warn, msgs
    assert "0.1.0 -> 0.2.0" in warn[0]


def test_doctor_journal_warning_tolerates_corrupt_journal(tmp_path, payload):
    install(payload, tmp_path)
    _journal(tmp_path).write_text("{ not json", encoding="utf-8")
    ok, msgs = validator.doctor(tmp_path)
    assert ok
    assert any(
        "interrupted transaction marker could not be inspected safely" in message
        and "corrupt" in message
        for message in msgs
    )


def test_merge_pre_apply_failure_leaves_no_journal(tmp_path, payload, monkeypatch):
    """A failure before merge's transaction begins has nothing to recover."""
    install(payload, tmp_path)
    _drift_a_kit_file(tmp_path)
    plan = catalog.resolve(payload, make_selection(payload))

    monkeypatch.setattr(upgrader, "_next_backup_dir", _raise)
    with pytest.raises(RuntimeError):
        upgrader.merge_install(payload, tmp_path, plan)
    assert not _journal(tmp_path).exists()


def test_mid_apply_ordinary_exception_rolls_the_tree_back(
    tmp_path, payload, monkeypatch
):
    install(payload, tmp_path)
    rule_a = tmp_path / ".claude" / "rules" / "continuity.md"
    rule_b = tmp_path / ".claude" / "rules" / "testing.md"
    pristine_a = rule_a.read_text(encoding="utf-8")
    pristine_b = rule_b.read_text(encoding="utf-8")
    rule_a.write_text("DRIFTED\n", encoding="utf-8")
    rule_b.write_text("DRIFTED\n", encoding="utf-8")

    real_copy = upgrader.ProjectFS.copy_file
    mutations = 0

    def fail_once(self, source, rel):
        nonlocal mutations
        rel_text = str(rel)
        if self.root == tmp_path and not rel_text.startswith(".claude-kit-txn-"):
            mutations += 1
            if mutations == 3:
                raise RuntimeError("simulated crash mid-apply")
        return real_copy(self, source, rel)

    monkeypatch.setattr(upgrader.ProjectFS, "copy_file", fail_once)
    with pytest.raises(RuntimeError, match="mid-apply"):
        upgrader.upgrade(tmp_path)
    monkeypatch.undo()

    assert not _journal(tmp_path).exists()
    assert rule_a.read_text(encoding="utf-8") == "DRIFTED\n"
    assert rule_b.read_text(encoding="utf-8") == "DRIFTED\n"

    ok, msgs = upgrader.upgrade(tmp_path)
    assert ok, msgs
    assert rule_a.read_text(encoding="utf-8") == pristine_a
    assert rule_b.read_text(encoding="utf-8") == pristine_b


class _SimulatedProcessDeath(BaseException):
    pass


def test_process_death_leaves_recovery_journal_and_next_run_restores_then_converges(
    tmp_path, payload, monkeypatch
):
    install(payload, tmp_path)
    rule_a = tmp_path / ".claude" / "rules" / "continuity.md"
    rule_b = tmp_path / ".claude" / "rules" / "testing.md"
    pristine_a = rule_a.read_text(encoding="utf-8")
    pristine_b = rule_b.read_text(encoding="utf-8")
    rule_a.write_text("DRIFTED\n", encoding="utf-8")
    rule_b.write_text("DRIFTED\n", encoding="utf-8")

    real_copy = upgrader.ProjectFS.copy_file
    mutations = 0

    def die_once(self, source, rel):
        nonlocal mutations
        rel_text = str(rel)
        if self.root == tmp_path and not rel_text.startswith(".claude-kit-txn-"):
            mutations += 1
            if mutations == 3:
                raise _SimulatedProcessDeath()
        return real_copy(self, source, rel)

    monkeypatch.setattr(upgrader.ProjectFS, "copy_file", die_once)
    with pytest.raises(_SimulatedProcessDeath):
        upgrader.upgrade(tmp_path)
    monkeypatch.undo()

    assert _journal(tmp_path).is_file()

    ok, msgs = upgrader.upgrade(tmp_path)
    assert ok, msgs
    assert not _journal(tmp_path).exists()
    assert rule_a.read_text(encoding="utf-8") == pristine_a
    assert rule_b.read_text(encoding="utf-8") == pristine_b
    ok, msgs = upgrader.upgrade(tmp_path)
    assert ok and any("nothing to upgrade" in m for m in msgs)
