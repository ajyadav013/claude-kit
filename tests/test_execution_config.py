"""Transactional project-scoped maker/reviewer configuration."""

from __future__ import annotations

import json
import os
import threading

import pytest

from claude_kit import execution_config as execution_config_module
from claude_kit import execution_lease as execution_lease_module
from claude_kit.execution_config import (
    ExecutionConfigError,
    configure_execution_policy,
    disable_execution_policy,
    load_execution_policy,
)
from claude_kit.execution_lease import (
    ManagedExecutionLeaseHeld,
    managed_execution_lease,
)
from claude_kit.models import (
    ExecutionPolicy,
    InitOptions,
    ModelChoice,
    StateLayout,
    WorkerBinding,
)
from claude_kit.secure_fs import ProjectFS, ProjectTransaction, UnsafePathError
from tests._helpers import make_selection


def _policy() -> ExecutionPolicy:
    return ExecutionPolicy(
        maker=WorkerBinding("claude", ModelChoice("tier", "deep")),
        reviewer=WorkerBinding("codex", ModelChoice("exact", "gpt-reviewer")),
        max_revisions=2,
    )


def _write_manifest(target, payload, *, execution_policy=None) -> None:
    options = InitOptions(
        claude_kit_version="0.0.0-test",
        selection=make_selection(payload),
        files=[],
        runtimes=["claude", "codex"],
        state_layout=StateLayout.neutral(),
        compatibility_catalog_versions={"claude": 1, "codex": 1},
        execution_policy=execution_policy,
    )
    manifest = target / StateLayout.neutral().manifest
    manifest.parent.mkdir(parents=True)
    document = options.to_dict()
    document["future_extension"] = {"preserve": True}
    manifest.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")


class _SimulatedConfigProcessDeath(BaseException):
    pass


class _SimulatedLeaseInitializationDeath(BaseException):
    pass


def _leave_interrupted_manifest(target, *, future_extension) -> None:
    """Leave a schema-v2 transaction whose live manifest is only partial."""

    fs = ProjectFS(target)
    manifest = StateLayout.neutral().manifest
    with pytest.raises(_SimulatedConfigProcessDeath):
        with ProjectTransaction(
            fs,
            operation="upgrade",
            protected_paths=(StateLayout.neutral().root,),
            journal_path=StateLayout.neutral().journal,
        ):
            partial = json.loads(fs.read_text(manifest))
            partial["future_extension"] = future_extension
            fs.write_text(manifest, json.dumps(partial, indent=2) + "\n")
            raise _SimulatedConfigProcessDeath()


def test_configure_round_trips_policy_and_preserves_unknown_manifest_keys(
    tmp_path, payload
):
    _write_manifest(tmp_path, payload)
    manifest = tmp_path / StateLayout.neutral().manifest
    before = json.loads(manifest.read_text(encoding="utf-8"))
    before["selection"]["future_selection_key"] = {"preserve": [1, 2, 3]}
    before["state_layout"]["future_layout_key"] = "preserve-me"
    manifest.write_text(json.dumps(before, indent=2) + "\n", encoding="utf-8")

    configured = configure_execution_policy(tmp_path, _policy())

    assert configured == _policy()
    assert load_execution_policy(tmp_path) == _policy()
    document = json.loads(
        (tmp_path / StateLayout.neutral().manifest).read_text(encoding="utf-8")
    )
    assert document["execution"] == _policy().to_dict()
    assert document["future_extension"] == {"preserve": True}
    assert document["selection"]["future_selection_key"] == {"preserve": [1, 2, 3]}
    assert document["state_layout"]["future_layout_key"] == "preserve-me"
    assert not (tmp_path / StateLayout.legacy_claude().manifest).exists()


def test_disable_is_idempotent_and_preserves_the_shared_manifest(tmp_path, payload):
    _write_manifest(tmp_path, payload, execution_policy=_policy())
    manifest = tmp_path / StateLayout.neutral().manifest
    before = json.loads(manifest.read_text(encoding="utf-8"))
    before["selection"]["future_selection_key"] = {"preserve": True}
    before["state_layout"]["future_layout_key"] = ["preserve"]
    manifest.write_text(json.dumps(before, indent=2) + "\n", encoding="utf-8")

    assert disable_execution_policy(tmp_path) is True
    assert disable_execution_policy(tmp_path) is False
    assert load_execution_policy(tmp_path) is None
    document = json.loads(
        (tmp_path / StateLayout.neutral().manifest).read_text(encoding="utf-8")
    )
    assert document["execution"] is None
    assert document["future_extension"] == {"preserve": True}
    assert document["selection"]["future_selection_key"] == {"preserve": True}
    assert document["state_layout"]["future_layout_key"] == ["preserve"]


def test_configuration_requires_a_neutral_runtime_aware_install(tmp_path):
    with pytest.raises(ExecutionConfigError, match="neutral .ckit"):
        load_execution_policy(tmp_path)


def test_configuration_refuses_a_corrupt_manifest_without_rewriting_it(
    tmp_path,
):
    manifest = tmp_path / StateLayout.neutral().manifest
    manifest.parent.mkdir(parents=True)
    original = b'{"schema_version":3,"execution":'
    manifest.write_bytes(original)

    with pytest.raises(ExecutionConfigError, match="corrupt"):
        configure_execution_policy(tmp_path, _policy())

    assert manifest.read_bytes() == original


def test_read_only_configuration_refuses_an_interrupted_transaction(tmp_path, payload):
    _write_manifest(tmp_path, payload)
    _leave_interrupted_manifest(tmp_path, future_extension={"partial": True})

    with pytest.raises(ExecutionConfigError, match="requires recovery"):
        load_execution_policy(tmp_path)

    document = json.loads(
        (tmp_path / StateLayout.neutral().manifest).read_text(encoding="utf-8")
    )
    assert document["future_extension"] == {"partial": True}


def test_configure_recovers_before_reading_the_manifest(tmp_path, payload):
    _write_manifest(tmp_path, payload)
    _leave_interrupted_manifest(tmp_path, future_extension={"partial": True})

    configure_execution_policy(tmp_path, _policy())

    document = json.loads(
        (tmp_path / StateLayout.neutral().manifest).read_text(encoding="utf-8")
    )
    assert document["execution"] == _policy().to_dict()
    assert document["future_extension"] == {"preserve": True}
    assert not (tmp_path / StateLayout.neutral().journal).exists()
    assert not list(tmp_path.glob(".claude-kit-txn-*"))


def test_disable_recovers_before_reading_the_manifest(tmp_path, payload):
    _write_manifest(tmp_path, payload, execution_policy=_policy())
    _leave_interrupted_manifest(tmp_path, future_extension={"partial": True})

    assert disable_execution_policy(tmp_path) is True

    document = json.loads(
        (tmp_path / StateLayout.neutral().manifest).read_text(encoding="utf-8")
    )
    assert document["execution"] is None
    assert document["future_extension"] == {"preserve": True}
    assert not (tmp_path / StateLayout.neutral().journal).exists()
    assert not list(tmp_path.glob(".claude-kit-txn-*"))


def test_configuration_holds_the_project_lease_across_manifest_read(
    tmp_path, payload, monkeypatch
):
    _write_manifest(tmp_path, payload)
    read_started = threading.Event()
    continue_write = threading.Event()
    errors: list[BaseException] = []
    original = execution_config_module._load_document

    def paused_load(fs):
        loaded = original(fs)
        read_started.set()
        if not continue_write.wait(timeout=5):
            raise AssertionError("test did not release the configuration writer")
        return loaded

    monkeypatch.setattr(execution_config_module, "_load_document", paused_load)

    def configure() -> None:
        try:
            configure_execution_policy(tmp_path, _policy())
        except BaseException as exc:  # pragma: no cover - asserted below
            errors.append(exc)

    worker = threading.Thread(target=configure)
    worker.start()
    assert read_started.wait(timeout=5)
    try:
        with pytest.raises(UnsafePathError, match="project mutation is busy"):
            with ProjectFS(tmp_path).mutation_lease(exclusive=True):
                pass
    finally:
        continue_write.set()
        worker.join(timeout=5)

    assert not worker.is_alive()
    assert errors == []
    assert load_execution_policy(tmp_path) == _policy()


def test_configuration_rollback_cannot_replace_the_managed_lease_inode(
    tmp_path, payload, monkeypatch
):
    _write_manifest(tmp_path, payload)
    original_write = ProjectFS.write_text
    injected = False

    def fail_after_manifest_write(self, rel, text, **kwargs):
        nonlocal injected
        written = original_write(self, rel, text, **kwargs)
        if rel == StateLayout.neutral().manifest and not injected:
            injected = True
            raise OSError("injected post-write failure")
        return written

    monkeypatch.setattr(ProjectFS, "write_text", fail_after_manifest_write)

    with managed_execution_lease(tmp_path):
        with pytest.raises(ExecutionConfigError, match="injected post-write failure"):
            configure_execution_policy(tmp_path, _policy())
        with pytest.raises(ManagedExecutionLeaseHeld):
            with managed_execution_lease(tmp_path):
                pass

    assert injected
    assert load_execution_policy(tmp_path) is None
    assert (tmp_path / ".claude-kit-managed-execution.lock").is_file()


def test_configuration_rollback_cannot_erase_new_pipeline_evidence(
    tmp_path, payload, monkeypatch
):
    _write_manifest(tmp_path, payload)
    snapshot = tmp_path / StateLayout.neutral().pipeline_snapshot
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    snapshot.write_text('{"revision":1}\n', encoding="utf-8")
    original_write = ProjectFS.write_text

    def fail_after_manifest_write(self, rel, text, **kwargs):
        written = original_write(self, rel, text, **kwargs)
        if rel == StateLayout.neutral().manifest:
            # Model evidence durably appended after the config transaction took
            # its rollback snapshot but before its own verification failed.
            snapshot.write_text('{"revision":2}\n', encoding="utf-8")
            raise OSError("injected config verification failure")
        return written

    monkeypatch.setattr(ProjectFS, "write_text", fail_after_manifest_write)

    with pytest.raises(ExecutionConfigError, match="verification failure"):
        configure_execution_policy(tmp_path, _policy())

    assert snapshot.read_text(encoding="utf-8") == '{"revision":2}\n'
    assert load_execution_policy(tmp_path) is None


def test_managed_lease_rejects_a_swapped_root_entry(tmp_path, monkeypatch):
    replacement_fd = None

    def swap(root_fd, _lease_fd):
        nonlocal replacement_fd
        os.unlink(".claude-kit-managed-execution.lock", dir_fd=root_fd)
        replacement_fd = os.open(
            ".claude-kit-managed-execution.lock",
            os.O_RDWR | os.O_CREAT | os.O_EXCL,
            0o600,
            dir_fd=root_fd,
        )

    monkeypatch.setattr(execution_lease_module, "_after_lease_open", swap)

    try:
        with pytest.raises(UnsafePathError, match="managed execution lock"):
            with managed_execution_lease(tmp_path):
                pass
    finally:
        if replacement_fd is not None:
            os.close(replacement_fd)


def test_managed_lease_refuses_to_commandeer_a_preexisting_user_file(tmp_path):
    lock = tmp_path / ".claude-kit-managed-execution.lock"
    lock.write_text("user-authored content\n", encoding="utf-8")
    lock.chmod(0o644)
    before = lock.read_bytes()
    before_mode = lock.stat().st_mode & 0o777

    with pytest.raises(UnsafePathError, match="managed execution lock"):
        with managed_execution_lease(tmp_path):
            pass

    assert lock.read_bytes() == before
    assert lock.stat().st_mode & 0o777 == before_mode


def test_managed_lease_rejects_a_symlinked_project_root(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(real, target_is_directory=True)

    with pytest.raises(UnsafePathError, match="project-root component"):
        with managed_execution_lease(alias):
            pass

    assert not (real / ".claude-kit-managed-execution.lock").exists()


def test_managed_lease_recovers_a_crash_during_first_marker_write(
    tmp_path, monkeypatch
):
    crash = True

    def die_after_create(_root_fd, _lease_fd):
        nonlocal crash
        if crash:
            crash = False
            raise _SimulatedLeaseInitializationDeath()

    monkeypatch.setattr(
        execution_lease_module,
        "_after_lease_create",
        die_after_create,
    )

    with pytest.raises(_SimulatedLeaseInitializationDeath):
        with managed_execution_lease(tmp_path):
            pass

    lock = tmp_path / ".claude-kit-managed-execution.lock"
    assert lock.read_bytes() == b""
    with managed_execution_lease(tmp_path):
        assert lock.read_bytes() == b"claude-kit-managed-execution-lock:v1\n"


@pytest.mark.parametrize(
    ("legacy_relative", "layout"),
    [
        (".ckit/state/managed-execution.lock", "neutral"),
        (".claude/state/managed-execution.lock", "legacy"),
    ],
)
def test_managed_lease_contends_with_the_previous_release_lock(
    tmp_path, payload, legacy_relative, layout
):
    import fcntl

    if layout == "neutral":
        _write_manifest(tmp_path, payload)
    else:
        continuity = tmp_path / StateLayout.legacy_claude().continuity
        continuity.parent.mkdir(parents=True)
        continuity.write_text("legacy state\n", encoding="utf-8")
    legacy_lock = tmp_path / legacy_relative
    legacy_lock.parent.mkdir(parents=True, exist_ok=True)
    legacy_fd = os.open(legacy_lock, os.O_RDWR | os.O_CREAT, 0o600)
    os.fchmod(legacy_fd, 0o600)
    try:
        fcntl.flock(legacy_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(ManagedExecutionLeaseHeld, match="earlier claude-kit"):
            with managed_execution_lease(tmp_path):
                pass
    finally:
        fcntl.flock(legacy_fd, fcntl.LOCK_UN)
        os.close(legacy_fd)

    with managed_execution_lease(tmp_path):
        contender_fd = os.open(legacy_lock, os.O_RDWR)
        try:
            with pytest.raises(BlockingIOError):
                fcntl.flock(contender_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        finally:
            os.close(contender_fd)


def test_legacy_managed_lease_also_binds_the_prospective_neutral_path(tmp_path):
    import fcntl

    continuity = tmp_path / StateLayout.legacy_claude().continuity
    continuity.parent.mkdir(parents=True)
    continuity.write_text("legacy state\n", encoding="utf-8")
    paths = (
        tmp_path / ".ckit/state/managed-execution.lock",
        tmp_path / ".claude/state/managed-execution.lock",
    )

    with managed_execution_lease(tmp_path):
        assert all(path.is_file() for path in paths)
        for path in paths:
            contender_fd = os.open(path, os.O_RDWR)
            try:
                with pytest.raises(BlockingIOError):
                    fcntl.flock(contender_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            finally:
                os.close(contender_fd)


@pytest.mark.parametrize(
    ("layout", "protected", "journal", "mutation"),
    [
        (
            "neutral",
            ".ckit",
            ".ckit/config/upgrade-in-progress.json",
            ".ckit/config/rollback-probe",
        ),
        (
            "legacy",
            ".claude",
            ".claude/config/upgrade-in-progress.json",
            ".claude/config/rollback-probe",
        ),
    ],
)
def test_transaction_rollback_preserves_active_compatibility_lock_inode(
    tmp_path, payload, layout, protected, journal, mutation
):
    import fcntl

    if layout == "neutral":
        _write_manifest(tmp_path, payload)
        lock = tmp_path / ".ckit/state/managed-execution.lock"
    else:
        continuity = tmp_path / StateLayout.legacy_claude().continuity
        continuity.parent.mkdir(parents=True)
        continuity.write_text("legacy state\n", encoding="utf-8")
        lock = tmp_path / ".claude/state/managed-execution.lock"
    fs = ProjectFS(tmp_path)

    with managed_execution_lease(tmp_path):
        before = lock.stat()
        with pytest.raises(RuntimeError, match="trigger rollback"):
            with ProjectTransaction(
                fs,
                operation="upgrade",
                protected_paths=(protected,),
                journal_path=journal,
            ):
                fs.write_text(mutation, "changed\n")
                raise RuntimeError("trigger rollback")

        after = lock.stat()
        assert (after.st_dev, after.st_ino) == (before.st_dev, before.st_ino)
        contender_fd = os.open(lock, os.O_RDWR)
        try:
            with pytest.raises(BlockingIOError):
                fcntl.flock(contender_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        finally:
            os.close(contender_fd)


def test_transaction_rollback_fails_closed_on_unsafe_compatibility_lock_metadata(
    tmp_path, payload
):
    _write_manifest(tmp_path, payload)
    fs = ProjectFS(tmp_path)
    lock = tmp_path / ".ckit/state/managed-execution.lock"

    with managed_execution_lease(tmp_path):
        with pytest.raises(UnsafePathError, match="mode-0600 regular file"):
            with ProjectTransaction(
                fs,
                operation="upgrade",
                protected_paths=(".ckit",),
                journal_path=".ckit/config/upgrade-in-progress.json",
            ):
                lock.chmod(0o644)
                raise RuntimeError("trigger rollback")


def test_managed_lease_releases_compatibility_lock_before_root_lock(
    tmp_path, payload, monkeypatch
):
    import fcntl

    _write_manifest(tmp_path, payload)
    original_flock = fcntl.flock
    unlocked: list[tuple[int, int]] = []

    def record_unlock(fd, operation):
        if operation == fcntl.LOCK_UN:
            info = os.fstat(fd)
            unlocked.append((info.st_dev, info.st_ino))
        return original_flock(fd, operation)

    monkeypatch.setattr(fcntl, "flock", record_unlock)
    with managed_execution_lease(tmp_path):
        root_info = (tmp_path / ".claude-kit-managed-execution.lock").stat()
        compatibility_info = (tmp_path / ".ckit/state/managed-execution.lock").stat()

    assert unlocked[-2:] == [
        (compatibility_info.st_dev, compatibility_info.st_ino),
        (root_info.st_dev, root_info.st_ino),
    ]


def test_concurrent_first_managed_lease_has_one_owner(tmp_path, monkeypatch):
    create_barrier = threading.Barrier(2)
    owner_entered = threading.Event()
    contender_finished = threading.Event()
    release_owner = threading.Event()
    outcomes: list[str] = []

    def before_create(_root_fd):
        create_barrier.wait(timeout=5)

    monkeypatch.setattr(execution_lease_module, "_before_lease_create", before_create)

    def compete() -> None:
        try:
            with managed_execution_lease(tmp_path):
                outcomes.append("owner")
                owner_entered.set()
                if not release_owner.wait(timeout=5):
                    raise AssertionError("test did not release managed lease owner")
        except ManagedExecutionLeaseHeld:
            outcomes.append("contender-refused")
            contender_finished.set()
        except BaseException as exc:  # pragma: no cover - asserted below
            outcomes.append(f"unexpected:{exc}")
            contender_finished.set()

    workers = [threading.Thread(target=compete) for _ in range(2)]
    for worker in workers:
        worker.start()
    assert owner_entered.wait(timeout=5)
    try:
        assert contender_finished.wait(timeout=5)
    finally:
        release_owner.set()
        for worker in workers:
            worker.join(timeout=5)

    assert not any(worker.is_alive() for worker in workers)
    assert sorted(outcomes) == ["contender-refused", "owner"]
