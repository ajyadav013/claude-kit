"""Portable run-owned worktree fallback and cleanup safety."""

from __future__ import annotations

import json
import shlex
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from claude_kit import worktrees as worktrees_module
from claude_kit.cli import app
from claude_kit.worktrees import (
    WorktreeError,
    WorktreeManager,
    WorktreeStatus,
)

RUNNER = CliRunner()


class _SimulatedCreateCrash(BaseException):
    pass


def _repo(path: Path) -> Path:
    path.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=path, check=True)
    subprocess.run(
        ["git", "config", "user.email", "worktrees@example.invalid"],
        cwd=path,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Worktree Tests"], cwd=path, check=True
    )
    (path / "README.md").write_text("root\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-qm", "root"], cwd=path, check=True)
    (path / ".ckit/config").mkdir(parents=True)
    (path / ".ckit/config/init-options.json").write_text("{}\n", encoding="utf-8")
    return path


def test_create_verify_mark_and_clean_worktree(tmp_path: Path) -> None:
    repo = _repo(tmp_path / "project")
    manager = WorktreeManager(repo)
    record = manager.create("run-1", "worker-a")
    target = (repo / record.target_path).resolve()

    assert record.status is WorktreeStatus.ACTIVE
    assert target.is_dir()
    assert target.parent == manager.container / "run-1"
    assert manager.verify("run-1", "worker-a") == record
    marked = manager.mark("run-1", "worker-a", "succeeded")
    assert marked.status is WorktreeStatus.SUCCEEDED
    removed = manager.cleanup("run-1", "worker-a")
    assert removed.status is WorktreeStatus.REMOVED
    assert not target.exists()
    assert manager.resume_run("run-1") == (removed,)


def test_checkpoint_binds_head_tracked_untracked_and_ignored_content(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path / "project")
    manager = WorktreeManager(repo)
    record = manager.create("checkpoint-run", "worker")
    target = (repo / record.target_path).resolve()

    initial = manager.checkpoint("checkpoint-run", "worker")
    (target / "README.md").write_text("changed\n", encoding="utf-8")
    tracked_change = manager.checkpoint("checkpoint-run", "worker")
    assert tracked_change.head_commit == initial.head_commit
    assert tracked_change.tracked_digest != initial.tracked_digest
    assert tracked_change.untracked_digest == initial.untracked_digest
    assert tracked_change.content_digest != initial.content_digest

    (target / "handoff.json").write_text('{"result":"ok"}\n', encoding="utf-8")
    untracked_change = manager.checkpoint("checkpoint-run", "worker")
    assert untracked_change.tracked_digest == tracked_change.tracked_digest
    assert untracked_change.untracked_digest != tracked_change.untracked_digest

    (target / ".gitignore").write_text("ignored.log\n", encoding="utf-8")
    subprocess.run(
        ["git", "add", ".gitignore", "README.md", "handoff.json"],
        cwd=target,
        check=True,
    )
    subprocess.run(["git", "commit", "-qm", "checkpoint"], cwd=target, check=True)
    committed = manager.checkpoint("checkpoint-run", "worker")
    (target / "ignored.log").write_text("ignored noise\n", encoding="utf-8")
    ignored = manager.checkpoint("checkpoint-run", "worker")
    assert ignored.head_commit == committed.head_commit
    assert ignored.tracked_digest == committed.tracked_digest
    assert ignored.untracked_digest != committed.untracked_digest
    assert ignored.content_digest != committed.content_digest
    assert committed.head_commit != initial.head_commit


def test_checkpoint_binds_index_oid_when_worktree_bytes_are_restored(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path / "project")
    manager = WorktreeManager(repo)
    record = manager.create("index-run", "worker")
    target = (repo / record.target_path).resolve()
    initial = manager.checkpoint("index-run", "worker")

    readme = target / "README.md"
    readme.write_text("staged payload\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=target, check=True)
    readme.write_text("root\n", encoding="utf-8")
    staged_only = manager.checkpoint("index-run", "worker")

    assert staged_only.head_commit == initial.head_commit
    assert staged_only.tracked_digest != initial.tracked_digest
    assert staged_only.content_digest != initial.content_digest


def test_checkpoint_rejects_incomplete_tracked_record_collection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _repo(tmp_path / "project")
    manager = WorktreeManager(repo)
    manager.create("cardinality-run", "worker")
    collect_records = worktrees_module._workspace_file_records

    def omit_last_record(root: Path, paths: list[bytes]) -> list[bytes]:
        records = collect_records(root, paths)
        return records[:-1]

    monkeypatch.setattr(worktrees_module, "_workspace_file_records", omit_last_record)
    with pytest.raises(
        WorktreeError, match="managed workspace checkpoint record count mismatch"
    ):
        manager.checkpoint("cardinality-run", "worker")


def test_dirty_and_failed_worker_artifacts_require_two_explicit_discards(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path / "project")
    manager = WorktreeManager(repo)
    record = manager.create("run-2", "worker-b")
    target = (repo / record.target_path).resolve()
    (target / "failure.log").write_text("diagnostic\n", encoding="utf-8")
    failed = manager.mark(
        "run-2", "worker-b", WorktreeStatus.FAILED, failure_reason="tests failed"
    )
    assert failed.failure_reason == "tests failed"

    with pytest.raises(WorktreeError, match="failed worker artifacts are preserved"):
        manager.cleanup("run-2", "worker-b")
    with pytest.raises(WorktreeError, match="uncommitted artifacts"):
        manager.cleanup("run-2", "worker-b", discard_failed=True)
    assert target.is_dir()

    removed = manager.cleanup(
        "run-2", "worker-b", discard_failed=True, discard_changes=True
    )
    assert removed.status is WorktreeStatus.REMOVED
    assert not target.exists()


def test_abort_and_resume_preserve_exact_run_owned_paths(tmp_path: Path) -> None:
    repo = _repo(tmp_path / "project")
    manager = WorktreeManager(repo)
    first = manager.create("run-3", "frontend")
    second = manager.create("run-3", "backend")
    manager.create("another-run", "worker")

    aborted = manager.abort_run("run-3")
    assert {record.worker_id for record in aborted} == {"frontend", "backend"}
    assert {record.status for record in aborted} == {WorktreeStatus.ABORTED}
    assert manager.resume_run("run-3") == aborted
    assert all((repo / record.target_path).resolve().is_dir() for record in aborted)
    assert manager.records("another-run")[0].status is WorktreeStatus.ACTIVE

    for record in (first, second):
        manager.cleanup(record.run_id, record.worker_id)
    manager.cleanup("another-run", "worker")


def test_registry_path_tampering_never_redirects_cleanup(tmp_path: Path) -> None:
    repo = _repo(tmp_path / "project")
    manager = WorktreeManager(repo)
    record = manager.create("run-4", "worker")
    target = (repo / record.target_path).resolve()
    outside = tmp_path / "must-survive"
    outside.mkdir()
    marker = outside / "marker"
    marker.write_text("keep\n", encoding="utf-8")

    registry = repo / manager.registry_rel
    document = json.loads(registry.read_text(encoding="utf-8"))
    document["records"][0]["target_path"] = "../must-survive"
    registry.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(WorktreeError, match="ownership path mismatch"):
        manager.cleanup("run-4", "worker", discard_changes=True)
    assert marker.read_text(encoding="utf-8") == "keep\n"
    assert target.is_dir()

    document["records"][0]["target_path"] = record.target_path
    registry.write_text(json.dumps(document), encoding="utf-8")
    manager.cleanup("run-4", "worker")


def test_precreated_container_symlink_cannot_redirect_creation(tmp_path: Path) -> None:
    repo = _repo(tmp_path / "project")
    manager = WorktreeManager(repo)
    outside = tmp_path / "outside"
    outside.mkdir()
    manager.container.symlink_to(outside, target_is_directory=True)

    with pytest.raises(WorktreeError, match="link/reparse point"):
        manager.create("redirect-run", "worker")

    assert list(outside.iterdir()) == []


def test_git_marker_is_bound_to_exact_registered_admin_directory(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path / "project")
    manager = WorktreeManager(repo)
    record = manager.create("marker-run", "worker")
    target = repo / record.target_path
    marker = target / ".git"
    original = marker.read_text(encoding="utf-8")

    marker.write_text(f"gitdir: {(repo / '.git').resolve()}\n", encoding="utf-8")
    with pytest.raises(WorktreeError, match="registered worktree admin dir"):
        manager.verify("marker-run", "worker")
    with pytest.raises(WorktreeError):
        manager.checkpoint("marker-run", "worker")

    marker.write_text(original, encoding="utf-8")
    manager.cleanup("marker-run", "worker")


def test_cleanup_preserves_ignored_only_content_without_explicit_discard(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path / "project")
    (repo / ".gitignore").write_text("ignored.log\n", encoding="utf-8")
    subprocess.run(["git", "add", ".gitignore"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "ignore fixture"], cwd=repo, check=True)
    manager = WorktreeManager(repo)
    record = manager.create("ignored-run", "worker")
    target = repo / record.target_path
    (target / "ignored.log").write_text("must survive\n", encoding="utf-8")

    with pytest.raises(WorktreeError, match="uncommitted artifacts"):
        manager.cleanup("ignored-run", "worker")
    assert (target / "ignored.log").read_text(encoding="utf-8") == "must survive\n"

    manager.cleanup("ignored-run", "worker", discard_changes=True)


def test_cleanup_preserves_committed_worker_changes_without_explicit_discard(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path / "project")
    manager = WorktreeManager(repo)
    record = manager.create("commit-run", "worker")
    target = repo / record.target_path
    (target / "README.md").write_text("worker commit\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=target, check=True)
    subprocess.run(["git", "commit", "-qm", "worker output"], cwd=target, check=True)

    with pytest.raises(WorktreeError, match="committed or uncommitted artifacts"):
        manager.cleanup("commit-run", "worker")

    manager.cleanup("commit-run", "worker", discard_changes=True)


@pytest.mark.parametrize(
    ("run_id", "worker_id"),
    [("../escape", "worker"), ("run", "../../escape"), ("", "worker")],
)
def test_identifiers_cannot_escape_bounded_container(
    tmp_path: Path, run_id: str, worker_id: str
) -> None:
    manager = WorktreeManager(_repo(tmp_path / "project"))
    with pytest.raises(WorktreeError):
        manager.create(run_id, worker_id)


def test_cli_worktree_lifecycle_uses_json_records(tmp_path: Path) -> None:
    repo = _repo(tmp_path / "project")
    created = RUNNER.invoke(
        app,
        ["worktree", "create", "cli-run", "worker", "--path", str(repo)],
    )
    assert created.exit_code == 0, created.output
    record = json.loads(created.stdout)
    assert record["status"] == "active"

    listed = RUNNER.invoke(
        app,
        ["worktree", "list", "--run-id", "cli-run", "--path", str(repo)],
    )
    assert listed.exit_code == 0
    assert json.loads(listed.stdout) == [record]

    marked = RUNNER.invoke(
        app,
        [
            "worktree",
            "mark",
            "cli-run",
            "worker",
            "--status",
            "succeeded",
            "--path",
            str(repo),
        ],
    )
    assert marked.exit_code == 0, marked.output
    removed = RUNNER.invoke(
        app,
        ["worktree", "cleanup", "cli-run", "worker", "--path", str(repo)],
    )
    assert removed.exit_code == 0, removed.output
    assert json.loads(removed.stdout)["status"] == "removed"


def test_create_intent_recovers_after_git_worktree_add_before_registry_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _repo(tmp_path / "project")
    manager = WorktreeManager(repo)
    anchored_add = worktrees_module._run_git_worktree_add_anchored

    def crash_after_add(*args, **kwargs):
        anchored_add(*args, **kwargs)
        raise _SimulatedCreateCrash

    monkeypatch.setattr(
        worktrees_module, "_run_git_worktree_add_anchored", crash_after_add
    )
    with pytest.raises(_SimulatedCreateCrash):
        manager.create("creating-after-add", "worker")
    intent = manager.records("creating-after-add")[0]
    assert intent.status is WorktreeStatus.CREATING
    assert (repo / intent.target_path).is_dir()

    monkeypatch.setattr(
        worktrees_module, "_run_git_worktree_add_anchored", anchored_add
    )
    active = manager.create("creating-after-add", "worker")
    assert active.status is WorktreeStatus.ACTIVE
    assert manager.verify(active.run_id, active.worker_id) == active
    manager.cleanup(active.run_id, active.worker_id)


def test_create_intent_recovers_partial_filter_neutral_materialization(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _repo(tmp_path / "project")
    (repo / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "app.py"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "add app"], cwd=repo, check=True)
    manager = WorktreeManager(repo)
    materialize = worktrees_module._materialize_head_without_repository_commands

    def crash_after_one_path(target: Path) -> None:
        worktrees_module._run_git(target, "read-tree", "HEAD")
        worktrees_module._run_git(
            target, "checkout-index", "--force", "--", "README.md"
        )
        raise _SimulatedCreateCrash

    monkeypatch.setattr(
        worktrees_module,
        "_materialize_head_without_repository_commands",
        crash_after_one_path,
    )
    with pytest.raises(_SimulatedCreateCrash):
        manager.create("partial-materialization", "worker")
    intent = manager.records("partial-materialization")[0]
    target = repo / intent.target_path
    assert intent.status is WorktreeStatus.CREATING
    assert (target / "README.md").is_file()
    assert not (target / "app.py").exists()

    monkeypatch.setattr(
        worktrees_module,
        "_materialize_head_without_repository_commands",
        materialize,
    )
    active = manager.resume_run("partial-materialization")[0]
    assert active.status is WorktreeStatus.ACTIVE
    assert (target / "README.md").read_text(encoding="utf-8") == "root\n"
    assert (target / "app.py").read_text(encoding="utf-8") == "VALUE = 1\n"
    manager.cleanup(active.run_id, active.worker_id)


def test_create_intent_recovers_after_owned_target_mkdir_before_git_add(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _repo(tmp_path / "project")
    manager = WorktreeManager(repo)
    anchored_add = worktrees_module._run_git_worktree_add_anchored

    def crash_before_add(*_args, **_kwargs):
        raise _SimulatedCreateCrash

    monkeypatch.setattr(
        worktrees_module, "_run_git_worktree_add_anchored", crash_before_add
    )
    with pytest.raises(_SimulatedCreateCrash):
        manager.create("creating-after-mkdir", "worker")
    intent = manager.records("creating-after-mkdir")[0]
    target = repo / intent.target_path
    assert intent.status is WorktreeStatus.CREATING
    assert target.is_dir() and list(target.iterdir()) == []

    monkeypatch.setattr(
        worktrees_module, "_run_git_worktree_add_anchored", anchored_add
    )
    resumed = manager.resume_run("creating-after-mkdir")[0]
    assert resumed.status is WorktreeStatus.ACTIVE
    manager.cleanup(resumed.run_id, resumed.worker_id)

    monkeypatch.setattr(
        worktrees_module, "_run_git_worktree_add_anchored", crash_before_add
    )
    with pytest.raises(_SimulatedCreateCrash):
        manager.create("aborting-after-mkdir", "worker")
    monkeypatch.setattr(
        worktrees_module, "_run_git_worktree_add_anchored", anchored_add
    )
    aborted = manager.abort_run("aborting-after-mkdir")[0]
    assert aborted.status is WorktreeStatus.ABORTED
    manager.cleanup(aborted.run_id, aborted.worker_id)


def test_anchored_create_cannot_follow_a_swapped_run_parent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _repo(tmp_path / "project")
    manager = WorktreeManager(repo)
    outside = tmp_path / "outside"
    outside.mkdir()
    anchored_add = worktrees_module._run_git_worktree_add_anchored

    def swap_parent_then_add(repository: Path, **kwargs) -> None:
        run_parent = manager.container / "race-run"
        moved = manager.container / "race-run-moved"
        run_parent.rename(moved)
        run_parent.symlink_to(outside, target_is_directory=True)
        anchored_add(repository, **kwargs)

    monkeypatch.setattr(
        worktrees_module,
        "_run_git_worktree_add_anchored",
        swap_parent_then_add,
    )
    with pytest.raises(WorktreeError, match="namespace changed"):
        manager.create("race-run", "worker")

    assert list(outside.iterdir()) == []
    registered = subprocess.run(
        ["git", "-C", str(repo), "worktree", "list", "--porcelain"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert "race-run-moved/worker" not in registered


def test_abort_cancels_never_created_intent_and_preserves_created_intent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _repo(tmp_path / "project")
    manager = WorktreeManager(repo)
    finish = WorktreeManager._finish_creating

    def crash_before_add(
        _manager: WorktreeManager, _intent: worktrees_module.WorktreeRecord
    ) -> worktrees_module.WorktreeRecord:
        raise _SimulatedCreateCrash

    monkeypatch.setattr(WorktreeManager, "_finish_creating", crash_before_add)
    with pytest.raises(_SimulatedCreateCrash):
        manager.create("creating-before-add", "worker")
    monkeypatch.setattr(WorktreeManager, "_finish_creating", finish)
    cancelled = manager.abort_run("creating-before-add")[0]
    assert cancelled.status is WorktreeStatus.REMOVED
    assert not (repo / cancelled.target_path).exists()

    anchored_add = worktrees_module._run_git_worktree_add_anchored

    def crash_after_add(*args, **kwargs):
        anchored_add(*args, **kwargs)
        raise _SimulatedCreateCrash

    monkeypatch.setattr(
        worktrees_module, "_run_git_worktree_add_anchored", crash_after_add
    )
    with pytest.raises(_SimulatedCreateCrash):
        manager.create("creating-abort-after-add", "worker")
    monkeypatch.setattr(
        worktrees_module, "_run_git_worktree_add_anchored", anchored_add
    )
    preserved = manager.abort_run("creating-abort-after-add")[0]
    assert preserved.status is WorktreeStatus.ABORTED
    assert (repo / preserved.target_path).is_dir()
    manager.cleanup(preserved.run_id, preserved.worker_id)


def test_create_intent_rejects_unregistered_target_wrong_head_and_index(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _repo(tmp_path / "project")
    (repo / "README.md").write_text("second\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "second"], cwd=repo, check=True)
    manager = WorktreeManager(repo)
    finish = WorktreeManager._finish_creating

    def crash_before_add(
        _manager: WorktreeManager, _intent: worktrees_module.WorktreeRecord
    ) -> worktrees_module.WorktreeRecord:
        raise _SimulatedCreateCrash

    monkeypatch.setattr(WorktreeManager, "_finish_creating", crash_before_add)
    with pytest.raises(_SimulatedCreateCrash):
        manager.create("hostile-target", "worker")
    hostile = manager.records("hostile-target")[0]
    target = repo / hostile.target_path
    target.mkdir(parents=True)
    monkeypatch.setattr(WorktreeManager, "_finish_creating", finish)
    with pytest.raises(WorktreeError, match="ownership"):
        manager.create("hostile-target", "worker")

    anchored_add = worktrees_module._run_git_worktree_add_anchored

    def crash_after_add(*args, **kwargs):
        anchored_add(*args, **kwargs)
        raise _SimulatedCreateCrash

    monkeypatch.setattr(
        worktrees_module, "_run_git_worktree_add_anchored", crash_after_add
    )
    with pytest.raises(_SimulatedCreateCrash):
        manager.create("wrong-head", "worker")
    wrong_head = manager.records("wrong-head")[0]
    wrong_head_target = repo / wrong_head.target_path
    subprocess.run(
        ["git", "-C", str(wrong_head_target), "update-ref", "HEAD", "HEAD^"],
        check=True,
    )
    monkeypatch.setattr(
        worktrees_module, "_run_git_worktree_add_anchored", anchored_add
    )
    with pytest.raises(WorktreeError, match="HEAD differs"):
        manager.create("wrong-head", "worker")

    monkeypatch.setattr(
        worktrees_module, "_run_git_worktree_add_anchored", crash_after_add
    )
    with pytest.raises(_SimulatedCreateCrash):
        manager.create("wrong-index", "worker")
    wrong_index = manager.records("wrong-index")[0]
    wrong_index_target = repo / wrong_index.target_path
    subprocess.run(
        ["git", "-C", str(wrong_index_target), "read-tree", "HEAD^"], check=True
    )
    monkeypatch.setattr(
        worktrees_module, "_run_git_worktree_add_anchored", anchored_add
    )
    with pytest.raises(WorktreeError, match="index differs"):
        manager.create("wrong-index", "worker")


def test_lifecycle_git_commands_execute_no_repo_filters_hooks_or_fsmonitor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _repo(tmp_path / "project")
    (repo / ".gitattributes").write_text("README.md filter=hostile\n", encoding="utf-8")
    subprocess.run(["git", "add", ".gitattributes"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "attribute fixture"], cwd=repo, check=True)
    marker = tmp_path / "repository-command-ran"
    hostile = tmp_path / "hostile.sh"
    hostile.write_text(
        "#!/bin/sh\n" + f": > {shlex.quote(str(marker))}\n" + "exit 1\n",
        encoding="utf-8",
    )
    hostile.chmod(0o700)
    command = shlex.quote(str(hostile))
    for key in (
        "filter.hostile.clean",
        "filter.hostile.smudge",
        "filter.hostile.process",
    ):
        subprocess.run(["git", "config", key, command], cwd=repo, check=True)
    subprocess.run(
        ["git", "config", "filter.hostile.required", "true"], cwd=repo, check=True
    )
    subprocess.run(["git", "config", "core.fsmonitor", command], cwd=repo, check=True)
    for hook_name in ("post-checkout", "post-index-change"):
        hook = repo / ".git/hooks" / hook_name
        hook.write_text(hostile.read_text(encoding="utf-8"), encoding="utf-8")
        hook.chmod(0o700)
    marker.unlink(missing_ok=True)
    redirected_git = tmp_path / "redirected-git"
    redirected_worktree = tmp_path / "redirected-worktree"
    redirected_git.mkdir()
    redirected_worktree.mkdir()
    hostile_index = tmp_path / "redirected-index"
    monkeypatch.setenv("GIT_DIR", str(redirected_git))
    monkeypatch.setenv("GIT_WORK_TREE", str(redirected_worktree))
    monkeypatch.setenv("GIT_INDEX_FILE", str(hostile_index))

    manager = WorktreeManager(repo)
    record = manager.create("no-repository-commands", "worker")
    manager.checkpoint(record.run_id, record.worker_id)
    manager.mark(record.run_id, record.worker_id, WorktreeStatus.SUCCEEDED)
    manager.cleanup(record.run_id, record.worker_id)

    assert not marker.exists()
    assert not hostile_index.exists()
    assert list(redirected_git.iterdir()) == []
    assert list(redirected_worktree.iterdir()) == []
