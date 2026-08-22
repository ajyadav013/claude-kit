"""Portable run-owned worktree fallback and cleanup safety."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from claude_kit.cli import app
from claude_kit.worktrees import (
    WorktreeError,
    WorktreeManager,
    WorktreeStatus,
)

RUNNER = CliRunner()


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
