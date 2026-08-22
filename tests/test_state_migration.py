"""Transactional legacy Claude-state migration coverage."""

from __future__ import annotations

import hashlib
import json
import stat
from pathlib import Path

import pytest

from claude_kit import state_migration
from claude_kit.models import InitOptions, StateLayout
from claude_kit.secure_fs import UnsafePathError
from claude_kit.state import detect_state_layout
from claude_kit.state_migration import (
    StateMigrationConflictError,
    migrate_legacy_state,
)
from tests._helpers import make_selection


def _write(path: Path, content: bytes, *, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    path.chmod(mode)


def _legacy_project(project: Path, payload: Path) -> dict[str, bytes]:
    files = {
        ".claude/config/stack-catalog.snapshot.yaml": (
            b"schema_version: 1\ngates:\n  - code-review\n"
        ),
        ".claude/config/user-overrides.json": b'{"keep": "user edit"}\n',
        ".claude/CONTINUITY.md": b"# Continuity\n\nuser-edited next step\n",
        ".claude/agent-memory/MEMORY.md": b"# Memory\n\nUser index\n",
        ".claude/agent-memory/gotchas/user.md": b"hard-won bytes\x00\xff",
        ".claude/artifacts/security-review.bin": b"\x00evidence\xff",
        ".claude/state/pipeline-snapshot.json": json.dumps(
            {
                "status": "active",
                "gate_history": [
                    {
                        "gate": "code-review",
                        "status": "passed",
                        "evidence_path": ".claude/state/evidence/review.bin",
                    }
                ],
            },
            separators=(",", ":"),
        ).encode("utf-8"),
        ".claude/state/tickets/index.json": b'{"tickets":{"CKIT-1":{"status":"OPEN"}}}',
        ".claude/state/evidence/review.bin": b"review\x00proof\xff",
        ".claude/tmp/resume.dat": b"temporary resume bytes\n",
    }
    for rel, content in files.items():
        mode = 0o751 if rel == ".claude/artifacts/security-review.bin" else 0o644
        _write(project / rel, content, mode=mode)
    (project / ".claude/agent-memory/empty-category").mkdir(parents=True)

    tracked = [
        ".claude/config/stack-catalog.snapshot.yaml",
        ".claude/CONTINUITY.md",
        ".claude/agent-memory/MEMORY.md",
        ".claude/agent-memory/gotchas/user.md",
        ".claude/rules/user-edited.md",
    ]
    _write(project / ".claude/rules/user-edited.md", b"# Claude discovery edit\n")
    _write(project / ".claude/settings.json", b'{"userSetting":true}\n')
    _write(project / ".claude/CONTINUITY.template.md", b"discovery seed\n")
    ticket = project / "docs/project/tickets/CKIT-1-user-ticket.md"
    _write(ticket, b"# CKIT-1: Preserve me\n")

    records = [
        {
            "path": rel,
            "sha256": hashlib.sha256((project / rel).read_bytes()).hexdigest(),
            "owner": "user-editable"
            if "CONTINUITY" in rel or "agent-memory" in rel
            else "kit",
        }
        for rel in tracked
    ]
    manifest = {
        "schema_version": 1,
        "claude_kit_version": "0.83.0",
        "selection": make_selection(payload).to_dict(),
        "files": records,
        "user_metadata": {"preserve": "unknown top-level field"},
    }
    manifest_bytes = json.dumps(manifest, indent=4).encode("utf-8")
    _write(project / ".claude/config/init-options.json", manifest_bytes)
    legacy_journal = b'{"schema_version":1,"from_version":"0.82.0","actions":[]}\n'
    _write(project / ".claude/config/upgrade-in-progress.json", legacy_journal)
    files[".claude/config/init-options.json"] = manifest_bytes
    files[".claude/config/upgrade-in-progress.json"] = legacy_journal
    files[".claude/rules/user-edited.md"] = b"# Claude discovery edit\n"
    files[".claude/settings.json"] = b'{"userSetting":true}\n'
    files[".claude/CONTINUITY.template.md"] = b"discovery seed\n"
    files["docs/project/tickets/CKIT-1-user-ticket.md"] = ticket.read_bytes()
    return files


def _snapshot_tree(root: Path) -> dict[str, tuple[str, bytes | None, int]]:
    if not root.exists():
        return {}
    snapshot: dict[str, tuple[str, bytes | None, int]] = {}
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix()
        info = path.lstat()
        if path.is_symlink():
            snapshot[rel] = (
                "link",
                str(path.readlink()).encode(),
                stat.S_IMODE(info.st_mode),
            )
        elif path.is_dir():
            snapshot[rel] = ("dir", None, stat.S_IMODE(info.st_mode))
        else:
            snapshot[rel] = ("file", path.read_bytes(), stat.S_IMODE(info.st_mode))
    return snapshot


def test_migration_preserves_mutable_bytes_and_leaves_claude_discovery(
    tmp_path, payload
):
    project = tmp_path / "project"
    legacy_bytes = _legacy_project(project, payload)
    _write(project / ".ckit/state/neutral-only.log", b"keep neutral extra\n")
    _write(
        project / ".ckit/agent-memory/MEMORY.md",
        legacy_bytes[".claude/agent-memory/MEMORY.md"],
        mode=0o600,
    )

    result = migrate_legacy_state(project)

    assert result.migrated
    destinations = {
        ".claude/config/stack-catalog.snapshot.yaml": ".ckit/config/stack-catalog.snapshot.yaml",
        ".claude/config/user-overrides.json": ".ckit/config/user-overrides.json",
        ".claude/CONTINUITY.md": ".ckit/CONTINUITY.md",
        ".claude/agent-memory/MEMORY.md": ".ckit/agent-memory/MEMORY.md",
        ".claude/agent-memory/gotchas/user.md": ".ckit/agent-memory/gotchas/user.md",
        ".claude/artifacts/security-review.bin": ".ckit/artifacts/security-review.bin",
        ".claude/state/pipeline-snapshot.json": ".ckit/state/pipeline-snapshot.json",
        ".claude/state/tickets/index.json": ".ckit/state/tickets/index.json",
        ".claude/state/evidence/review.bin": ".ckit/state/evidence/review.bin",
        ".claude/tmp/resume.dat": ".ckit/tmp/resume.dat",
    }
    for source, destination in destinations.items():
        assert (project / destination).read_bytes() == legacy_bytes[source]
        assert (project / source).read_bytes() == legacy_bytes[source]
    assert (
        stat.S_IMODE((project / ".ckit/artifacts/security-review.bin").stat().st_mode)
        == 0o751
    )
    assert (project / ".ckit/agent-memory/empty-category").is_dir()
    assert (project / ".ckit/state/neutral-only.log").read_bytes() == (
        b"keep neutral extra\n"
    )

    migrated_manifest = json.loads(
        (project / ".ckit/config/init-options.json").read_text(encoding="utf-8")
    )
    options = InitOptions.from_dict(migrated_manifest)
    assert options.state_layout == StateLayout.neutral()
    assert detect_state_layout(project) == StateLayout.neutral()
    assert options.runtimes == ["claude"]
    assert migrated_manifest["user_metadata"] == {"preserve": "unknown top-level field"}
    records = {record.path: record for record in options.files}
    assert records[".ckit/agent-memory/MEMORY.md"].provider == "shared"
    assert records[".claude/rules/user-edited.md"].provider == "claude"
    assert stat.S_IMODE((project / ".ckit/agent-memory/MEMORY.md").stat().st_mode) == (
        0o600
    )

    # Transient migration machinery is not imported. Claude-native discovery
    # payload and the external ticket source of truth remain byte-identical.
    assert not (project / ".ckit/config/upgrade-in-progress.json").exists()
    for rel, content in legacy_bytes.items():
        assert (project / rel).read_bytes() == content
    assert not (project / ".ckit/rules").exists()
    assert not (project / ".ckit/settings.json").exists()

    # A completed neutral manifest is the convergence marker. Newer neutral user
    # edits are authoritative and a rerun never overwrites them from legacy data.
    _write(project / ".ckit/CONTINUITY.md", b"new neutral user edit\n")
    rerun = migrate_legacy_state(project)
    assert not rerun.migrated and rerun.already_neutral
    assert (project / ".ckit/CONTINUITY.md").read_bytes() == b"new neutral user edit\n"


def test_conflicting_partial_destination_fails_without_mutation(tmp_path, payload):
    project = tmp_path / "project"
    _legacy_project(project, payload)
    _write(project / ".ckit/agent-memory/MEMORY.md", b"independent neutral edit\n")
    before = _snapshot_tree(project)

    with pytest.raises(StateMigrationConflictError) as raised:
        migrate_legacy_state(project)

    assert raised.value.conflicts == (".ckit/agent-memory/MEMORY.md",)
    assert _snapshot_tree(project) == before
    assert not list(project.glob(".claude-kit-txn-*"))
    assert not (project / ".ckit/config/upgrade-in-progress.json").exists()


def test_runtime_failure_rolls_back_both_state_roots(tmp_path, payload, monkeypatch):
    project = tmp_path / "project"
    _legacy_project(project, payload)
    before = _snapshot_tree(project)
    calls = 0

    def fail_second_copy(_fs, _source, _destination):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("injected migration failure")

    monkeypatch.setattr(state_migration, "_before_copy", fail_second_copy)
    with pytest.raises(RuntimeError, match="injected migration failure"):
        migrate_legacy_state(project)

    assert calls == 2
    assert _snapshot_tree(project) == before
    assert not (project / ".ckit").exists()
    assert not list(project.glob(".claude-kit-txn-*"))


class _SimulatedMigrationProcessDeath(BaseException):
    pass


def test_interrupted_migration_recovers_then_converges(tmp_path, payload, monkeypatch):
    project = tmp_path / "project"
    legacy_bytes = _legacy_project(project, payload)
    calls = 0

    def die_after_one_copy(_fs, _source, _destination):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise _SimulatedMigrationProcessDeath()

    monkeypatch.setattr(state_migration, "_before_copy", die_after_one_copy)
    with pytest.raises(_SimulatedMigrationProcessDeath):
        migrate_legacy_state(project)

    assert (project / ".ckit/config/upgrade-in-progress.json").is_file()
    assert list(project.glob(".claude-kit-txn-*"))

    monkeypatch.undo()
    result = migrate_legacy_state(project)
    assert result.migrated and result.recovered
    assert not (project / ".ckit/config/upgrade-in-progress.json").exists()
    assert not list(project.glob(".claude-kit-txn-*"))
    assert (project / ".ckit/state/evidence/review.bin").read_bytes() == (
        legacy_bytes[".claude/state/evidence/review.bin"]
    )
    for rel, content in legacy_bytes.items():
        assert (project / rel).read_bytes() == content


def test_migration_refuses_a_symlink_inside_legacy_state(tmp_path, payload):
    project = tmp_path / "project"
    _legacy_project(project, payload)
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "sentinel.bin"
    sentinel.write_bytes(b"safe\n")
    (project / ".claude/state/linked-evidence").symlink_to(
        outside, target_is_directory=True
    )

    with pytest.raises(UnsafePathError, match="symlink|reparse|junction"):
        migrate_legacy_state(project)
    assert sentinel.read_bytes() == b"safe\n"
    assert not (project / ".ckit").exists()
    assert not list(project.glob(".claude-kit-txn-*"))


def test_migration_refuses_a_symlinked_neutral_root(tmp_path, payload):
    project = tmp_path / "project"
    _legacy_project(project, payload)
    outside = tmp_path / "outside"
    outside.mkdir()
    (project / ".ckit").symlink_to(outside, target_is_directory=True)

    with pytest.raises(UnsafePathError, match="symlink|reparse|junction"):
        migrate_legacy_state(project)
    assert not list(outside.iterdir())
    assert (project / ".ckit").is_symlink()
    assert not list(project.glob(".claude-kit-txn-*"))
