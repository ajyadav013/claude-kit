"""Transactional upgrade journal (P2-14).

The journal (`.claude/config/upgrade-in-progress.json`) is written *before* `upgrade` mutates the tree
and removed only after the new baseline commits. Because `upgrade` is convergent, a journal left by an
interrupted run is cleared by the next run; `doctor` warns while one is present; `merge_install` never
writes one; and it is gitignored so it is never committed.

Interruptions are simulated by patching `_next_backup_dir`, which `_apply` calls immediately *after*
writing the journal and *before* the first file mutation — so a raise there reproduces a crash with the
journal already on disk and no files touched. (Patching `shutil.copy2` would be wrong: `shutil` is one
shared module object, so it would also break the reference build that runs before `_apply`.)
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


def test_interrupted_upgrade_leaves_journal_then_resumes(
    tmp_path, payload, monkeypatch
):
    install(payload, tmp_path)
    _drift_a_kit_file(tmp_path)

    monkeypatch.setattr(upgrader, "_next_backup_dir", _raise)
    with pytest.raises(RuntimeError):
        upgrader.upgrade(tmp_path)
    # The journal was written before the (failed) backup/mutation step.
    assert _journal(tmp_path).exists()

    # Resume: re-running the real (convergent) upgrade finishes the work and clears the journal.
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
    _ok, msgs = validator.doctor(tmp_path)
    assert any("interrupted upgrade detected" in m for m in msgs)


def test_merge_install_does_not_write_a_journal(tmp_path, payload, monkeypatch):
    """The non-destructive merge path is not journaled — gating is to `upgrade` only."""
    install(payload, tmp_path)
    _drift_a_kit_file(tmp_path)
    plan = catalog.resolve(payload, make_selection(payload))

    monkeypatch.setattr(upgrader, "_next_backup_dir", _raise)
    with pytest.raises(RuntimeError):
        upgrader.merge_install(payload, tmp_path, plan)
    assert not _journal(tmp_path).exists()


class _CrashingShutil:
    """Delegate to the real shutil but raise on the Nth copy2 call.

    Patching the ``upgrader.shutil`` *attribute* (not the shared shutil module itself) confines
    the crash to the upgrader's own calls — scaffold's reference build, which runs earlier inside
    ``upgrade()``, keeps the real module and stays intact. This is how a crash *inside* the
    ``_apply`` mutation loop is simulated, unlike ``_next_backup_dir`` which crashes before any
    file is touched.
    """

    def __init__(self, real, crash_after: int) -> None:
        self._real = real
        self._copies = 0
        self._crash_after = crash_after

    def copy2(self, *a, **k):
        self._copies += 1
        if self._copies > self._crash_after:
            raise RuntimeError("simulated crash mid-apply")
        return self._real.copy2(*a, **k)

    def __getattr__(self, name):
        return getattr(self._real, name)


def test_mid_apply_crash_leaves_partial_state_then_resumes(
    tmp_path, payload, monkeypatch
):
    """Crash AFTER the first file was mutated (not before, like the _next_backup_dir test):
    the tree is genuinely half-upgraded, the journal is on disk, and a plain re-run converges."""
    import shutil as real_shutil

    install(payload, tmp_path)
    rule_a = tmp_path / ".claude" / "rules" / "continuity.md"
    rule_b = tmp_path / ".claude" / "rules" / "testing.md"
    pristine_a = rule_a.read_text(encoding="utf-8")
    pristine_b = rule_b.read_text(encoding="utf-8")
    rule_a.write_text("DRIFTED\n", encoding="utf-8")
    rule_b.write_text("DRIFTED\n", encoding="utf-8")

    # Two drifted kit files -> actions sorted by path: [continuity, testing], each doing
    # copy2 twice (backup, then restore). crash_after=2 = die on testing.md's backup:
    # continuity.md is already healed, testing.md still drifted.
    monkeypatch.setattr(upgrader, "shutil", _CrashingShutil(real_shutil, crash_after=2))
    with pytest.raises(RuntimeError, match="mid-apply"):
        upgrader.upgrade(tmp_path)
    monkeypatch.undo()

    assert _journal(tmp_path).exists()  # transaction visibly open
    assert rule_a.read_text(encoding="utf-8") == pristine_a  # first mutation landed
    assert rule_b.read_text(encoding="utf-8") == "DRIFTED\n"  # second never ran

    # Convergent resume: a plain re-run finishes the remaining work and commits.
    ok, msgs = upgrader.upgrade(tmp_path)
    assert ok, msgs
    assert not _journal(tmp_path).exists()
    assert rule_b.read_text(encoding="utf-8") == pristine_b
    # And a third run is a clean no-op.
    ok, msgs = upgrader.upgrade(tmp_path)
    assert ok and any("nothing to upgrade" in m for m in msgs)
